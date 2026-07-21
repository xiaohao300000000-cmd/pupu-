# 朴朴 DeepSeek 智能购物助手

这是一个正在开发的 Python 模块化单体项目：由 DeepSeek 理解用户的采购或菜品需求，通过受控工具查询朴朴真实商品，组建助手购物车，并在用户确认后安全同步到真实购物车。

> 当前状态：开发中。公开服务器时间验证脚本已建立，但最近一次真实网络请求失败（PupuNetworkError）；`seal/sign` 静态跟进已确认存在请求级线索但仍未恢复完整算法；手机号登录、受保护请求签名、真实商品查询和真实购物车加购尚未完成验收。

## 当前已实现

- 独立 `PupuSignatureService` 契约，公开请求与受保护请求显式分类。
- 强制朴朴调用链：`Business module → SignatureService → PupuHttpClient → Pupu API`。
- 受保护请求在没有可验证签名时会在网络 I/O 之前失败，不会降级成无签名请求。
- HTTP 超时、TLS、网络、HTTP 状态、JSON 解析和朴朴业务错误分类。
- DeepSeek V4 兼容的工具调用 Provider，模型、Base URL、API Key 和超时全部可配置。
- 工具白名单、Pydantic 参数校验、非法工具拒绝和最大工具轮数限制。
- 与朴朴真实购物车隔离的版本化助手购物车。
- 采购状态机：只有“确认版本一致 + 价格库存复核无变化”后才会暴露真实写入工具。
- 两阶段写入核心：预览哈希、短期确认凭证、精确确认短语、一次性消费、幂等键和写后回读判定。
- Windows 兼容的确认存储文件锁；全量测试当前 `62 passed`。

## 架构边界

```text
用户消息
  → PurchaseAgent (DeepSeek)
    → ToolRegistry (当前状态白名单 + 参数校验)
      → AssistantCart (本地计划，版本化)
        → ConfirmationStore (短期、一次性)
          → CartControl (复核 → 写入 → 回读)
            → Pupu business module
              → PupuSignatureService
                → PupuHttpClient
                  → Pupu API
```

DeepSeek 不能读取朴朴 Token，不能生成签名，不能直接访问网络，也不能绕过状态机写真实购物车。

## 快速开始

需要 Python 3.12+。

```bash
python3.12 -m venv .venv
.venv/bin/pip install -e '.[dev]'
cp .env.example .env
.venv/bin/pytest
```

Windows 本机可直接运行：

```powershell
py -3.12 -m pytest -q
```

验证公开朴朴服务器时间接口：

```bash
.venv/bin/python scripts/validate_pupu_public.py
```

该脚本会发送真实网络请求，但不需要账号，不修改购物车。脱敏证据保存在已忽略的 `.local/evidence/` 中。最近一次运行失败，不能记为真实接口验收通过。

## 配置

复制 [.env.example](.env.example) 后填写本地配置。关键安全默认值：

```text
PUPU_VERIFY_TLS=true
PUPU_ALLOW_LIVE_MUTATION=false
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_MODEL=deepseek-v4-flash
```

`LLM_API_KEY` 只能放在本地 `.env` 或运行时环境变量中。`.env`、凭证、APK、本地工具和验证证据均不进入 Git。

## 真实验证状态

| 能力 | 状态 | 完成标准 |
|---|---|---|
| 公开服务器时间 | 最近一次运行失败 | HTTP 成功、`errcode=0`、返回可用时间戳 |
| DeepSeek 工具循环 | 单元测试已通过 | 尚未使用用户 API Key 进行真实请求 |
| 助手购物车 | 单元测试已通过 | 本地版本、幂等和门店隔离 |
| 两阶段购物车控制 | 单元测试已通过 | 尚未接入朴朴真实购物车 Gateway |
| 手机号登录 | 未验证 | 需要用户本人输入当次验证码 |
| 受保护 `seal/sign` | 未验证 | 需要完整实现和真实请求向量 |
| 真实商品查询 | 未验证 | 需要当前门店与账号上下文 |
| 真实购物车加购 | 未验证 | 写入成功 + API 回读 + 手机 App 确认 |

Mock 只用于单元测试，不会被记为真实朴朴验收结果。

## 文档

- [总体设计](docs/superpowers/specs/2026-07-21-pupu-assistant-design.md)
- [签名与购物车实施计划](docs/superpowers/plans/2026-07-21-pupu-signature-and-cart-control.md)
- [GitHub 上游审计](docs/research/pupu-signature-audit-2026-07-21.md)
- [APK 元数据复核](docs/research/apk-metadata-review-2026-07-21.md)
- [`seal/sign` 静态跟进](docs/research/seal-sign-static-followup-2026-07-21.md)
- [复核证据表](docs/research/evidence-table-2026-07-21.md)
- [当前交接说明](HANDOFF.md)

## 许可与来源

项目会优先复用可用的 GitHub 模块，但任何复制代码都必须保留来源和许可证。`cddjr/check` 当前仅作协议研究上游；已发现其 MIT License 与 README 中的限制表述存在口径冲突，商业使用前需另行确认。


## Black-box signer fixture path

- `.local/bin/pupusgn` is a committed offline Mac/Linux signer wrapper. It reads JSON, merges supplied black-box `seal/sign` headers, writes JSON to stdout, and performs no HTTP requests.
- `.local/pupusgn-test.json` contains two redacted supplied-result cases: one protected product read and one cart write fixture.
- `.local/pupusgn-sdu-input.json` contains two stdin-to-local-sdu cases with no precomputed signatures; it requires `--sdu-command` or `PUPUSGN_SDU_CMD`.
- `.local/pupu-cases.json` records current 6.4.9 product/cart candidate routes with placeholder-only method/path/query/body shapes.
- Details: [Black-box Pupu signer materials](docs/research/blackbox-signer-materials-2026-07-21.md)

# Pupu Assistant Handoff

更新时间：2026-07-21

开发分支：`codex/pupu-signature-cart-control`

目标仓库：`xiaohao300000000-cmd/pupu-`

## 交付状态

本分支已完成并拆分提交：

1. Python 包骨架与安全默认配置。
2. `cddjr/check` 及相关上游的可追溯审计记录。
3. 独立 `PupuSignatureService` 接口和“受保护签名不可用”显式失败实现。
4. 强制签名优先的 `PupuHttpClient`。
5. 公开服务器时间真实验证脚本与脱敏证据模型。
6. DeepSeek V4 工具调用 Provider、工具白名单、参数校验和轮数上限。
7. 版本化、幂等的助手购物车。
8. 采购状态机，真实写入工具只在确认与复核通过后暴露。
9. 购物车两阶段控制：预览哈希、过期、精确短语、一次性消费、幂等键、超时后回读判定。

## 真实验证边界

| 接口或能力 | 当前证据 |
|---|---|
| `GET https://j1.pupuapi.com/client/base/data` | 真实请求通过，`errcode=0`，签名模式 `none` |
| DeepSeek Tool Calls | MockTransport 单元测试通过，未使用真实 API Key |
| 助手购物车/状态机/确认存储 | 单元测试通过 |
| 真实认证请求 | 未验证 |
| 真实门店、商品、库存与购物车读取 | 未验证 |
| 真实购物车写入 | 未验证 |
| 朴朴手机 App 回读 | 未验证 |

不得把单元测试、MockTransport 或本地购物车状态说成真实加购完成。

## 验证命令

```bash
.venv/bin/pytest tests/test_config.py \
  tests/architecture/test_pupu_http_boundary.py \
  tests/integrations/pupu \
  tests/integrations/llm \
  tests/application \
  tests/domain \
  tests/storage \
  tests/validation \
  tests/entrypoints

.venv/bin/ruff check src tests
```

真实公开请求：

```bash
.venv/bin/python scripts/validate_pupu_public.py
```

## 下一步

1. 增加 DeepSeek 真实 API 最小验证脚本，使用用户本地 `LLM_API_KEY`，证据不记录 Key 或模型思维内容。
2. 实现本地凭证存储与手机号/验证码交互边界；验证码仅在当次进程使用。
3. 在受保护请求签名得到真实向量验证后，再实现门店、商品和购物车 Gateway。
4. 使用低风险单个商品执行 `preview → confirmation → execute → readback`。
5. 最终验收必须由用户在同账号朴朴手机 App 中确认商品和数量一致。

## 安全约束

- `PUPU_ALLOW_LIVE_MUTATION=false` 是默认值。
- 真实写入需要开关与精确交互确认同时成立。
- 写入超时不自动重试，先回读购物车判定。
- `.env`、凭证、APK、`.local/`、`.tools/` 和验证证据不提交。
- 飞书集成尚未开始；后续只允许新建，不修改任何现有配置。

## 本地未发布内容

当前工作树中的客户端产物调查草稿、分析工具与本地证据不属于本次发布范围，不应为了获得“干净工作树”而将其追加到提交中。

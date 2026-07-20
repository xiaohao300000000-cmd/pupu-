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
5. 公开服务器时间真实验证脚本与脱敏证据模型；最近一次运行失败，未取得 HTTP/API 响应。
6. DeepSeek V4 工具调用 Provider、工具白名单、参数校验和轮数上限。
7. 版本化、幂等的助手购物车。
8. 采购状态机，真实写入工具只在确认与复核通过后暴露。
9. 购物车两阶段控制：预览哈希、过期、精确短语、一次性消费、幂等键、超时后回读判定。
10. Windows 兼容性修复：`ConfirmationStore` 改为跨平台文件锁，避免 `fcntl` 导致测试收集失败。
11. APK 复核文档：两份 APK 元数据已核验，但 `seal/sign` 完整实现仍未得到。

## 真实验证边界

| 接口或能力 | 当前证据 |
|---|---|
| `GET https://j1.pupuapi.com/client/base/data` | 最近一次运行失败，未取得 HTTP/API 响应 |
| DeepSeek Tool Calls | MockTransport 单元测试通过，未使用真实 API Key |
| 助手购物车/状态机/确认存储 | 单元测试通过；Windows 文件锁已改为跨平台实现 |
| APK 元数据 | 6.4.9 与 6.4.1 已核验，同一证书、v1/v2/v3 |
| 受保护 `seal/sign` | 未得到完整实现，仍 fail-closed |
| 真实认证请求 | 未验证 |
| 真实门店、商品、库存与购物车读取 | 未验证 |
| 真实购物车写入 | 未验证 |
| 朴朴手机 App 回读 | 未验证 |

不得把单元测试、MockTransport、本地购物车状态或 APK 字符串命中说成真实加购完成或 `seal/sign` 已完成。

## 验证命令

```bash
py -3.12 -m pytest -q
```

本轮结果：`62 passed in 0.77s`。

真实公开请求：

```bash
py -3.12 scripts/validate_pupu_public.py
```

最近一次运行结果：`PupuNetworkError`，证据写入 `.local/evidence/public-server-time.json`，不能记为接口通过。

## 研究文档

- `docs/research/pupu-signature-audit-2026-07-21.md`
- `docs/research/apk-metadata-review-2026-07-21.md`
- `docs/research/evidence-table-2026-07-21.md`
- `docs/research/upstreams.json`

## 下一步

1. 继续 native / Hermes 层定位 `ppAppSecret`、`ppOs` 与最终 `seal/sign` 输出格式。
2. 拿到一个 GET 向量和一个 POST 向量后，先写固定向量测试，再实现签名模块。
3. 受保护请求签名得到真实向量验证后，再实现门店、商品和购物车 Gateway。
4. 使用低风险单个商品执行 `preview → confirmation → execute → readback`。
5. 最终验收必须由用户在同账号朴朴手机 App 中确认商品和数量一致。

## 安全约束

- `PUPU_ALLOW_LIVE_MUTATION=false` 是默认值。
- 真实写入需要开关与精确交互确认同时成立。
- 写入超时不自动重试，先回读购物车判定。
- `.env`、凭证、APK、`.local/`、`.tools/` 和验证证据不提交。
- APK / native / bundle 原始产物只放在本地 `C:\Users\10579\work\pupu-audit\artifacts`，不进入 Git。
- 飞书集成尚未开始；后续只允许新建，不修改任何现有配置。

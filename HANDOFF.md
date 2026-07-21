# Pupu Assistant Handoff

更新时间：2026-07-21

开发分支：`codex/assistant-cart-persistence`

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
12. `seal/sign` 静态跟进：确认 Hermes `encryptionToParams` 只是业务参数 MD5 摘要；`withSecSign` 会透传到 native request config；payload 中存在 `HEADER_SEAL/HEADER_SIGN`、`seal-v2/v3`、`sign-v2/v3`、`pp-seqid/pp-time` 等线索，但仍缺完整算法和固定向量。
13. SQLite 采购会话持久化：按 `task_id + user_id` 保存短期上下文、采购状态机、版本化助手购物车、商品明细和操作幂等 ID；保存使用单事务替换，避免旧商品残留。
14. 稳定 `PupuConnector` 商品边界与任务级工具绑定：读取当前门店、搜索、商品详情和助手购物车增删改替换均通过显式接口；Connector 返回商品会复核门店和 `store_product_id`，不允许模型制造商品事实。
15. 可恢复的 DeepSeek 需求理解阶段：平台无关采购需求、单问题澄清、澄清答案历史及原任务恢复；直接采购意图必须提交需求或澄清问题。
16. 最小采购计划编排：`获取门店 → 搜索并保存真实候选 → 候选中选品 → 助手购物车 → 等待确认`；缺门店、缺候选或空购物车均显式失败，不允许生成假结果。
17. 飞书事件接入边界：按官方 CLI 展平 schema 解析文本消息和卡片动作，事件 ID 持久化去重；文本消息可以创建任务或回答原任务的单问题澄清。
18. 飞书助手购物车动作：按 `task_id + operator_id + cart_version` 处理数量修改、删除、取消和确认；旧卡片拒绝写入，删除最后一项后保持空购物车而不进入待确认。
19. 外部黑盒 signer 适配：把受保护请求交给用户配置的 `PUPUSGN_BLACKBOX_CMD`，只接受含 `seal/sign` 头的结果；未配置或返回无效时保持网络前失败。

## 真实验证边界

| 接口或能力 | 当前证据 |
|---|---|
| `GET https://j1.pupuapi.com/client/base/data` | 最近一次运行失败，未取得 HTTP/API 响应 |
| DeepSeek Tool Calls | MockTransport 单元测试通过，未使用真实 API Key |
| 助手购物车/状态机/确认存储 | 单元测试通过；Windows 文件锁已改为跨平台实现 |
| SQLite 任务/购物车恢复 | 代码已实现；本轮遵照用户指令未运行新增测试，不能标记为已验证 |
| Connector 商品工具绑定 | 代码已实现；没有真实受保护 Connector，且本轮未测试，不能标记为真实商品查询通过 |
| 需求结构化与澄清恢复 | 代码已实现；本轮未测试，也未使用真实 DeepSeek API Key |
| “帮我买牛奶”计划链路 | 应用编排已实现；真实 Connector 缺失且本轮未测试，尚未跑通真实商品结果 |
| 飞书事件处理 | 代码边界已实现；未创建新应用、未配置凭证、未监听真实事件、未发送消息或卡片 |
| 飞书购物车卡片 | 业务视图与回调处理已实现；尚未生成或发送真实 Card JSON，本轮未测试 |
| APK 元数据 | 6.4.9 与 6.4.1 已核验，同一证书、v1/v2/v3 |
| 受保护 `seal/sign` | 已有外部命令适配与占位样例；未提供真实结果时仍 fail-closed，本轮未测试 |
| 真实认证请求 | 未验证 |
| 真实门店、商品、库存与购物车读取 | 未验证 |
| 真实购物车写入 | 未验证 |
| 朴朴手机 App 回读 | 未验证 |

不得把单元测试、MockTransport、本地购物车状态或 APK 字符串命中说成真实加购完成或 `seal/sign` 已完成。

## 验证命令

```bash
py -3.12 -m pytest -q
```

持久化改动前基线：`62 passed`。本轮用户明确要求继续开发但不运行测试，因此没有持久化改动后的测试结果。

真实公开请求：

```bash
py -3.12 scripts/validate_pupu_public.py
```

最近一次运行结果：`PupuNetworkError`，证据写入 `.local/evidence/public-server-time.json`，不能记为接口通过。

## 研究文档

- `docs/research/pupu-signature-audit-2026-07-21.md`
- `docs/research/apk-metadata-review-2026-07-21.md`
- `docs/research/evidence-table-2026-07-21.md`
- `docs/research/seal-sign-static-followup-2026-07-21.md`
- `docs/research/upstreams.json`

## 下一步

1. `seal/sign`、APK、Hook 和算法恢复由用户本人处理；本项目只接入用户提供的结果。
2. 非逆向开发继续完成采购会话仓库与应用编排的连接，使助手购物车每次变更后保存、进程重启后恢复。
3. 用户提供可调用 signer 命令和真实向量后，把命令写入本地 `PUPUSGN_BLACKBOX_CMD`，再实现门店、商品和购物车 Gateway。
4. 受保护 Connector 可用后，按文档跑通“帮我买牛奶”的真实最小闭环，再连接飞书新应用的真实消息发送与回调监听。
5. 最终验收必须由用户在同账号朴朴手机 App 中确认商品和数量一致。

## 安全约束

- `PUPU_ALLOW_LIVE_MUTATION=false` 是默认值。
- 真实写入需要开关与精确交互确认同时成立。
- 写入超时不自动重试，先回读购物车判定。
- `.env`、凭证、APK、`.local/`、`.tools/` 和验证证据不提交。
- APK / native / bundle 原始产物只放在本地 `C:\Users\10579\work\pupu-audit\artifacts`，不进入 Git。
- 飞书业务边界已开始实现；真实接入仍只允许新建应用，不修改、复用或接管任何现有配置。


## Black-box signer materials added on 2026-07-21

- Added `.local/bin/pupusgn` as an offline Mac/Linux CLI wrapper. It accepts stdin or `--input`, supports `--case` for fixture files, writes signed headers to stdout, and returns `network_performed=false`.
- Added `.local/pupusgn-test.json` with two placeholder-only cases: `protected_read_product_detail_popup` and `business_write_cart_purchasing_product`.
- Added `.local/pupu-cases.json` with redacted 6.4.9 product/cart request shapes and a placeholder allowed test merchant/product slot.
- Added `src/pupu_assistant/integrations/pupu/blackbox_signer.py` plus tests. No real device/account/header/signature values are committed.
- If the user supplies Hook/black-box output later, put it in an ignored private runtime JSON and run `.local/bin/pupusgn`; do not replace fail-closed protected signing in production until a signed vector has been verified.

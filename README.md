# 朴朴 DeepSeek 智能购物助手

这是一个正在开发的 Python 模块化单体项目：由 DeepSeek 理解用户的采购或菜品需求，通过受控工具查询朴朴真实商品，组建助手购物车，并在用户确认后安全同步到真实购物车。

> 当前状态：非 signer 的本地业务代码继续开发中，本轮新增内容均未测试。受保护请求仍只允许消费外部 `PUPUSGN_BLACKBOX_CMD`；没有真实 signer、账号上下文和新飞书应用时保持 fail-closed，不执行真实商品请求、消息发送或购物车写入。

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
- SQLite 采购会话仓库：按用户保存任务上下文、状态机、助手购物车、商品明细和操作幂等 ID，支持进程重启后恢复。
- 稳定的 `PupuConnector` 只读商品接口与按任务绑定的 Agent 工具：模型只能接收 Connector 返回并复核过门店归属的商品事实，不能自行构造价格、库存或平台商品 ID。
- 可恢复的需求理解流程：把自然语言保存为平台无关的结构化采购需求；信息不足时每轮只允许一个关键问题，用户回答后恢复同一任务继续理解。
- 最小采购编排：按状态机依次获取当前门店、为每条需求搜索并持久化真实候选、让 Agent 只从候选中选择、写入独立助手购物车并进入等待确认。
- 飞书应用层边界：解析 `lark-cli` 已展平的文本消息与卡片回调事件，按 `event_id` 去重，并把同一用户的追问回答恢复到原采购任务。
- 飞书助手购物车交互模型：把版本化购物车转换为卡片视图，处理改数量、删除、取消与确认动作；回调按用户和购物车版本隔离，旧卡片不会修改新方案。
- 飞书助手购物车 Card 2.0 JSON 渲染边界：生成商品、规格、价格、库存、数量、小计、总价及增减/删除/确认/取消按钮载荷，并把回调值绑定到任务与购物车版本。
- 飞书候选商品交互：从会话内已保存的同需求候选生成详情与替换按钮，只允许同门店、同需求且有库存的候选替换当前助手购物车商品；取消或过期卡片不能继续修改。
- SQLite 家庭记忆：按用户隔离保存、查看、修改和删除长期偏好与轻量库存，并生成不含用户 ID、内部记录 ID、地址或凭证的 Agent 上下文。
- 本地偏好/库存更新意图：只有显式对应意图才能写家庭记忆；澄清与写入互斥，其他采购意图不能夹带记忆变更。
- 菜品采购结构化契约：必须生成可执行原料需求或提出一个关键问题，并可在配置家庭记忆后参考已有库存。
- SQLite 商品事实缓存、价格历史、用户购物历史缓存和脱敏操作审计；购物历史可按精确确认短语清空，审计记录不随之删除。
- 等待确认阶段的自然语言改数量、删除和候选替换；所有替换只能来自当前任务已保存的同门店、同需求且有库存候选。
- 未同步助手购物车的撤销、任务取消、查看购物车，以及查看/删除偏好和查看家庭库存等用户控制。
- 结构化菜谱与库存扣减：仅对同名或关键词命中、单位一致且未过期的库存做确定性扣减；临期、过期或单位不明时保留提示而不猜测。
- 最多三个菜品建议的结构化结果，不虚构朴朴价格；用户选择后继续同一个澄清任务。
- 历史复购工作流：只消费 Connector 返回的当前门店真实订单、商品详情、价格、库存和替代品，不使用本地历史冒充平台订单。
- 完整的 `PupuConnector` 业务接口契约，以及显式注入真实 Connector 的本地运行时组装入口；仓库仍不包含可绕过 signer 的受保护接口实现。
- 选品原因持久化并展示在助手购物车卡片中，明确区分模型基于真实候选的选择、历史复购和用户主动替换。

> SQLite 持久化代码已实现，但按本轮用户指令未运行新增测试；上面的 `62 passed` 是持久化改动之前的基线，不代表本轮改动已经验证。
> `PupuConnector` 当前只有稳定接口与工具绑定，尚没有可用的真实受保护接口实现；不能据此声称商品查询已跑通。
> 需求理解流程已编码，但本轮按用户要求没有执行测试，也未使用真实 DeepSeek API Key 验证。
> 最小采购编排没有真实 Connector 时会明确停止，不会用 Mock 或模型输出补造商品。
> 飞书代码只定义新应用专用配置与事件处理；当前没有创建、修改或复用任何现有飞书应用，也没有发送消息或卡片。
> 卡片代码现在可以生成 Card 2.0 JSON，但只作为新飞书应用发送层的返回值；真实发送、回调监听和飞书客户端渲染仍未连接，本轮也未测试。
> 商品缓存、价格历史、操作审计、购物历史、自然语言改车、撤销、菜谱库存扣减、菜品建议、历史复购、运行时组装和选品原因均为代码实现；本轮未运行测试，也未通过真实 DeepSeek、真实 Connector 或飞书新应用验证。

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
PUPU_DATABASE_PATH=.local/pupu-assistant.db
PUPUSGN_BLACKBOX_CMD=
FEISHU_APP_INSTANCE_NAME=
FEISHU_APP_ID=
FEISHU_APP_SECRET=
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
| 任务/购物车 SQLite 恢复 | 已实现，本轮未测试 | 重启恢复、原子替换及 `task_id + user_id` 隔离仍待验证 |
| 两阶段购物车控制 | 单元测试已通过 | 尚未接入朴朴真实购物车 Gateway |
| 飞书助手购物车卡片 | Card 2.0 JSON 生成已实现，本轮未测试 | 尚未在新应用中发送或验证客户端渲染 |
| 候选详情与替换 | 已实现，本轮未测试 | 只消费已保存候选；尚未在飞书客户端验证 |
| 家庭偏好与轻量库存 | SQLite CRUD 与脱敏 Agent 上下文已实现，本轮未测试 | 尚未用真实 DeepSeek/飞书消息验证更新意图 |
| 菜品采购结构化 | 原料需求/单问题契约已实现，本轮未测试 | 真实商品匹配仍依赖受保护 Connector |
| 商品事实与价格历史 | SQLite 持久化已实现，本轮未测试 | 需要真实 Connector 返回事实后验证缓存更新与价格变化记录 |
| 操作审计与购物历史控制 | 脱敏审计、用户历史缓存及精确确认清空已实现，本轮未测试 | 尚未接入真实账号订单数据 |
| 自然语言改车、撤销和取消 | 等待确认阶段的本地控制已实现，本轮未测试 | 尚未用真实 DeepSeek/飞书事件验证 |
| 菜谱库存扣减与菜品建议 | 确定性规则及最多三项建议已实现，本轮未测试 | 不含真实朴朴价格，商品匹配仍依赖受保护 Connector |
| 历史复购 | 真实订单 Connector 工作流已实现，本轮未测试 | 真实订单列表、详情、当前价格库存与替代品均待受保护 Connector |
| 本地运行时组装 | 显式 Connector 注入边界已实现，本轮未测试 | 没有内置 Mock 或可绕过 signer 的默认实现 |
| 手机号登录 | 未验证 | 需要用户本人输入当次验证码 |
| 受保护 `seal/sign` | 未验证 | 仅允许用户提供真实 signer/请求向量；本项目不研究或实现算法 |
| 真实商品查询 | 未验证 | 需要当前门店与账号上下文 |
| 真实购物车加购 | 未验证 | 写入成功 + API 回读 + 手机 App 确认 |

Mock 只用于单元测试，不会被记为真实朴朴验收结果。

## 文档

- [总体设计](docs/superpowers/specs/2026-07-21-pupu-assistant-design.md)
- [签名与购物车实施计划](docs/superpowers/plans/2026-07-21-pupu-signature-and-cart-control.md)
- [助手购物车持久化与恢复计划](docs/superpowers/plans/2026-07-21-assistant-cart-persistence-and-recovery.md)
- [GitHub 上游审计](docs/research/pupu-signature-audit-2026-07-21.md)
- [APK 元数据复核](docs/research/apk-metadata-review-2026-07-21.md)
- [`seal/sign` 静态跟进](docs/research/seal-sign-static-followup-2026-07-21.md)
- [复核证据表](docs/research/evidence-table-2026-07-21.md)
- [当前交接说明](HANDOFF.md)

## 许可与来源

项目会优先复用可用的 GitHub 模块，但任何复制代码都必须保留来源和许可证。`cddjr/check` 当前仅作协议研究上游；已发现其 MIT License 与 README 中的限制表述存在口径冲突，商业使用前需另行确认。


## Black-box signer fixture path

- `.local/bin/pupusgn` is a committed offline Mac/Linux signer wrapper. It reads JSON, merges supplied black-box `seal/sign` headers, writes JSON to stdout, and performs no HTTP requests.
- `.local/pupusgn-test.json` contains two redacted runnable cases: one protected product read and one cart write fixture.
- `.local/pupu-cases.json` records current 6.4.9 product/cart candidate routes with placeholder-only method/path/query/body shapes.
- `ExternalBlackboxSignatureService` can call the account owner's `PUPUSGN_BLACKBOX_CMD` and merge its signed headers into the existing fail-closed HTTP chain; it does not generate signatures itself.
- Details: [Black-box Pupu signer materials](docs/research/blackbox-signer-materials-2026-07-21.md)

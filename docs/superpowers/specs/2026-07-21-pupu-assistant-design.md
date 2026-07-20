# 家庭采购助理总体设计

日期：2026-07-21
状态：已确认，待实施计划
目标仓库：`xiaohao300000000-cmd/pupu-`

## 1. 产品定义

家庭采购助理是一个由 DeepSeek 驱动、以朴朴超市为真实商品与执行底座的采购 Agent。

DeepSeek 是采购决策核心。它负责理解用户需求、判断是否需要澄清、生成菜品原料、调用朴朴商品工具、比较真实候选、选择商品和数量、维护助手购物车并根据用户反馈调整采购方案。

朴朴 Connector 提供真实商品、订单、价格、库存、购物车和活动能力。飞书、状态机、数据库、菜谱和定时任务都服务于这条核心采购链路。

MVP 不自动提交订单、不自动支付。用户明确确认前，不得修改朴朴真实购物车。

## 2. 已确认约束

- 单一 Python 服务，不保留独立 Node 或 MCP 侧车进程。
- 优先 Fork 和复用 GitHub 上已有模块；允许为了融合进行必要调整。
- 朴朴能力优先基于 `cddjr/check`。
- 保留签到、抽奖、集卡和优惠券活动。
- 活动同时支持用户指令和定时执行。
- 默认自动允许签到、查询和领取类低风险操作。
- 抽奖、兑换、卡片合成等消耗性操作默认需要用户授权。
- 手机号登录暂缓，第一阶段允许导入现有 `device_id` 和 `refresh_token`。
- DeepSeek 通过可替换的 `LLMProvider` 接入。
- 飞书只创建新应用、新机器人、新事件订阅、新菜单和新卡片配置，绝不修改任何现有设置。
- 代码同步到公开仓库 `xiaohao300000000-cmd/pupu-`。
- Token、API Key、App Secret、手机号和地址不得提交 GitHub。
- Mock 可以用于单元测试，但不能作为真实朴朴接口验收结果。

## 3. 技术方案选择

采用 Python 模块化单体。

不直接扩建青龙脚本，也不在 MVP 中引入多进程 MCP 服务。项目保留类似 MCP 的稳定工具契约，以便未来拆分服务时不修改 Agent。

```text
飞书消息 / 卡片回调 ─┐
定时任务 ───────────┼→ Application Orchestrator
本地 CLI / Validator ┘          │
                               ├→ DeepSeek Purchase Agent
                               ├→ Purchase State Machine
                               ├→ Tool Registry
                               └→ Policy Engine
                                      │
                         ┌────────────┼────────────┐
                         ↓            ↓            ↓
                   Pupu Connector  Recipe Service  Assistant Cart
                         │
            Auth / Store / Product / Order / Cart / Activities
```

## 4. 目录边界

```text
src/pupu_assistant/
├── entrypoints/
│   ├── feishu/
│   ├── api/
│   └── cli/
├── application/
│   ├── orchestrator.py
│   ├── state_machine.py
│   ├── tool_registry.py
│   ├── commands.py
│   └── policies.py
├── domain/
│   ├── purchase/
│   ├── assistant_cart/
│   ├── recipes/
│   ├── activities/
│   └── preferences/
├── integrations/
│   ├── pupu/
│   │   ├── auth.py
│   │   ├── client.py
│   │   ├── signature.py
│   │   ├── stores.py
│   │   ├── products.py
│   │   ├── orders.py
│   │   ├── cart.py
│   │   └── activities/
│   ├── llm/
│   │   ├── provider.py
│   │   └── deepseek.py
│   └── recipes/
│       └── scraper.py
├── scheduler/
├── storage/
└── config.py
```

各模块通过显式接口通信。业务模块不得直接创建 HTTP 请求，不得读取朴朴 Token，也不得直接访问 Connector 内部会话对象。

## 5. GitHub 模块复用边界

### 5.1 `cddjr/check`

作为朴朴协议和活动能力的主要源码底座。

保留并整理：

- 服务器时间。
- Access Token 刷新与 Refresh Token 轮换。
- `pp-userid`、`pp-suid`、门店和地址请求头。
- 用户信息、地址、`place_id` 和服务门店。
- 收藏商品、价格、库存和限购字段。
- 签到、抽奖、集卡和优惠券相关接口。
- 现有朴朴数据结构与错误码研究成果。

移除或重构：

- 青龙配置和运行框架。
- 导入时自动执行 `pip3 install`。
- PushDeer 和青龙通知。
- `ssl=False`。
- 明文 Token 配置。
- 直接创建订单的自动抢购链路。
- 宽泛异常吞噬。

保留上游提交信息、MIT License 和第三方来源记录。README 中的商业限制与 MIT License 存在口径冲突，需要在商用前单独处理。

### 5.2 `rohlik-mcp`

复用工具接口设计和 API Validator 思路：

- `search_products`
- `get_product_detail`
- `get_order_history`
- `get_order_detail`
- `get_cart`
- `check_products`
- `get_frequent_items`

工具实现全部改为调用 Pupu Connector。

### 5.3 `tesco-grocery-mcp`

Fork `skills/SKILL.md` 的阶段编排思想：

1. 收集收藏、购物车和用户偏好。
2. 批量搜索所有未解决需求。
3. 比较并选择候选。
4. 写入助手购物车。
5. 用户确认后同步。
6. 回读购物车并处理替代品。

### 5.4 Texas Grocery MCP

复用两阶段安全写入模式：

```text
preview → confirmation_id → execute → verify
```

将其抽象为通用安全写入服务，供真实购物车、抽奖、兑换和卡片合成使用。

### 5.5 Recipe2Grocery

仅复用对话体验和菜谱转购物清单的产品思路。该仓库当前没有明确许可证，未获得授权前不得直接复制代码。

### 5.6 recipe-scrapers

作为正式 Python 依赖直接使用，负责从菜谱网页提取菜名、原料、步骤和份量信息。

KitchenOwl 和 Grocy 不进入 MVP。

## 6. DeepSeek Purchase Agent

DeepSeek 不是纯分类器或文案生成器，而是采购方案决策核心。

它可以：

- 识别用户采购、复购、菜品、推荐、修改和活动意图。
- 提取人数、预算、规格、品牌、库存和饮食约束。
- 每次只提出一个最关键的澄清问题。
- 根据菜品生成结构化原料和份量。
- 主动调用朴朴搜索、商品详情、订单和库存工具。
- 阅读真实候选商品。
- 比较品牌、规格、价格、库存、历史偏好和包装浪费。
- 选择商品与数量。
- 调用助手购物车工具添加、删除、替换和调整商品。
- 根据预算或用户反馈重新规划。
- 用户确认后发起真实购物车同步请求。

它不能：

- 虚构商品、价格、库存或平台 ID。
- 拼接朴朴 URL 或生成鉴权信息。
- 读取 Token。
- 直接写数据库。
- 绕过状态机修改朴朴真实购物车。
- 将本地成功状态当作朴朴同步成功。

### 6.1 工具集合

只读朴朴工具：

```text
search_products
get_product_detail
get_favorite_products
get_orders
get_order_detail
get_current_store
get_current_cart
check_price_and_stock
find_platform_substitutes
```

助手购物车工具：

```text
assistant_cart.get
assistant_cart.add
assistant_cart.set_quantity
assistant_cart.remove
assistant_cart.replace
assistant_cart.rebuild_with_budget
```

菜谱工具：

```text
recommend_dishes
extract_recipe_url
generate_ingredient_list
adjust_ingredients
map_ingredients_to_requirements
```

写入准备工具：

```text
prepare_cart_sync
prepare_activity_operation
```

真实写入工具只有在状态机授权后才会暴露。

### 6.2 LLMProvider

```python
class LLMProvider:
    async def run_agent(
        self,
        messages,
        tools,
        allowed_tools,
    ) -> AgentResult:
        raise NotImplementedError
```

环境变量：

```text
LLM_PROVIDER=deepseek
LLM_BASE_URL=https://api.deepseek.com
LLM_API_KEY=
LLM_MODEL=deepseek-v4-flash
LLM_TIMEOUT_SECONDS=
LLM_MAX_TOOL_ROUNDS=
```

模型名和 Base URL 不得写死。工具参数必须经过 Pydantic/JSON Schema 校验。必须限制最大工具调用轮数并处理空响应、超时、限流和非法工具选择。

## 7. 采购主流程

```text
用户表达需求
→ DeepSeek 提取需求并按需澄清
→ DeepSeek 调用真实朴朴搜索
→ Connector 返回真实候选
→ DeepSeek 比较并选择商品
→ DeepSeek 加入助手购物车
→ 飞书展示商品、数量、价格和理由
→ 用户修改或确认
→ DeepSeek 调整方案
→ 用户最终确认
→ 状态机重新检查价格和库存
→ Pupu Cart Service 写入真实购物车
→ 重新读取朴朴购物车
→ 验证商品、数量和价格
→ 飞书返回成功、部分失败或失败结果
```

菜品场景使用同一流程，只是在商品搜索前增加菜品原料生成与库存扣减。

## 8. 状态机

采购状态：

```text
RECEIVED
UNDERSTANDING
AWAITING_CLARIFICATION
GATHERING_CONTEXT
SEARCHING
BUILDING_CART
AWAITING_CONFIRMATION
REVALIDATING
AWAITING_RECONFIRMATION
SYNCING
VERIFYING
COMPLETED
PARTIAL_FAILED
FAILED
CANCELLED
AUTH_REQUIRED
```

状态机决定每个阶段允许暴露给 DeepSeek 的工具。DeepSeek 负责选择商品和维护助手购物车，状态机负责顺序、恢复、去重、权限和真实写入安全。

## 9. 写入安全

每次真实购物车写入保存：

```text
confirmation_id
user_id
cart_id
cart_version
planned_operations
price_snapshot
expires_at
idempotency_key
used_at
```

规则：

1. 用户确认助手购物车的特定版本。
2. 购物车修改后旧确认立即失效。
3. 同步前重新查询价格和库存。
4. 重要变化需要重新确认。
5. 同一个幂等键不得重复执行。
6. 写入后必须回读真实购物车。
7. 只有回读一致才能标记成功。
8. 部分失败按商品记录，不得整体冒充成功。

## 10. 活动编排

签到、抽奖、集卡和优惠券统一使用 `ActivityCommand`。

入口：

- 飞书用户指令。
- 每日定时任务。
- 本地 CLI。

状态：

```text
SCHEDULED / USER_REQUESTED
→ POLICY_CHECK
→ AWAITING_CONFIRMATION
→ EXECUTING
→ VERIFYING
→ SUCCEEDED / PARTIAL_FAILED / FAILED
```

默认策略：

- 自动允许：签到、查询活动、领取已获得奖励、查询优惠券。
- 默认确认：抽奖、消耗朴分、兑换、卡片合成。
- 永久禁止自动执行：创建订单、支付、修改账号安全信息。

使用 `user_id + activity_type + activity_date + target_id` 防止重复执行。

## 11. PupuSignatureService

### 11.1 强制调用链

所有朴朴 HTTP 请求必须经过：

```text
业务模块 → PupuSignatureService → PupuHttpClient → Pupu API
```

业务模块不得直接访问 `aiohttp`、`httpx` 或原始请求会话。

### 11.2 统一接口

```python
class PupuSignatureService:
    def sign(self, request: PupuRequestContext) -> SignedPupuRequest:
        raise NotImplementedError
```

`PupuRequestContext` 至少包含：

```text
method
url/path
query
body bytes
timestamp
device_id
user_id
su_id
store_id
place_id
city_zip
app_version
os_type
existing_headers
```

`SignedPupuRequest` 返回：

```text
normalized_url
normalized_body
headers
signature_metadata
```

签名服务负责普通公共请求头和受保护请求的 `seal/sign`。如果某类接口不需要签名，也必须显式返回 `signature_mode=none`，不能绕过该服务。

### 11.3 专项研究任务

首个实现子项目必须：

1. 检查 `cddjr/check` 及其他朴朴 GitHub 仓库。
2. 搜索 `seal`、`sign`、时间戳、魔改 MD5、魔改 Base64 和 XXTEA。
3. 找出生成位置、输入参数、请求头和调用链。
4. 区分完整实现、部分实现和纯文字说明。
5. 如已有完整实现，按许可证要求抽取。
6. 如没有完整实现，保留统一接口并准确记录缺失算法、常量、字段顺序和验证样本。
7. 提供最小真实请求验证脚本。
8. 分接口记录真实请求验证结果。

不得用 Mock 作为该专项的完成标准。没有朴朴凭证或缺少算法时，应报告为未通过真实验证，不得宣称完成。

## 12. 数据模型

最少需要：

- `users`
- `pupu_credentials`
- `purchase_tasks`
- `conversation_messages`
- `requirements`
- `product_candidates`
- `assistant_carts`
- `assistant_cart_items`
- `confirmations`
- `cart_sync_operations`
- `preferences`
- `activity_runs`
- `tool_calls`
- `event_deduplication`
- `api_validation_runs`

菜品、原料和推荐理由可以由 DeepSeek 生成。商品名称、平台 ID、价格、库存、订单和购物车结果必须来自真实朴朴响应，并保存来源与采集时间。

MVP 使用 SQLite 和 SQLAlchemy，凭证字段加密保存。后续允许迁移 PostgreSQL。

## 13. 飞书隔离

- 创建全新的飞书应用和应用机器人。
- 创建新的事件订阅、卡片模板、机器人菜单和回调地址。
- 不修改、不覆盖、不复用任何已有飞书应用设置。
- 即使发现同名应用，也创建带唯一后缀的新应用。
- 使用独立 `APP_ID`、`APP_SECRET` 和回调路径。
- 所有创建结果记录到本项目配置。
- 回调在三秒内确认接收，耗时工作异步执行。
- 使用飞书 `event_id` 和卡片操作 ID 去重。

## 14. 错误与恢复

- DeepSeek 失败：保留任务状态，重试或请求用户稍后继续。
- Token 失效：进入 `AUTH_REQUIRED`，停止外部写入。
- 商品搜索失败：不得虚构候选。
- 价格库存变化：重新确认。
- 部分同步失败：逐项展示成功和失败。
- 飞书重复回调：幂等忽略。
- 定时任务重复触发：执行键去重。
- 服务重启：恢复所有非终态任务。
- 接口字段变化：记录脱敏结构摘要并产生兼容性告警。
- 签名失败：记录签名模式、请求路径和非敏感诊断信息，不记录 Token、完整地址或签名密钥。

## 15. 测试与验收

### 15.1 自动化测试

- 领域模型和状态机单元测试。
- DeepSeek 工具参数与结果契约测试。
- 助手购物车增删改、去重和版本测试。
- 确认凭证、过期和幂等测试。
- 活动风险策略测试。
- HTTP 错误分类和重试测试。
- 签名固定向量测试。
- 脱敏响应录制的契约回归测试。

### 15.2 真实 API Validator

必须逐项验证：

1. 服务器时间。
2. Token 刷新。
3. 用户信息。
4. 地址和门店。
5. 收藏商品。
6. 签到、抽奖、集卡和优惠券。
7. 商品搜索。
8. 商品详情、价格和库存。
9. 订单列表和订单详情。
10. 真实购物车读取。
11. 真实购物车添加、修改和删除。
12. 手机同账号朴朴 App 回读。

每项记录：

```text
endpoint
signature_mode
tested_at
account_scope
request_result
response_schema_version
verified_in_mobile_app
failure_reason
```

### 15.3 端到端用例

- 帮我买两瓶牛奶。
- 买牛奶、鸡蛋和面包。
- 两个人吃咖喱鸡，家里有米。
- 把牛奶换成便宜一点的。
- 昨天买的再来一次。
- 查看今日签到和可领取奖励。
- 定时签到不会重复执行。
- 消耗朴分的抽奖必须确认。

## 16. 当前风险

1. `seal/sign` 完整算法尚未确认。
2. 商品搜索、订单详情和购物车端点尚未从当前客户端验证。
3. 真实购物车接口是增量数量还是绝对数量尚未确认。
4. 手机号登录延后，但最终产品化必须解决。
5. DeepSeek 工具调用需要防止空响应、错误参数和无效循环。
6. 菜品份量需要规则校验，避免明显过量。
7. `cddjr/check` 活动接口可能已经变化。
8. Recipe2Grocery 无明确许可证。
9. `cddjr/check` 的 MIT License 与 README 商业限制口径不一致。
10. 朴朴 API 当前存在间歇性 TLS 握手重置，需要兼容连接策略和健康监控。

这些风险不改变总体架构，但决定实施顺序。

## 17. 实施顺序

1. `seal/sign` GitHub 研究与 `PupuSignatureService`。
2. Pupu HTTP Client 与 Connector Validator。
3. 认证、地址、门店和收藏商品。
4. 活动能力迁移与真实验证。
5. 商品搜索、详情、订单和购物车。
6. 助手购物车与安全写入。
7. DeepSeek Purchase Agent。
8. 菜品与 recipe-scrapers。
9. 新建飞书应用并接入消息与卡片。
10. 完整端到端验收。

## 18. 完成定义

项目只有在以下结果成立时才算完成 MVP：

```text
用户在飞书说“帮我买两瓶牛奶”
→ DeepSeek 查询真实朴朴商品
→ DeepSeek 选择并加入助手购物车
→ 用户确认
→ 系统写入朴朴真实购物车
→ 手机同账号朴朴 App 中真实出现两瓶牛奶
```

本地状态、Mock 响应或未回读的 API 成功码均不能替代该验收。

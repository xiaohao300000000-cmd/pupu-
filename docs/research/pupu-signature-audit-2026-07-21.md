# 朴朴 `seal/sign` GitHub 实现审计

审计时间：2026-07-21（Asia/Shanghai）

## 可用性结论

截至本次审计，公开 GitHub 仓库中没有找到可直接复用、可由真实请求证明适用于当前朴朴客户端的完整 `seal/sign` 实现。

`cddjr/check` 是目前信息最完整的朴朴仓库，但其代码没有生成 `seal` 或请求签名 `sign`。仓库 issue #3 的作者回复明确表示没有继续深入分析，只给出了部分算法线索。因此不能把它判断为“已实现最新签名”，也不能把这段文字直接编码后当作可用实现。

两个公开 Fork 都落后于上游且没有独立提交，因此也没有补齐签名。其余仓库只实现刷新 Token、签到或活动查询，没有真实购物车读写。

## `cddjr/check` 代码位置与调用链

审计提交：[`a7da0d90`](https://github.com/cddjr/check/tree/a7da0d90a55a0b345b70dde1549591a69e2cd417)

- [`pupu_api.py`](https://github.com/cddjr/check/blob/a7da0d90a55a0b345b70dde1549591a69e2cd417/pupu_api.py) 是请求入口和业务 API 集合。
- `pupu_api.py:103-117` 设置或删除 `pp-suid`、`pp-userid`。
- `pupu_api.py:272-309` 刷新 Access Token，并处理 Refresh Token 轮换。
- `pupu_api.py:428-456` 调用签到接口。这里的 `SignIn` 是业务“签到”，不是请求签名生成。
- `pupu_api.py:1069` 开始的 `CreateOrder` 是直接创建订单能力，不是购物车能力。
- [`pupu_types.py`](https://github.com/cddjr/check/blob/a7da0d90a55a0b345b70dde1549591a69e2cd417/pupu_types.py) 定义部分请求与响应结构。
- `ck_pupu_sign.py`、`ck_pupu_lottery.py`、`ck_pupu_collectcards.py` 和 `ck_pupu_coupon.py` 是活动脚本入口。

当前调用链是“业务方法直接构造 URL/头 → 内部会话发 HTTP → 朴朴 API”，不存在独立签名层，也不满足本项目要求的调用链。

## issue #3 已知线索

来源：[`cddjr/check#3`](https://github.com/cddjr/check/issues/3)

作者只描述了以下信息：

- 请求头新增 `seal` 和 `sign`。
- `sign` 据称由部分请求头、时间戳、账号信息和静态键 `dac032e8fbb9900d840b960429b1a184` 混合后进行一种修改版 MD5。
- `seal.a` 据称包含修改版 MD5（输入提到 `sign` 与分隔串 `&*()*&`）和八字节随机值。
- `seal.b`、`seal.c`、`seal.d` 据称也是八字节随机值。
- `seal.f` 据称使用 XXTEA 加密时间戳、账号信息等内容，再以修改版 Base64 输出。

这不是完整实现。仍然缺失：

- 参与 `sign` 的准确请求头名称、大小写、排序和拼接格式；
- 时间戳单位与服务器时间偏移处理；
- 账号和设备字段的准确集合与空值规则；
- 修改版 MD5 的初始状态、轮常量或输出变换；
- 修改版 Base64 的字母表、填充和字节序；
- XXTEA key、明文序列化、端序和轮数；
- `seal` 整体序列化格式以及 `a` 至 `f` 的完整含义；
- 随机字段是否参与其他字段计算；
- 哪些当前端点必须携带 `seal/sign`；
- 当前客户端版本是否仍使用相同算法。

## 其他仓库

| 仓库 | 审计提交 | 许可证 | 签名实现 | 购物车 |
|---|---|---|---|---|
| `YDEKQ/check` | `8bfb8cd1` | MIT Fork | 无，落后上游 5 个提交 | 无 |
| `jo-dean/check` | `66d4d27c` | MIT Fork | 无，落后上游 25 个提交 | 无 |
| `CHERWING/CHERWIN_SCRIPTS` | `06468e0e` | 未检测到 | 无；`sign` 指签到 | 无 |
| `fghwett/pupu` | `1731c117` | MIT | 无；`signTask` 指签到 | 无 |
| `Churroser/PupuTool` | `e028c793` | 未检测到 | 无；`Sign` 指签到 | 无 |

机器可读明细见 [`upstreams.json`](./upstreams.json)。

## 全局代码搜索

使用 GitHub Code Search 检索以下特征：

```text
dac032e8fbb9900d840b960429b1a184
&*()*&
seal + pupuapi
sign + pupuapi
xxtea + pupuapi
```

静态键和分隔串没有公开代码命中。`seal/sign + pupuapi` 结果主要是签到脚本、域名规则或无关项目，没有出现可验证的生成器。

## 本项目处理方式

第一阶段将提供独立 `PupuSignatureService`：

```text
业务模块 → PupuSignatureService → PupuHttpClient → Pupu API
```

- 明确不需要保护的公共端点返回 `signature_mode=none`，但仍经过签名服务。
- 受保护端点在算法未验证时返回 `ProtectedSignatureUnavailable`，并在网络请求前失败。
- 只有从当前官方客户端静态分析或用户本人账号的脱敏真实流量得到完整固定向量后，才实现 `seal/sign`。
- 固定向量通过后还必须用受保护的真实只读请求校验；Mock 不作为签名可用结论。

## 当前真实请求状态

本文件只记录 GitHub 源码审计。此阶段没有使用用户凭证，也没有把任何受保护接口标记为真实验证通过。

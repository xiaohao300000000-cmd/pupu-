# 朴朴 `seal/sign` 静态跟进（2026-07-21）

## 结论

`seal/sign` 现在仍然不能直接用。最新静态跟进只确认了两类线索：

1. Hermes bundle 里有一个业务参数 MD5 摘要函数 `encryptionToParams`，可解释部分接口参数上的 `sign` 字段。
2. APK 壳后 payload 里确实存在请求级 `seal/sign` header 常量、`seal-v2/v3`、`sign-v2/v3`、`pp-seqid`、`pp-time` 等字符串。

但还没有恢复请求级 `seal/sign` 的完整算法、序列化规则、随机字段结构或 GET/POST 固定向量。因此项目代码继续保持受保护接口 fail-closed，不把任何受保护请求降级成无签名请求。

## Hermes 业务参数签名线索

### `encryptionToParams`

位置：`artifacts/hbc649.index.decomp.js:980979-981040`

静态逻辑：

```text
encryptionToParams(params, timestamp):
  currentAppEnv = default.currentAppEnv
  pp_os = currentAppEnv.ppOs
  unique_id = DeviceInfo.getDeviceId()
  secret = currentAppEnv.ppAppSecret
  _params = {
    pp_os,
    unique_id,
    secret,
    timestamp,
    ...params 按 key 升序写入
  }
  str = queryString.stringify(_params, {encode:false, sort:false})
  return md5(str)
```

关键证据：

| 行号 | 证据 |
|---|---|
| `980986-980992` | 读取 `currentAppEnv.ppOs`、`DeviceInfo.getDeviceId()`、`currentAppEnv.ppAppSecret` |
| `980994-980998` | 写入 `pp_os`、`unique_id`、`secret`、`timestamp` |
| `981002-981014` | `Object.keys(params).sort()` 后把业务参数写入 `_params` |
| `981027-981029` | `stringify(..., {encode:false, sort:false})` |
| `981034-981037` | 对字符串做 `md5` |

### `getProductDetailSign` 调用点

位置：`artifacts/hbc649.index.decomp.js:343161-343218`

行为：

- 如果有 `store_product_id`，使用 `{store_product_id}`。
- 否则使用 `{product_id, store_id}`。
- 调用 `encryptionToParams(params, timestamp)` 返回 `sign`。

这个函数只能说明部分业务接口有参数级摘要；它不是全局请求级 `seal/sign`。

## `withSecSign` 请求级开关

Hermes bundle 里有多个接口显式传入 `withSecSign: true`，例如：

| 位置 | 请求 |
|---|---|
| `hbc649.index.decomp.js:200099-200107` | `GET /client/marketing/channel/global_redeem/list` |
| `hbc649.index.decomp.js:344326-344336` | `GET /client/product/storeproduct/unit_price/detail/{id}` |
| `hbc649.index.decomp.js:491844-491869` | `POST`，带 body/header、`enableSliderValidation: true`、`withSecSign: true` |
| `hbc649.index.decomp.js:633038-633050` | `POST /client/game/task_system/user_tasks/task/{id}/ticket` |
| `hbc649.index.decomp.js:1312249-1312262` | `POST /client/coupon/gift_coupon` |
| `hbc649.index.decomp.js:1968333-1968346` | `GET /client/product/storeproduct/detail_popup/{...}` |
| `hbc649.index.decomp.js:2121160-2121165` | `GET /client/assets/discount/list` |

请求包装层会把 `withSecSign` 原样放入 native request config：

| 位置 | 证据 |
|---|---|
| `1796791-1796793` | 调用 `pupu.request` |
| `1796831-1796836` | 从 options 读取 `withSecSign` |
| `1796873-1796888` | 构造 request config：`method/baseURL/path/params/body/headers/retryCount/timeout/withSecSign/...` |
| `1796889-1796890` | 把 config 交给后续 request/native bridge |

这说明 `withSecSign` 是请求级安全签名开关，但 Hermes 层没有直接给出 `seal/sign` 算法。

## payload / native 证据

### 壳与 payload 状态

`extract649/classes.dex` 的 DEX header 显示：

```text
file_size = 53608828
string_ids_size = 476
class_defs_size = 48
```

这个 DEX 本体只像 SecNeo wrapper + 大尾部 payload。`jadx` 只反编译出 39 个 Java 文件，主要是：

- `com/secneo/apkwrapper/*`
- `com/alibaba/android/arouter/routes/*`

`embedded_payload_from_classes_zip.bin` 头部是 `PK\x03\x04`，但 `zipfile.is_zipfile(...) == false`，且没有可直接解包的标准 ZIP 结构；当前判断是 SecNeo 自定义/加密容器或壳内资源流。

### 请求级 header 字符串

`artifacts/classes_payload_strings.txt` 中出现请求级 header 常量和实际 header 名：

| 位置 | 字符串 |
|---|---|
| `221985-221991` | `HEADER_SEAL`、`HEADER_SEAL_V2`、`HEADER_SEAL_V3`、`HEADER_SIGN`、`HEADER_SIGNABLE`、`HEADER_SIGN_V2`、`HEADER_SIGN_V3` |
| `245530-245543` | `pp-deviceid`、`pp-os`、`pp-seqid`、`pp-time`、`ppAppSecret` |
| `247696-247698` | `seal`、`seal-v2`、`seal-v3` |
| `249380-249381` | `sign-v2`、`sign-v3` |
| `287683-287684` | `force_ctrl_seal_v1v2`、`force_ctrl_seal_v3` |
| `298520` | `trackSealInfo` |

`sign` 附近还存在异常字符串：

```text
sign Exception:
sign InvalidKeyException:
sign NoSuchAlgorithmException:
sign SignatureException:
sign content or key is null
signature is invalid:
```

这些字符串证明壳后 payload 里存在请求签名相关实现或校验路径，但字符串本身不足以还原算法。

### native 线索

`artifacts/native-string-interesting-649.txt` 中的关键点：

- `libdexjni.so`：`Signature`、`$seal`、`seal`
- `libentryexpro.so`：`{"v":"%s","cmd":"init","reqtm":"%s","params":{"secret":"%s",%s}}`
- `libppcurl.so`：大量 `signature`/`base64`/`md5`，主要来自 TLS/OpenSSL/nghttp2 通用字符串

对 `libentryexpro.so` 的字符串引用检查显示该 JSON 由 `UPChannelExpress` 相关函数引用，更像银联/支付 SDK 初始化，不是朴朴 API 的请求级 `seal/sign`。

对 `libdexjni.so` 的 `$seal` / `seal` / `Signature` 做了 Python + Capstone/pyelftools 的静态引用检查：

```text
Signature file_off=0x109887 va=0x119887
$seal     file_off=0x1102d1 va=0x1202d1
seal      file_off=0x1176f8 va=0x1276f8
obvious static adrp/add xrefs: none
```

也就是说这些字符串不像普通 NUL 字符串那样被直接引用，可能处在壳数据、压缩字符串池或运行时解密结构里。

## 不能直接实现的缺口

还缺以下材料，不能把当前线索写成可用签名器：

- 请求级 `sign` 的准确输入字段、大小写、排序和拼接格式。
- `seal-v2/v3` 的整体结构、随机数位置、字段含义和序列化格式。
- `pp-seqid`、`pp-time`、设备 ID、用户 ID、token 等字段是否参与计算及空值规则。
- 修改版 MD5/Base64/XXTEA 之类算法线索的真实实现细节。
- GET 与 POST 的固定输入/输出向量。
- 当前服务端是否仍接受旧 issue 中描述的 `seal` 版本。

## 项目处理决定

- 不新增假 `seal/sign` 实现。
- 不把 `encryptionToParams` 当作全局请求签名器。
- `PupuSignatureService` 对受保护路径继续抛出 `ProtectedSignatureUnavailable`。
- 后续只有拿到当前 APK 的完整静态实现或用户本人账号的脱敏真实向量后，才进入 TDD 实现阶段。

## 下一步

1. 运行时 dump 壳后 DEX/classes，优先找包含 `HEADER_SEAL`、`HEADER_SIGN`、`force_ctrl_seal_v3`、`trackSealInfo` 的类。
2. Hook native/request bridge，观察 `withSecSign: true` 到 header 写入之间的真实参数。
3. 采集一个只读 GET 和一个无写入 POST 的脱敏固定向量。
4. 先写固定向量测试，再实现签名模块。

# APK 元数据复核（2026-07-21）

## 结论

本次已经取得两份可校验的朴朴 APK，包名、版本号、文件 SHA-256、证书 SHA-256 和签名方案均已验证：

- `artifacts/apk/pupu-downkuai.bin` → 6.4.9
- `artifacts/apk/Pupu-6.4.1-APKPure.apk` → 6.4.1

两份 APK 使用同一证书，均为 `v1/v2/v3`，没有 `v31`。6.4.9 的 manifest 明确暴露了 SecNeo 壳：`com.secneo.apkwrapper.AW` / `com.secneo.apkwrapper.AP`。当前还没拿到可直接复用的 `seal/sign` 生成器。

## 核验结果

| APK | 来源 | 文件 SHA-256 | package | versionName | versionCode | minSdk / targetSdk | 证书 SHA-256 | 签名方案 |
|---|---|---|---|---|---|---|---|---|
| `pupu-downkuai.bin` | Downkuai CDN，入口页 `https://www.downkuai.com/android/58394.html`，直链落点见 `artifacts/apk/downkuai.headers.txt` | `81475B9A141211B5275B1B594926B9ACE705A875BAE85C0DA70DAFD0A3A310A8` | `com.pupumall.customer` | `6.4.9` | `600409` | `24 / 33` | `0046AF697FA20E59A23786EC11229013FF07F632EDE57881CBA83DE5AF14F636` | `v1/v2/v3` |
| `Pupu-6.4.1-APKPure.apk` | APKPure CDN，入口页 `d.apkpure.com` 302 到 `data.winudf.com`，见 `artifacts/apk/Pupu-6.4.1-APKPure.headers.txt` | `F3949A7914A57B2ABF01F12A3C9E6F36BA36FDFCDD77982516EF252B57845F6E` | `com.pupumall.customer` | `6.4.1` | `600401` | `24 / 33` | `0046AF697FA20E59A23786EC11229013FF07F632EDE57881CBA83DE5AF14F636` | `v1/v2/v3` |

可交叉核验文件（本地 evidence，不提交 Git）：

- `C:\Users\10579\work\pupu-audit\artifacts\apk\apk-metadata-androguard.json`
- `C:\Users\10579\work\pupu-audit\artifacts\apk\apk-signing-block-detect.json`
- `C:\Users\10579\work\pupu-audit\artifacts\apk\apk-signing-block-cert-extract.json`
- `C:\Users\10579\work\pupu-audit\artifacts\apk\sha256-crosscheck.txt`
- `C:\Users\10579\work\pupu-audit\artifacts\apk\*keytool.txt`
- `C:\Users\10579\work\pupu-audit\artifacts\apk\*jarsigner-summary.txt`

## 静态反编译观察

### 1. Java / smali 入口被壳包住

6.4.9 的 manifest：

- `application = com.secneo.apkwrapper.AW`
- `appComponentFactory = com.secneo.apkwrapper.AP`

6.4.1 和 6.4.9 的可见 Java 代码都极少，主要只剩：

- `com/pupumall/customer/R.java`
- `com/secneo/apkwrapper/*`

也就是说，当前公开可见的 Java / smali 层没有直接露出可用的 `seal/sign` 实现。

### 2. 业务层有一个请求摘要/签名线索，但还不是最终 `seal/sign`

在 6.4.9 的 Hermes / JS bundle 里，已经能看到一个像请求签名辅助函数的逻辑：

- 位置：`artifacts/hbc649.index.decomp.js:980979-981030`
- 依赖：`pp_os`、`unique_id`、`secret`、`timestamp`
- 过程：`Object.keys(params).sort()` → `query-string.stringify(..., {encode:false, sort:false})` → `md5`

这说明业务层确实有签名/摘要相关处理，但它仍不是已验证的 `seal/sign` 完整实现，也还没拿到 GET/POST 固定向量。

### 3. 原生层还没打透

当前能看到的原生库包括：

- `libentryexpro.so`
- `libppcurl.so`

但还没从 native 层提取出可复用的 `seal/sign` 入口、参数序列化规则或完整输出向量。

## 未验证内容

- `ppAppSecret`、`ppOs` 的真实值
- `seal/sign` 的完整参数顺序和序列化
- `sign` / `seal` 的最终输出格式
- 受保护接口的真实输入输出向量
- native 层是否还有额外混淆或二次封装

## 结论

当前可以确认：

- APK 元数据已验证
- 同一证书、同一签名方案已验证
- 业务层存在签名辅助逻辑
- 但还没有得到可直接交付的 `seal/sign` 完整实现

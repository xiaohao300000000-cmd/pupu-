# 朴朴兼容性与项目真实性复核证据表

复核日期：2026-07-21（Asia/Shanghai）
范围：只读复核 APK、公开 GitHub 源码和本地实现；不登录、不改购物车、不下单。

## 总结结论

当前可以确认两份 APK 的元数据和签名方案一致，但仍不能声称已经拿到可交付的 `seal/sign` 完整实现。公开 GitHub 仓库里没有可直接复用的完整签名生成器；本地项目也保持 fail-closed。最新一次公开网络验证脚本仍失败，未取得 HTTP/API 响应。

## 证据表

| 复核项目 | 结论 | 验证方法 | 证据位置 | 可信等级 | 尚未验证 / 备注 |
|---|---|---|---|---|---|
| APK 文件来源 | 已取得两份可校验 APK：6.4.9 与 6.4.1 | 直接下载 + 文件哈希交叉校验 | `artifacts/apk/downkuai.headers.txt`、`artifacts/apk/Pupu-6.4.1-APKPure.headers.txt`、`artifacts/apk/sha256-crosscheck.txt` | 高 | 来源页分别为 Downkuai 和 APKPure 公开镜像 |
| APK 元数据 | 已验证包名、版本、版本代码、minSdk、targetSdk | `androguard` + manifest + 签名块解析 | `artifacts/apk/apk-metadata-androguard.json`、`artifacts/apk/pupu-6.4.9-downkuai-apktool/AndroidManifest.xml`、`artifacts/apk/Pupu-6.4.1/apktool/AndroidManifest.xml` | 高 | 两份 APK 的 package 都是 `com.pupumall.customer` |
| APK 签名方案 | 已验证 v1/v2/v3，证书 SHA-256 一致 | `keytool` / `jarsigner` / 自写 signing block 解析 | `artifacts/apk/apk-signing-block-detect.json`、`artifacts/apk/apk-signing-block-cert-extract.json`、`artifacts/apk/*keytool.txt` | 高 | `v31=false` |
| APK 静态逆向入口 | 目前只见 SecNeo 壳，没见到可直接复用的 Java `seal/sign` | JADX / apktool / rg | `artifacts/decompiled/sources`、`artifacts/apk/Pupu-6.4.1/jadx/sources`、`artifacts/apk/pupu-6.4.9-downkuai-apktool/smali` | 高 | 仅见 `R.java` 与 `com/secneo/apkwrapper/*`；业务逻辑未直接裸露 |
| 业务层签名辅助 | 已定位到一段像请求摘要/签名辅助的 JS 逻辑，但不是最终 `seal/sign` | Hermes / bundle 反编译（本地证据） | `artifacts/hbc649.index.decomp.js`、`artifacts/hbc649.common.decomp.js`、`artifacts/hbc649.decomp.js` | 中 | 线索包含 `pp_os`、`unique_id`、`secret`、`timestamp`，以及 `Object.keys(...).sort()` + `md5` |
| Hermes `withSecSign` 请求级开关 | 已确认多个接口传入 `withSecSign: true`，请求包装层会把它透传到 native request config | Hermes / bundle 反编译行号复核 | `artifacts/hbc649.index.decomp.js:200105`、`:344334`、`:491860`、`:633048`、`:1796836-1796889` | 中 | 证明存在请求级签名开关；未证明 Hermes 层包含 `seal/sign` 算法 |
| 壳后 payload `seal/sign` 字符串 | 已确认 payload 中存在 `HEADER_SEAL/HEADER_SIGN`、`seal-v2/v3`、`sign-v2/v3`、`pp-seqid/pp-time` 等字符串 | payload 字符串表 / 二进制扫描 | `artifacts/classes_payload_strings.txt`、`docs/research/seal-sign-static-followup-2026-07-21.md` | 中 | 字符串证明实现或校验路径存在，但不足以还原算法 |
| native 层 | 已确认存在原生库，但还没打透 | 目录扫描 / 字符串初扫 | `artifacts/apk/pupu-6.4.9-downkuai-apktool/lib/**`、`artifacts/native-string-interesting-649.txt` | 中 | `libentryexpro.so`、`libppcurl.so` 还需继续分析 |
| `cddjr/check` 请求头与身份参数 | 旧版代码中存在完整的若干请求头/Token 处理 | 固定提交逐行静态读取 | [`pupu_api.py#L48-L77`](https://github.com/cddjr/check/blob/a7da0d90a55a0b345b70dde1549591a69e2cd417/pupu_api.py#L48-L77)、[`#L80-L134`](https://github.com/cddjr/check/blob/a7da0d90a55a0b345b70dde1549591a69e2cd417/pupu_api.py#L80-L134) | 高 | 适用于旧版脚本自身，不是当前 APK 签名证明 |
| `cddjr/check` HTTP 调用 | 直接组装 headers 并调用 HTTP session；无独立签名层 | 固定提交逐行检查 | [`pupu_api.py#L190-L223`](https://github.com/cddjr/check/blob/a7da0d90a55a0b345b70dde1549591a69e2cd417/pupu_api.py#L190-L223) | 高 | 未发现 `seal/sign` 生成器 |
| `cddjr/check` 的 `SignIn` | 完整的业务签到接口，不是请求签名 | 固定提交逐行检查 | [`pupu_api.py#L428-L446`](https://github.com/cddjr/check/blob/a7da0d90a55a0b345b70dde1549591a69e2cd417/pupu_api.py#L428-L446)、`ck_pupu_sign.py#L46-L75` | 高 | 名称 `sign` 容易误读；应分类为业务动作 |
| `cddjr/check` 的订单/购物车结论 | `CreateOrder` 是下单接口；未证明购物车读写 | 固定提交逐行检查 | [`pupu_api.py#L1069-L1135`](https://github.com/cddjr/check/blob/a7da0d90a55a0b345b70dde1549591a69e2cd417/pupu_api.py#L1069-L1135) | 高 | 不得把订单创建等同购物车控制 |
| issue #3 算法线索 | 仅部分文字描述，非实现、非验证向量 | 只读查看 issue；未把评论当代码 | [`docs/research/pupu-signature-audit-2026-07-21.md`](./pupu-signature-audit-2026-07-21.md) | 中 / 低 | 缺字段顺序、序列化、魔改 MD5/Base64、XXTEA key/轮数、seal 序列化和真实输出向量 |
| 本地 `PupuSignatureService` | 已有协议、公共路由显式 `none`、受保护路由 fail-closed；没有算法 | Python 源码静态检查 | [`signature.py#L15-L63`](../../src/pupu_assistant/integrations/pupu/signature.py#L15-L63) | 高 | `SEAL_SIGN` 只是策略标记，不代表真实签名已生成 |
| 本地 HTTP 调用链 | 符合“业务模块 → SignatureService → HTTP Client → Pupu API” | 源码和架构测试 | [`client.py#L28-L143`](../../src/pupu_assistant/integrations/pupu/client.py#L28-L143)、[`system.py#L18-L31`](../../src/pupu_assistant/integrations/pupu/system.py#L18-L31)、[`test_pupu_http_boundary.py#L19-L30`](../../tests/architecture/test_pupu_http_boundary.py#L19-L30) | 高 | 只证明架构，不证明服务端接受签名 |
| 单元/Mock/架构测试 | 目标测试集 `62 passed` | `py -3.12 -m pytest -q` | 测试命令与源码 | 高 | 之前的 Windows `fcntl` 问题已修复 |
| 真实网络公共接口 | 最近一次运行失败；未取得 HTTP/API 响应 | `py -3.12 scripts/validate_pupu_public.py` | `.local/evidence/public-server-time.json` | 高（失败事实） | `http_status` / `pupu_errcode` 仍为 null；网络失败不能推断接口或签名正确性 |

## 可接入材料缺口

当前可以提供的是 Python 源码接口与调用链，主仓库提交为 `48437837ce4e9bd113f9132d8cb585fd85cd468b`。仓库未发现根目录许可证文件；README 说明上游代码需按来源和许可证另行确认。`cddjr/check` 提交为 `a7da0d90a55a0b345b70dde1549591a69e2cd417`，其公开仓库标注 MIT，但 README 还存在非商业研究限制表述，商业使用前必须单独确认授权。

尚未具备用户要求的最小签名材料：

- 当前 APK 的完整 `seal/sign` 参数顺序
- 固定 GET / POST 向量
- `ppAppSecret` / `ppOs` 的真实值
- native 层的最终输出格式
- 服务端可验证的真实只读签名回放结果

## 2026-07-21 black-box signer fixture

| Area | Evidence | Conclusion | Verification |
|---|---|---|---|
| Black-box signer wrapper | `.local/bin/pupusgn`, `.local/pupusgn-test.json`, `.local/pupu-cases.json` | Implemented as offline placeholder/result-merger; no real credentials or network I/O | `py -3.12 -m pytest tests/integrations/pupu/test_blackbox_signer.py -q` |

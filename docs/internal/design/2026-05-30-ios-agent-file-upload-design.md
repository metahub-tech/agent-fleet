# iOS Agent 文件上传 — agent 字节 → mac host 暂存 → iOS 设备(Photos / app 沙盒)

**Date:** 2026-05-30
**Status:** approved (design), implemented + iPad iOS 26.5 真机已验
**Platform:** ios-device (跟随 Android `feat/android-file-upload` 同款架构)

> **实施期 spec 微调(真机部署期发现,见 PR 与 commit log 详情)**:
> 1. **WDA 路由注册改为运行时协议自发现**:Appium WDA 13.x 用 `FBClassesThatConformsToProtocol(<FBCommandHandler>)` 自动收类,**无需** 手改 `FBCommandRouter.m`。`FBPhotosCommands.{h,m}` 放 `WebDriverAgentLib/Commands/`(非老版 `Routes/`),实现 `<FBCommandHandler>` 协议即被自动挂载。`install.sh` 跳过 router 注入步骤。
> 2. **`project.pbxproj` 需注册新文件**:WDA 项目没用 file-system synchronized groups,新源文件必须加进 pbxproj 的 PBXBuildFile/PBXFileReference 等表。用 `pbxproj` python 库做 `add_file/remove_file_by_path`(install.sh 缺包自动 `pip install --user pbxproj`)。
> 3. **WDA HTTP body 用 JSON+base64,不是 raw body**:WDA 的 `FBRouteRequest` 只暴露 `arguments`(JSON 解析后的 body)字典,没有 raw body / headers API。mac→WDA payload 改为 `{"file_b64":"...","filename":"...","type":"image|video"}`。base64 ~33% 膨胀对本地 127.0.0.1 通信完全可接受。
> 4. **mac→WDA 走 per-device forward port,不是固定 8100**:WDA HTTP `:8100` 在设备上,mac 端经 `_ensure_forwarder_and_client(udid)` 拿到的 WdaClient.base_url(`http://127.0.0.1:18100+N`,pymobiledevice3 usbmux forward 起的)。`wda_photos_import` 接 `base_url=` 参数,由 `/upload` handler 注入。
> 5. **WDA 响应是 WebDriver 协议 envelope**:`{"value": {真实响应}, "sessionId": null}`。Python 客户端 unwrap `value` 后再判 ok/error。
> 6. **超时 + 静默失败硬化**(code-review 后):tmp 删放进 completionHandler 内(超时分支不删,防与晚到的 change block 抢读);captures `BOOL ok` 显式判断 `!ok` 即使 err 为 nil 也报失败;`assetId == nil` 也报失败。

## Problem

iOS 没有 Android 上"agent→设备文件上传"特性(2026-05-28, PR #53)的对应能力,根因有两层:

1. **传输断层(同 Android)**:ios-device MCP server 跑在 mac host 上,通过 pymobiledevice3 操作设备。现有 `push_file_to_app(host_path, bundle_id, device_relpath, …)` 的 `host_path` 只读 **mac host 本地磁盘**,而 agent 要上传的文件(qinπ.png 类素材、视频)在 **agent 自己的机器**上 —— ios server 看不见,字节没法传到 mac、自然推不进设备。

2. **写入相册更难**:iOS 16+ 的 Photos library 需要 `PHPhotoLibrary` API,纯 pymobiledevice3 / shell 写不进去。旧的 `afc → /var/mobile/Media/DCIM` trick 在 iPad iOS 26 必废,只对 iPhone7(iOS 15)凑效 —— 不通用。

3. agent 的实际诉求(基于 Android 已验证的换背景/上传素材流程)是把**任意图片/视频送到 iOS 设备的 Photos 相册**,且要支持现代 iOS(主测 iPad iOS 26.5,兼顾 iPhone7 iOS 15.8)。

## Goal

让 agent 能把自己持有的字节(本地文件 / URL / inline base64)送到 iOS 设备,**主路径默认进 Photos 相册**(图片/视频),次路径推进指定 app 沙盒。跨 iPad(iOS 26) / iPhone7(iOS 15) 通用,长期可靠。

镜像 Android `/upload` HTTP 端点 + MCP 工具的形态,后端换 iOS 栈(pymobiledevice3 + 扩展的 WDA)。

## Architecture

### 数据流

```
                       ┌─ target=photos: mac 包成 JSON{file_b64,filename,type} → WDA → NSTemp → PHPhotoLibrary
agent 字节 ──HTTP POST─┤
                       └─ target=app:    流式落 mac 暂存 → pymobiledevice3 afc push → bundle_id 沙盒
```

### 两条目标路径(target 参数)
- **`target=photos`(默认)**:**WDA 直收字节**。mac host `/upload` 把字节包成 JSON `{"file_b64":"...", "filename":"...", "type":"image|video"}` 后 `POST http://127.0.0.1:<wda_local_port>/wda/photos/import`(`wda_local_port` 由 `_ensure_forwarder_and_client(udid)` 返回的 WdaClient.base_url 提供,18100+N,pymobiledevice3 usbmux forward 起的)。**为什么 JSON+base64 不是 raw body**:WDA 13.x 的 `FBRouteRequest` 只暴露 `arguments`(JSON 解析后的 body)字典,无 raw body/headers API;走 JSON 是兼容现状的最小代价。base64 ~33% 膨胀对本地 127.0.0.1 通信完全可接受。WDA route handler 内:
  1. 从 `request.arguments[@"file_b64"]` 取串 base64 解码 → 写到 `NSTemporaryDirectory()/<uuid>-<filename>`;
  2. 调 `PHPhotoLibrary.shared().performChanges:` 创建 `PHAssetCreationRequest.creationRequestForAssetFromImageAtFileURL:` / `forVideoAtFileURL:`;
  3. 用 `dispatch_semaphore_t` 等 `completionHandler`(超时 30s);
  4. 删临时文件,返回 `{ok:true, asset_id:"<localIdentifier>"}` / `{ok:false, error:"..."}`。

  > **为何不走 afc 推 WDA 沙盒**:WDA runner 是 XCUITest target,`Info.plist` 没有 `UIFileSharingEnabled`,`house_arrest` 写不进去。直接让 WDA 通过自己的 HTTP 接口收字节绕过这条限制,顺带省一跳 + 不需要 WDA bundle ID 解析。
- **`target=app`**:走 pymobiledevice3 路径。mac host `/upload` 流式落主机暂存 → `_afc_op(udid, bundle_id, documents_only, …push)` 推到目标 app 沙盒(等价旧 `push_file_to_app`,但**字节来自 agent**,不是 mac host 磁盘)。`documents_only` 同旧契约(默认 true,目标 app 须 `UIFileSharingEnabled` 或 dev-signed)。

### MCP 端点 + 共享 helper 抽取
- **HTTP 端点**:`POST /upload` 挂在现有 ios-device server(port 8769)的 Starlette `custom_route`(同 Android 模式,绕 MCP 25s 工具调用死线)。
- **共享 helper**:把 Android `_uploads.py` 里平台无关的 helper(`parse_bool` / `sanitize_filename` / `validate_relpath` / `resolve_upload_target` / `download_url` / `_ip_is_blocked` / 流式落盘 helper)抽到 `platforms/common/_upload_common.py`。Android `_uploads.py` 切到引用 common,iOS 新 `_uploads_ios.py` 也引用。改动有限、Android 测试全 reuse。
- **iOS 专属逻辑**:`_uploads_ios.py` 含 WDA bundle 解析、`afc_push_to_wda_sandbox`、`call_wda_photos_import`、`afc_push_to_app`。

## Tool Surface

新增 3 个 MCP 工具:`upload_to_photos` / `upload_to_app` / `get_upload_endpoint`,加 1 个 HTTP `/upload` 路由(custom_route,非工具,不计数)。文档更新时按 ios server 实际 `@mcp.tool` 数量(`tests/test_tool_signatures.py`(若有)同步)校准。

### 1. `POST /upload`(HTTP,首选)
Query 参数:
- `target=photos|app`(默认 photos)
- `filename`(photos 推荐传;app 沙盒可省,从 relpath 推)
- `bundle_id`(target=app 必填)
- `relpath`(target=app 必填,app 沙盒相对路径,默认 documents_only)
- `documents_only=true|false`(target=app,默认 true)
- `device`(udid 或 alias;单设备可省)

Body:文件字节(`--data-binary @file`,或 multipart `file` 字段)。

返回:
```json
target=photos: {"ok":true,"target":"photos","device":"<udid>","asset_id":"<PHAsset.localId>","size":N,"filename":"..."}
target=app:    {"ok":true,"target":"app","device":"<udid>","bundle_id":"...","relpath":"...","documents_only":true,"size":N}
失败:          {"ok":false,"error":"...","hint":"...","stage":"download|afc|wda|phlibrary"}
```

### 2. `upload_to_photos(content_base64?|url?, filename, device?)`
MCP 工具。小图 base64 同步上传到相册;url 同步上限 ~20MB(USB)/~8MB(无线),超走 HTTP。

### 3. `upload_to_app(content_base64?|url?, bundle_id, relpath, documents_only=True, device?)`
MCP 工具。同上,但目标 app 沙盒。

### 4. `get_upload_endpoint()`
MCP 工具。返回 `/upload` 用法 + curl 例子(host 同 ios-device MCP URL,port 8769)。

**不做**:`stage_upload` / `deliver_staged` / `job_status` —— HTTP `/upload` 已覆盖大文件;MCP 工具留 inline 小数据(YAGNI)。

## WDA Extension(新增,关键部件)

### 路由(JSON+base64 body)
新加 ObjC 文件 `WebDriverAgentLib/Commands/FBPhotosCommands.h/.m`(WDA 13.x 用 `Commands/`,非老版 `Routes/`),实现 `<FBCommandHandler>` 协议即被 `FBClassesThatConformsToProtocol` 在运行时自动发现并挂载 —— **无需手改 router 文件**。注册:
```
POST /wda/photos/import
Content-Type: application/json
body: {
  "file_b64": "<base64>",   // 必填
  "filename": "bg.jpg",      // 可选,用于 NSTemp 文件命名 + 调试
  "type":     "image"        // image | video,可选,缺省按 filename 后缀推
}
```
Handler 关键逻辑(伪码):
```objc
// 1. 从 request.arguments 拿 file_b64/filename/type, base64 解码出 NSData
NSData *fileData = ...; NSString *type = ...;
NSString *tmpPath = [NSTemporaryDirectory() stringByAppendingPathComponent:
                       [NSString stringWithFormat:@"%@-%@", [NSUUID UUID].UUIDString, filename]];
[fileData writeToFile:tmpPath atomically:YES];

// 2. PHPhotoLibrary 异步,必须等 completionHandler 再响应 HTTP
__block NSString *assetId = nil;
__block NSError *blockErr = nil;
dispatch_semaphore_t sem = dispatch_semaphore_create(0);

[[PHPhotoLibrary sharedPhotoLibrary] performChanges:^{
    PHAssetCreationRequest *req;
    NSURL *url = [NSURL fileURLWithPath:tmpPath];
    if ([type isEqualToString:@"video"]) req = [PHAssetCreationRequest creationRequestForAssetFromVideoAtFileURL:url];
    else                                  req = [PHAssetCreationRequest creationRequestForAssetFromImageAtFileURL:url];
    assetId = req.placeholderForCreatedAsset.localIdentifier;
} completionHandler:^(BOOL ok, NSError *err) {
    blockErr = err;
    dispatch_semaphore_signal(sem);
}];

// 30s 超时,避免授权弹窗等永久阻塞
long waitRc = dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 30LL * NSEC_PER_SEC));
[[NSFileManager defaultManager] removeItemAtPath:tmpPath error:nil];

if (waitRc != 0)    return /* {"ok":false,"error":"PHPhotoLibrary timeout"} */;
if (blockErr)       return /* {"ok":false,"error": blockErr.localizedDescription, "code": blockErr.code} */;
return /* {"ok":true, "asset_id": assetId} */;
```

### 路由必须显式注册(WDA Routes 是静态聚合)
Appium WDA 13.x 在 `FBWebServer.m` 用 `FBClassesThatConformsToProtocol(@protocol(FBCommandHandler))` 在运行时反射所有实现该协议的类并 `registerRouteHandlers:`。**只要 FBPhotosCommands 实现 `<FBCommandHandler>` + 提供 `+routes`,被编译进 binary 即被自动挂载**,无需修改任何 router 源文件。但 WDA 项目用静态 pbxproj 文件清单(非 file-system synchronized groups),新加的 .h/.m 必须通过 `pbxproj` python 库 `add_file(target_name="WebDriverAgentLib")` 注册到 PBXBuildFile/PBXFileReference 等表才会被编译。`install.sh` 缺包时自动 `pip install --user pbxproj`。

### Info.plist 注入(PlistBuddy,不要文本 patch)
WDA runner `Info.plist` 加 `NSPhotoLibraryAddUsageDescription`。用 `PlistBuddy` 幂等 upsert(`Add … || Set …`),不要文本 diff(易因换行/BOM/格式差异碎)。**Add-Only**,不加 `NSPhotoLibraryUsageDescription`(读权限)—— 权限最小化。
```sh
/usr/libexec/PlistBuddy -c "Add :NSPhotoLibraryAddUsageDescription string '用于把上传的图片/视频加入相册'" \
  "$WDA_DIR/WebDriverAgent/WebDriverAgentRunner/Info.plist" 2>/dev/null \
|| /usr/libexec/PlistBuddy -c "Set :NSPhotoLibraryAddUsageDescription '用于把上传的图片/视频加入相册'" "$..."
```

### Build cache 失效
`cp` 文件 mtime 被覆盖为当前,xcodebuild 增量 build **会**重编新文件;但若被修改的源文件已 touch 过且 DerivedData 哈希未变,有可能跳编。`install.sh` 在注入完后 `touch -m` 所有修改过的源文件(`.h/.m`、`project.pbxproj`、`Info.plist`),强制让 mtime 比 DerivedData 缓存条目新。首次扩展后建议手动跑一次 `xcodebuild clean`。

### 部署(沿用现有 daemon 模式)
- `platforms/ios/wda-ext/FBPhotosCommands.{h,m}` 维护在本仓库;`build-wda.sh` 在 `xcodebuild` 前自动 cp 到 `$WDA_DIR/WebDriverAgentLib/Commands/` + pbxproj 注册 + plist upsert。卸载:`wda-ext/uninstall.sh`(pbxproj remove + 删 cp 的文件 + 删 plist key)。
- `refresh-wda-cert.sh` / `install-wda-daemon.sh` 流程不变。
- **首次相册授权**:WDA 第一次调 PHPhotoLibrary,iOS 弹"WDA 要添加到您的相册"。用户**需在设备上点一次允许**。授权后所有后续上传无 prompt。`/upload` 在首次返 `{ok:false, error:"...denied...", hint:"在 iPad 设置 → 隐私 → 照片 → WebDriverAgent → 添加照片,允许后重试"}`。可选:WDA 启动时主动 `[PHPhotoLibrary requestAuthorizationForAccessLevel:PHAccessLevelAddOnly handler:]` 让弹窗在第一次 upload 之前出现(体验更好,但实施时再定)。

### WDA 端口(target=photos 唯一外部依赖)
WDA 默认 `:8100`,由 go-ios tunnel forward 到 mac host(`http://127.0.0.1:<wda_port>`)。`/upload` handler 从 `~/.agent-fleet/ios-config.json` 或 env `ATB_IOS_WDA_PORT` 读(默认 8100)。**不再需要 WDA bundle ID**(因为不走 afc 推 WDA 沙盒)—— bundle ID 仅 `target=app` 路径需要,且由 caller 显式传 `bundle_id` 参数。

## Data Flow(典型流程)

1. **agent 给 iPad 换背景图(4.4MB qinπ.png)**:
   - `curl -X POST -F file=@qinπ.png -F type=image -F filename=qinπ.png \
       'http://qjl-mac-mini:8769/upload?target=photos&device=apple-ipad15-7'`
   - mac host `/upload` 把字节包成 JSON `{file_b64, filename, type}` 发给 WDA `http://127.0.0.1:<per-device-port>/wda/photos/import` → WDA decode 写 NSTemp → PHPhotoLibrary 创建 asset(sem 等 completion;tmp 由 completionHandler 收尾防超时竞态)→ 返回 `{ok:true, asset_id:"..."}`(经 WebDriver envelope `{"value":...,"sessionId":...}` 包装,Python 客户端 unwrap)。
   - iPad 相册 / 小红书选图器立刻看到。无 mac 暂存落盘(target=photos 全程流式)。

2. **MCP 小图同步**:
   - `upload_to_photos(content_base64="...", filename="bg.jpg")` → 内部 base64 解码后(再 base64 包进 JSON)发给 WDA(同 #1 流程),返回 asset_id。

3. **推 PDF 到某文件 app**:
   - `curl ...?target=app&bundle_id=com.example.docs&relpath=Documents/x.pdf` → afc 推进沙盒 → 返回。

## Error Handling & Security

- **入参互斥/必填校验**:`content_base64` 与 `url` 二选一(MCP 工具);target=app 必须 `bundle_id+relpath`。失败 400 + 明确 error。
- **路径校验**:`filename` / `relpath` 走共享 `sanitize_filename` / `validate_relpath`(拒 `..`、绝对路径、引号 / `;` / `$` / 反斜线等注入面)。WDA 端 path 字段额外校验在 WDA 沙盒前缀内。
- **SSRF**:url 走共享 `download_url`(http/https only + 内网/loopback/link-local/reserved/metadata IP 拒 + DNS 重绑定对端复验)。
- **大小**:`URL_HARD_MAX=200MB`(共享);mac `/upload` 流式读 body + 边写边复核;multipart 用 UploadFile 分块读 64KB。mac→WDA 的 JSON+base64 body 体积约为原文件 ×1.33,本地 127.0.0.1 通信不构成瓶颈。
- **WDA 不可达**:`/upload?target=photos` 先 ping `http://127.0.0.1:<port>/status`,超时/4xx → 500 + hint("WDA daemon 未跑;`launchctl list | grep wda` 检查")。
- **PHPhotoLibrary 失败**:WDA 返回的 error 直接透传给 caller;首次授权拒/缺权限有专门 hint 引导设备端"设置 → 隐私 → 照片 → WDA → 添加照片"。
- **AFC 失败**:`HouseArrestException`(app 不可 file-share)→ hint 提示 `documents_only` 或 dev-signed 限制。
- **暂存清理**:try/finally 删 mac 暂存 tmp;失败路径也清。
- **鉴权**:tailnet-trust(同 Android);不做 token。

## Files

### 新增
- `platforms/common/_upload_common.py` —— 共享 helper(parse_bool / sanitize_filename / validate_relpath / resolve_upload_target / download_url / _ip_is_blocked / 流式落盘 / IMAGE_VIDEO 扩展名表)。
- `platforms/ios/server/_uploads_ios.py` —— iOS 专属:wda_bundle 解析、afc_push_to_wda_sandbox、call_wda_photos_import、afc_push_to_app、`_http_upload_worker`(threadpool 同步执行)。
- `platforms/ios/server/tests/test_uploads_ios.py` —— 单测(纯逻辑,mock pymobiledevice3 + requests)。
- `platforms/ios/wda-ext/FBPhotosCommands.{h,m}` —— **不 fork WDA**(WDA 在每台 mac 主机的 `$WDA_DIR`,默认 `~/WebDriverAgent`,非本仓库子项目),本仓库维护这两个扩展文件。
- `platforms/ios/wda-ext/install.sh` —— 在 `build-wda.sh` 内被调用,幂等做四件事:① cp `.h/.m` 到 `$WDA_DIR/WebDriverAgentLib/Commands/`(WDA 13.x 路径);② 通过 `pbxproj` python 库 `add_file(target_name="WebDriverAgentLib")` 注册新文件(已存在则跳过;首次运行缺包自动 `pip install --user pbxproj`);③ `PlistBuddy` upsert `NSPhotoLibraryAddUsageDescription` 进 WDA runner `Info.plist`(Add-Only 权限);④ `touch -m` 所有修改过的源文件强制 build cache 失效。**无需** 改 `FBCommandRouter.m` —— WDA 13.x 用 `<FBCommandHandler>` 协议运行时自发现。
- `platforms/ios/wda-ext/uninstall.sh` —— 反向还原(删 cp 的文件、去 import/routes 行、删 plist key)。

### 改
- `platforms/android/server/_uploads.py` —— 切到 `from _upload_common import ...`,删冗余;保留 android 专属(JobRegistry / adb runner / kill-stale / android specific tool args)。**注意** `_FORBIDDEN_PATH_CHARS` 含单引号是 Android 专属(防 `content query --where _data='...'` 的 SQL 注入),iOS 不需要相同字符集 —— 共享版按"通用最小集"+ 在共享函数文档串里注明 Android 额外补什么;Android 自己在 import 后做额外校验。Android 现有 63 单测不变。
- `platforms/ios/server/ios_device_mcp.py` —— 加 3 个 MCP 工具(`upload_to_photos` / `upload_to_app` / `get_upload_endpoint`)+ 1 个 `@mcp.custom_route("/upload")` Starlette 路由 + import _uploads_ios。
- `platforms/ios/scripts/build-wda.sh` —— 在 xcodebuild 前调用 `wda-ext/install.sh`(幂等);若 install.sh 失败则 build-wda.sh 退出,不进入 build 阶段(避免编译出无新路由的 WDA)。
- `platforms/ios/server/tests/test_tool_signatures.py`(若有,核对工具数)。
- 文档:`platforms/ios/README.md` 工具表 + 新章节;`platforms/ios/skills/using-ios/SKILL.md` 上传节;`docs/architecture.md` iOS 能力行;`CHANGELOG.md`。

## Testing

- **单测**(共享 + iOS 专属,Python pytest):
  - 共享 helper(已有 Android 单测覆盖,迁移到共享模块后保持绿)。
  - iOS 专属:wda_bundle 探测/读取/缺失报错;target/参数互斥校验;`/upload` handler 的流式落盘(mock pymobiledevice3 + requests);PHPhotoLibrary 调用错误透传。
- **WDA Swift 扩展**:不在 Python CI;靠真机集成验证 + Code 自审。
- **真机(iPad iOS 26.5 在 qjl-mac-mini)** —— 必跑:
  1. 小图 base64 via `upload_to_photos` → 返回 visible/asset_id;设备相册 app 打开看到。
  2. curl `/upload?target=photos` 推中图(~500KB)→ 同上。
  3. curl 推 4.4MB qinπ.png → asset_id 返回,相册可见(对比 Android 同图)。
  4. curl 推小 mp4 视频(几 MB)→ 相册"视频"分类可见。
  5. curl `/upload?target=app&bundle_id=<WDA>` 推 PDF → afc 落进沙盒(pull 验证)。
  6. **首次相册授权**:第一次跑时设备弹窗 → 你点允许 → 复试通过(记入文档)。
- **iPhone7 iOS 15.8(可选,同 PR)**:同 1+3+4 三组烟测。代码/WDA 扩展同份。
- **质量门禁**:Python 部分派 `feature-dev:code-reviewer`(同 Android 流程);WDA 扩展真机定稿。

## Out of Scope

- **从相册读取/枚举**(只 ADD 不 READ,权限最小化)。
- **视频压缩 / 转码**(原文件如实写库)。
- **HEIC / Live Photo 特殊处理**(PHPhotoLibrary 自然处理,够用)。
- **stage_upload / deliver_staged 异步分片**(HTTP /upload 已覆盖大文件,YAGNI;若将来要 MCP-only 上传 >200MB 再补)。
- **启动器加固**(iOS host 用 launchd + install-wda-daemon.sh,与 Windows Task Scheduler 不同;本轮不动)。
- **iPhone7(iOS 15)上 afc-DCIM 老 trick**(虽可能在 iOS 15 凑效,但保留也增加维护负担;WDA 扩展跨版本统一)。

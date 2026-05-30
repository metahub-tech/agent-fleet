# agent-fleet WDA 扩展(Photos import)

给 WebDriverAgent 加一个 `POST /wda/photos/import` 路由,把上传的图片/视频通过 `PHPhotoLibrary` 加入 iOS 设备相册。**iOS 16+ 没有 pure-shell/afc 通道写入相册库;`afc` 也写不进 WDA runner 自己的沙盒(XCUITest target 没 `UIFileSharingEnabled`)** —— 因此 WDA 直接收 raw body、内部写 NSTemp + 调 PHPhotoLibrary 是唯一通用路径。

## 文件
- `FBPhotosCommands.h` / `FBPhotosCommands.m` —— route + handler(`dispatch_semaphore` 等 `performChanges` completion,30s 超时)
- `install.sh` —— 幂等注入到 `$WDA_DIR`(默认 `~/WebDriverAgent`):
  1. cp `.h/.m` → `WebDriverAgentLib/Routes/`
  2. 在 `FBCommandRouter.m` 注入 `#import "FBPhotosCommands.h"` + commandHandlerClasses 数组项
  3. `PlistBuddy` upsert `NSPhotoLibraryAddUsageDescription` 到 `WebDriverAgentRunner/Info.plist`(Add-Only 权限)
  4. `touch -m` 让 xcodebuild 增量 cache 失效
- `uninstall.sh` —— 反向还原

## 用法

通常**不需要直接调** —— `platforms/ios/scripts/build-wda.sh` 在 `xcodebuild` 之前会自动调 `install.sh`。手动用例:
```bash
./install.sh /path/to/WebDriverAgent
./uninstall.sh /path/to/WebDriverAgent
```

## 首次相册授权

WDA 第一次调 PHPhotoLibrary,iOS 会弹"**WebDriverAgent 要添加到您的相册**"。在设备上点**允许**。授权后所有后续 import 无 prompt。

未授权时 `wda_photos_import` 返回 `{ok:false, error:"...denied..."}` + hint 引导设置路径:**设置 → 隐私 → 照片 → WebDriverAgent → 添加照片**。

## 设计

见 `docs/internal/design/2026-05-30-ios-agent-file-upload-design.md` 的 "WDA Extension" 节。

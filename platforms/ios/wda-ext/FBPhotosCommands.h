// agent-fleet WDA 扩展 —— /wda/photos/import
//
// 接收 raw NSData body + X-Filename / X-Type 头，写入 NSTemporaryDirectory()
// 再调 PHPhotoLibrary.performChanges 把图片/视频加入相册，
// dispatch_semaphore 等 completionHandler（30s 超时）后返回 asset_id。
//
// 设计：docs/internal/design/2026-05-30-ios-agent-file-upload-design.md
// 由 platforms/ios/wda-ext/install.sh 幂等注入到 $WDA_DIR 的 WebDriverAgentLib/Commands/。
//
// Appium WDA 13.x 用运行时协议发现注册路由（FBClassesThatConformsToProtocol）：
// 只要类实现 <FBCommandHandler> 并提供 +routes，就会被 FBWebServer 自动发现并挂载，
// 无需修改 FBWebServer.m 或任何 router 文件。

#import <Foundation/Foundation.h>

#import <WebDriverAgentLib/FBCommandHandler.h>

@class FBRoute;

NS_ASSUME_NONNULL_BEGIN

@interface FBPhotosCommands : NSObject <FBCommandHandler>

+ (NSArray *)routes;

@end

NS_ASSUME_NONNULL_END

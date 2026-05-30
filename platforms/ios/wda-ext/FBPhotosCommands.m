// agent-fleet WDA 扩展 —— /wda/photos/import 实现。
// 由 platforms/ios/wda-ext/install.sh 注入到 $WDA_DIR 的 WebDriverAgentLib/Routes/，
// 并在 FBCommandRouter.m 的 commandHandlerClasses 数组里追加 [FBPhotosCommands class]。

#import "FBPhotosCommands.h"

#import "FBRoute.h"
#import "FBRouteRequest.h"
#import "FBResponsePayload.h"
#import "FBCommandStatus.h"

@import Photos;

@implementation FBPhotosCommands

+ (NSArray<FBRoute *> *)routes {
  return @[
    [[[FBRoute POST:@"/wda/photos/import"] withoutSession]
       respondWithTarget:self action:@selector(handleImport:)],
  ];
}

+ (id<FBResponsePayload>)handleImport:(FBRouteRequest *)request {
  // WDA 13.x: FBRouteRequest 只暴露 arguments(JSON 解析后的 body)，无 raw body / headers API。
  // 用 JSON+base64：body = {"file_b64": "...", "filename": "...", "type": "image|video"}
  NSString *fileB64  = request.arguments[@"file_b64"];
  NSString *filename = request.arguments[@"filename"] ?: @"upload.bin";
  NSString *ttype    = request.arguments[@"type"]     ?: @"image";

  if (!fileB64 || fileB64.length == 0) {
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:@"missing file_b64" traceback:nil]);
  }
  NSData *fileData = [[NSData alloc] initWithBase64EncodedString:fileB64
                                                         options:NSDataBase64DecodingIgnoreUnknownCharacters];
  if (!fileData || fileData.length == 0) {
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:@"base64 decode failed or empty" traceback:nil]);
  }

  // 1) 写 NSTemp
  NSString *tmp = [NSTemporaryDirectory() stringByAppendingPathComponent:
                     [NSString stringWithFormat:@"%@-%@", [NSUUID UUID].UUIDString, filename]];
  NSError *writeErr = nil;
  if (![fileData writeToFile:tmp options:NSDataWritingAtomic error:&writeErr]) {
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:
              [NSString stringWithFormat:@"write tmp failed: %@", writeErr.localizedDescription]
                                                                       traceback:nil]);
  }

  // 2) PHPhotoLibrary.performChanges 是异步，必须 semaphore 等 completion 再响应 HTTP。
  __block NSString *assetId = nil;
  __block NSError  *blockErr = nil;
  dispatch_semaphore_t sem = dispatch_semaphore_create(0);

  [[PHPhotoLibrary sharedPhotoLibrary] performChanges:^{
    NSURL *url = [NSURL fileURLWithPath:tmp];
    PHAssetCreationRequest *req = [ttype isEqualToString:@"video"]
      ? [PHAssetCreationRequest creationRequestForAssetFromVideoAtFileURL:url]
      : [PHAssetCreationRequest creationRequestForAssetFromImageAtFileURL:url];
    assetId = req.placeholderForCreatedAsset.localIdentifier;
  } completionHandler:^(BOOL ok, NSError * _Nullable err) {
    blockErr = err;
    dispatch_semaphore_signal(sem);
  }];

  long waitRc = dispatch_semaphore_wait(sem, dispatch_time(DISPATCH_TIME_NOW, 30LL * NSEC_PER_SEC));
  [[NSFileManager defaultManager] removeItemAtPath:tmp error:nil];

  if (waitRc != 0) {
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:@"PHPhotoLibrary timeout (30s)"
                                                                       traceback:nil]);
  }
  if (blockErr) {
    NSString *msg = [NSString stringWithFormat:@"%@ (code=%ld)",
                       blockErr.localizedDescription, (long)blockErr.code];
    return FBResponseWithStatus([FBCommandStatus invalidArgumentErrorWithMessage:msg traceback:nil]);
  }
  return FBResponseWithObject(@{@"ok": @YES, @"asset_id": assetId ?: NSNull.null});
}

@end

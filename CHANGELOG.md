# Changelog

All notable changes to this project will be documented in this file.

The format is based on [Keep a Changelog](https://keepachangelog.com/en/1.1.0/),
and this project adheres to [Semantic Versioning](https://semver.org/spec/v2.0.0.html).

## [Unreleased]

### 新增

- **human_dom 接入 win（pc-device 第二端）**。win server 注册 `HumanDomCapability`（注入 `_os_tap` + `_os_fill`=Ctrl+A 全选 + 剪贴板粘贴）+ `127.0.0.1:8779` loopback 桥；`platforms/windows/platform.toml` 启用 human_dom（opt-in，装扩展 + 写 `~/.fleet/human-dom-ready` marker 后 enabled）。让 win 发布员（公众号富文本编辑器里 `div[role=button]` 等只有 vision 才点得到的元素）也拿到 DOM 精度。坐标公式 win 真机标定。

- **pc-device（mac 先行）：human_dom DOM 感知能力模块**。`human_browser` 的精确定位伴生能力——在保持零 automation traces / 真实 profile / OS 级输入的前提下，通过 Chrome 扩展 content script **只读 DOM** 取得元素屏幕坐标，告别"截图猜坐标"。
  - **架构**：扩展 content script 遍历 DOM 按文字 / `aria-label` / `placeholder` / `title` / `name` 属性匹配并返回 `{text, role, center:[x,y], box, visible, clickable}`（`center` 是 `[x,y]` 列表）；坐标空间与 `take_screenshot` / `tap` 一致，直接传给 OS 级工具。扩展只读，不点击、不改 DOM、不注入合成事件；操作仍由 `tap` / `type_text` / `press_key` 完成，保持完整的 human 特征。
  - **OCR 兜底**：canvas / shadow DOM / 动态遮罩等 DOM 不可达场景，`human_dom_locate` 返回 `suggest:"vision_locate"`，自动引导转 `vision_locate`（RapidOCR）继续 OS 级操作。
  - **MCP 工具**（+3，**可选启用**——装扩展后 mac 73 → 76）：`human_dom_locate(query, css?)` 按语义查元素返回候选列表；`human_dom_tap(query, nth?, css?)` 定位后 OS 级点击；`human_dom_fill(query, text, css?)` 定位后聚焦 + 覆盖式填充（全选 + 剪贴板粘贴，支持中文）。
  - **桥**：content script ↔ pc-device server 本地 WebSocket（**只绑 `127.0.0.1` 的独立 loopback listener**，端口 8779，不挂在对 LAN 开放的 MCP app 上），无外网依赖；扩展在真实 profile 一次安装永久生效。
  - **生命周期（opt-in）**：要先把扩展装进真实 Chrome（一次性，`install-human-dom-extension.sh` Load unpacked）。server 启动按 `~/.fleet/human-dom-ready` marker 判定——装了才 `enabled`、没装 `list_capabilities` 显 `unavailable` 并引导安装。故**不计入默认工具数（mac fresh 仍 73）**。
  - **已验证（macmini 真机 e2e）**：扩展装载 + `human_dom_locate`→`tap` 精准落点（无系统性偏移，Retina 坐标公式实测对）+ 中文 `human_dom_fill` + 小红书发布页存草稿全过；marker 门控 enabled/unavailable 真机确认。win 及跨平台后续。

## [0.8.4-alpha] - 2026-06-20

### 新增

- **pc-device：vision 像素级元素定位能力模块**（win/mac，可选启用）。补 core `find_elements`/`tap_element` 的盲区——当 OS 无障碍树为空/不可用（网页、canvas、Electron 关 a11y、Flutter、游戏）时，元素只能"截图猜坐标"，vision 用像素把它定准。
  - **栈**：RapidOCR（PP-OCRv4 ONNX）+ OpenCV 模板匹配，纯 CPU、离线，无需 GPU/联网/外部模型服务；按需在 `platform.toml` 的 `[capabilities].enabled` 加 `vision` 开启。
  - **MCP 工具**（pc-device 各 +3）：`vision_locate(query, region?, max_results?)` 按文字定位、返回排序候选 `{text,center,box,score}`；`vision_tap(query, region?, nth?)` 定位后调 core tap 点击；`vision_locate_image(template, region?, threshold?)` 模板匹配定位无字图标。win 71 → 74、mac 70 → 73。
  - **职责切分（反直觉）**：OCR 只管"定位"（同图实测中位 1px、0 token），"理解"仍归 agent 自身视觉——刻意不做 `vision_read`；对照下 VLM 报坐标中位 120px、约 1280 token/次。
  - **关键实现**：复用 core 截图（同坐标空间）+ region 内存裁剪压延迟；RapidOCR 引擎进程内单例；**子行定位**（按 query 字符偏移比例切密集页合并行框，把 ~30px 误差收到几 px）；单尺度模板匹配；低对比读不出=已知局限、永不崩 server。
  - 28 单测全绿（纯逻辑 fake OCR + cv2 合成图，含并发锁压测）；macmini + test-win11 真机 e2e 通过（human_browser 真网页 → `vision_locate` → `vision_tap` 完成跳转）。

- **iOS：agent→设备文件上传**(对齐 Android 同款形态,后端换 iOS 栈)。解决"agent 自带的字节传不到 iOS 设备"(旧 `push_file_to_app` 只读 mac host 磁盘,且 Photos 库写入 iOS 16+ 无 shell/afc 通道)。
  - **HTTP `POST /upload`(首选)**:挂在 ios-device server(8769)上的 Starlette 路由,agent 直接 POST 文件字节 → mac 透传给 WDA `/wda/photos/import`(target=photos)或 pymobiledevice3 afc 推 app 沙箱(target=app)→ 返回 JSON。**任意大小**,真机已验 iPad iOS 26.5 4.4MB qinπ.png ~15s 进相册。
  - **WDA 扩展**(`platforms/ios/wda-ext/FBPhotosCommands.{h,m}`):新加 ObjC route `POST /wda/photos/import`,内部 `dispatch_semaphore` 等 `PHPhotoLibrary.performChanges` completion(30s 超时,tmp 由 completionHandler 收尾防超时竞态),`PHAssetCreationRequest creationRequestForAssetFromImage/Video` 加进相册。WDA 13.x 用运行时协议自发现(`<FBCommandHandler>`),无需手改 router;`build-wda.sh` 在 xcodebuild 前自动调 `wda-ext/install.sh`(幂等 cp + pbxproj 注入 + PlistBuddy `NSPhotoLibraryAddUsageDescription`)。Add-Only 权限,首次需设备授权一次。
  - **MCP 工具**:`upload_to_photos` / `upload_to_app` / `get_upload_endpoint`(同 Android 模式;iOS 工具数 26 → 29)。
  - **跨平台抽取**:Android 与 iOS 共用的纯逻辑(`UploadError`/`require_xor`/`decode_b64`/`parse_bool`/`sanitize_filename`/`is_image`/`is_video`/SSRF+流式 `download_url` 等)移到 `platforms/common/_upload_common.py`,Android `_uploads.py` 切引用保留专属(`_FORBIDDEN_PATH_CHARS` 叠加单引号防 SQL、`validate_device_path`、adb 命令构造、JobRegistry 等)。Android 63 测试 + iOS 12 测试 + common 11 测试全绿。

- **Android：agent→设备文件上传**。解决"agent 自带的字节传不到手机"（服务端在设备主机上看不见 agent 磁盘，旧 `push_file` 只能读主机本地路径）。
  - **HTTP `POST /upload`（首选）**：挂在现有 android-device server（8768）上的 Starlette 路由，agent 直接 POST 文件字节 → 主机流式落盘 → `adb push`（+可选 `pm install` / 媒体扫描）→ 返回 JSON。绕过 base64 上下文膨胀、分片、MCP ~25s 工具调用死线，**任意大小**。`curl -X POST --data-binary @f 'http://<host>:8768/upload?device_path=/sdcard/Pictures/x.png&make_visible=true'`。
  - **MCP 工具**：`upload_media`（base64 小文件同步、图片自动进相册）、`stage_upload`+`deliver_staged`+`job_status`（分片暂存 + 后台 push/install + 轮询，MCP-only 环境用）、`get_upload_endpoint`（发现 HTTP 端点）。Android 工具数 25 → 30。
  - **媒体可见性**：`make_visible=true` 对图片 `am broadcast MEDIA_SCANNER_SCAN_FILE`，Android10+ 实测 ~数秒异步索引后进相册/选图器（小红书换背景等）；可见性查询用规范 `_data` 路径（`/storage/emulated/0/...`）并以单条 shell 命令传递，规避 adb-shell 剥引号导致的假阴性。
  - **安全/健壮**：路径穿越 + 引号/分号/`$` 注入防护、SSRF（http/https + 内网/元数据 IP 拒绝 + DNS 重绑定对端复验）、流式落盘防 OOM、后台子进程超时清理、`reap_orphans` 跨平台（Windows 无 SIGKILL 降级）+ 启动清场。真机（华为 VOG-AL00 / Android10）验证：4.4MB 图片传至手机并进相册。

### 文档

- **9 语 README 同步**：8 个翻译版（zh-CN / ja / ko / es / fr / de / pt-BR / ru）连同英文版统一各平台工具数（win 74 / mac 73 / android 31 / ios 30，已含 vision）；本次发版把全部 README + 安装脚本（`install.sh` / `install.ps1`）的版本串与 `uvx` 安装命令从 `v0.8.3-alpha` 同步到 `v0.8.4-alpha`。

## [0.8.2-alpha] - 2026-05-21

### 新增

- **WDA 保活 daemon 化（#155）**：`platforms/ios/scripts/install-wda-daemon.sh <udid> <bundle_id>` 把 WebDriverAgent 托管给 launchd —— 开机自启 + 崩溃自动重启 + **不再常驻 `xcodebuild test`**（不占 Xcode 进程、抗重启）。架构：root LaunchDaemon `cc.metahub.ios-tunneld`（pymobiledevice3 `remote tunneld`，所有设备共用 RSD tunnel，API `:49151`）+ per-device 用户 LaunchAgent `cc.metahub.ios-wda-<udid>`（`_wda-daemon-run.sh` 查 tunnel → go-ios `runwda`，`KeepAlive` 自愈 tunnel 重启 / 热插 / 证书过期）。
- **新脚本**：`install-go-ios.sh`（拉取 go-ios pin v1.0.213 universal 二进制到 `platforms/ios/bin/`，免 brew/npm/go/Rosetta）、`_wda-daemon-run.sh`（per-device launcher，含 pause 哨兵）、`install-wda-daemon.sh`（装 daemon）、`uninstall-wda-daemon.sh`（卸载，支持 `<udid>` / `--all`）、`refresh-wda-cert.sh`（证书重签）。
- **免费 / 付费签名双模式（一等支持）**：新增 `_signing.sh` 共享解析器，`build-wda.sh` / `refresh-wda-cert.sh` / `install-wda-daemon.sh` / `setup-ios.sh` 统一按环境自动判定 —— **FREE**（Xcode Apple ID 账号，7 天证书，手动续期）vs **PAID**（`WDA_ASC_KEY_PATH`/`KEY_ID`/`ISSUER_ID` → App Store Connect API key headless 签名，1 年证书，自动续期）。`build-wda.sh` 现支持付费 headless 路径（`-authenticationKey*` + `WDA_TEAM_ID` 覆盖，付费首次无证书也能签）；`setup-ios.sh` 引导按模式分流。`docs/platforms/ios.md` 新增「付费账号接入」清单。
- **WDA 证书续期（诚实结论）**：免费 Apple ID **无法自动续期** 7 天证书（实测：mint profile 需账号，账号随重启掉出 `No Accounts`，重新加账号要过 2FA，任何自动化含 GUI 都过不了）→ 免费只能手动重建。`install-wda-daemon.sh` 仅在配置了 **App Store Connect API key**（`WDA_ASC_KEY_PATH`/`KEY_ID`/`ISSUER_ID`，付费）时才装 cert-refresh LaunchAgent（每 ~5 天 headless 重签）；免费不装失败定时器、改为引导。脚本兼容 macOS bash 3.2。
- `setup-ios.sh` step [6] 设备引导新增 daemon 化选项（推荐路径）；`docs/platforms/ios.md` 新增「WDA 保活：daemon 化」节。

### 真机验证（iPadOS 26 / iOS 18，2026-05-21）

- **`dvt xcuitest` 路线证伪**：pymobiledevice3 9.12.3 在 iPadOS 26 上 `dvt xcuitest` 启动 WDA 稳定 `Connection terminated abruptly`（已排除锁屏 / 残留 runner / tunnel 层 —— `dvt proclist`/`dvt launch` 普通 app 都通）。这是 pymobiledevice3 DVT-based xcuitest 在 iOS 17+ 的已知缺陷。
- **go-ios `runwda` 路线验证通过**：经现有 tunnel（`--address/--rsd-port`）授权 testmanagerd 会话 → WDA 上线 `state:success` → ios-device MCP `take_screenshot` 端到端成功。daemon 选用此路径。
- 设计文档 `docs/internal/design/2026-05-20-ios-onboarding-optimization.md` 记录完整可行性验证与最终方案。

## [0.8.1-alpha] - 2026-05-20

### 修复

- **iOS `push_file_to_app` / `pull_file_from_app` 真实现**：v0.8.0 的实现用了不存在的 `pymobiledevice3 apps afc push/pull` CLI 子命令（pmd 9.x 的 afc 是交互式 shell，多设备时还弹 device chooser，无法非交互调用）。改用 Python `house_arrest` API：`create_using_usbmux` → `HouseArrestService(documents_only=)` → `send_command(bundle_id)` → `push/pull`。afc 方法在不同 pmd 版本是 sync/async 混合，用 `_aw()` 只 await coroutine；整个流程跑在 `asyncio.run` 新 loop（FastMCP sync handler 在 worker 线程，无运行中 loop，安全）。
- **新增 `documents_only` 参数**：True 用于 UIFileSharingEnabled app（路径相对 Documents），False 用于 dev-signed app（路径相对 container 根，如 `Documents/foo.txt`）。无法 vend 的 app 返回清晰错误 + hint（InstallationLookupFailed）。
- iPad 真机验证：push host→app→pull host roundtrip md5 一致。

## [0.8.0-alpha] - 2026-05-20

### 新增

- **iOS / iPadOS 设备桥接（第 4 个平台，`ios-device`，端口 8769）**：macOS host 上通过 WebDriverAgent (UI 操作) + pymobiledevice3 (设备发现/安装/信息) 驱动 iPhone / iPad。架构 mirror v0.7.x android-device：单 MCP 入口 + per-device 路由 + 别名映射 (`apple-{ProductType}`) + per-device holder + FastMCP `instructions=` + `iosfleet://devices` resource。
- **26 个工具**：list_devices / set_default_device / get_default_device / acquire_ios / release_ios / get_ios_status / get_screen_size / take_screenshot / tap / swipe / long_press / press_button / type_text / dump_ui_hierarchy / find_elements / tap_element / current_app / list_apps / install_ipa / uninstall_app / start_app / terminate_app / activate_app / push_file_to_app / pull_file_from_app / device_info。
- **新模块**：`platforms/ios/server/_ios_devices.py`（pymobiledevice3 CLI 设备发现）、`_wda_client.py`（WDA HTTP client + USB-tunnel forwarder）、`ios_device_mcp.py`（主 server）；复用 `_aliases.py` / `_device_state.py`（slug 规则扩展处理 ProductType 的逗号）。
- **部署**：`platforms/ios/scripts/setup-ios.sh`（launchd `cc.metahub.ios-device` + brew python@3.12 venv）+ `_launch-ios.sh`（restart loop）+ `cli/src/fleet/installers/_ios.py`（smoke tests）+ `MacosIosBridge` installer。
- **文档**：`docs/platforms/ios.md` 完整真机部署关卡（完整 Xcode / Developer Mode / 屏幕使用时间限制 / 信任开发者证书 / Enable UI Automation + 重启 / 解锁状态）；`platforms/ios/skills/using-ios/SKILL.md`。

### 真机验证

- iPad15,7（iPad A16，iPadOS 26.2.1）真机验证 17 个工具：list_devices / get_screen_size / current_app / device_info / take_screenshot / start_app / find_elements / tap_element / tap / type_text / list_apps / press_button / swipe / long_press / dump_ui_hierarchy / acquire / release / status 全链路通过。

### 已知限制

- **WDA 保活**：WebDriverAgent 需要 Xcode `xcodebuild test` 保持运行；免费 Apple ID 证书 7 天过期需重 build。setup-ios.sh 只管 ios-device server 的 launchd，不管 WDA（daemon 化 WDA 留 followup）。
- **adb_shell 无 iOS 等价物**（沙盒）；文件传输限 `UIFileSharingEnabled` 的 app。
- **macOS 系统 Python 3.9.6 无法运行**（fastmcp 要 3.10+），必须 brew python@3.12。
- **多设备并发** 待 iPhone + iPad 同时接入验证（架构同 Android multi-device，代码已就绪）。
- **iOS 12 及更老** untested（WDA 老 fork 环境难凑齐）。

## [0.7.5-alpha] - 2026-05-19

### 修复

- **诊断字段透传到 client**：v0.7.4 的 `_adb_run` 在超时时返回 `timed_out: true / requested_timeout / effective_timeout / hint` 字段，但 user-facing tools (`adb_shell` / `install_apk` / `uninstall_app` / `push_file` / `pull_file` / `tap` / `swipe` / `long_press` / `press_key` / `type_text` / `list_packages` / `get_screen_size` / `kill_app` / `current_app`) 自己构造 return dict 时把这些 strip 掉了，诊断信息只留在 stderr 字符串里。本次加 `_diag(r)` helper，14 处 fail-return 加 `**_diag(r)` spread，让 client 直接拿到结构化 `timed_out: bool` flag + 完整 timeout 上下文，无需 parse 字符串。真机验证 v0.7.4 真机回归时发现的尾巴。

## [0.7.4-alpha] - 2026-05-19

### 修复

- **Android `_adb_run` internal helper 也 clamp 25s**：v0.7.2 只 cap 了 user-facing `adb_shell` tool；本次把 `_adb_run` 内部 subprocess timeout 也 hard cap 到 `_FASTMCP_DEADLINE_SAFE_SECONDS = 25`。这影响所有 internal long-path：`install_apk` (caller 传 120s)、`uninstall_app` (30s)、`push_file` / `pull_file` (300s) —— 现在它们的 subprocess 最长 25s，避免触发 fastmcp [#823](https://github.com/jlowin/fastmcp/issues/823) session crash。
- **Timeout 返回 shape 透明化**：超时返回 dict 新增 `timed_out: true`, `requested_timeout`, `effective_timeout`, `hint` 字段。caller 不需要 parse stderr 字符串就能判断是否超时 + 看到 caller 请求的原 timeout 与实际生效值差异。
- **4 个 long-path tool 的 docstring 加大文件/慢操作警告**：`install_apk` / `uninstall_app` / `push_file` / `pull_file` 都明写 25s 上限 + 触发条件 + workaround。

### 已知限制（继续追踪）

- 大 APK install (>50MB USB / >20MB wireless) 仍会超时 → 需要 async start_process 模式重构（backlog）。本次只是确保超时**不让 session crash** + caller 拿到清晰诊断信息。

## [0.7.3-alpha] - 2026-05-19

### 文档

- **Android server 管理章节**（`docs/platforms/android.md`）：按 host OS 分（Windows Task Scheduler / macOS launchd / Linux systemd）的启停 / 重启 / 看 log 命令清单。
- **手动启动陷阱警告**：明确写出"**不要用 `Start-Process -RedirectStandardOutput` 手动起 server**"——该 cmdlet 让父 PowerShell 持有 child 的 stdio handle，使 `mcp__win-device__run_powershell` 等远程调用看似 hang。`setup-android.ps1` 最后输出的 Service control 提示也加了同条警告。

### 改进

- **三平台 server `__main__` 入口加 stdio line-buffering**：`sys.stdout.reconfigure(line_buffering=True)` + 同样处理 stderr。修复 `python server.py > log 2>&1` 模式下 log 不实时刷新到 server 退出才能看（block buffering 默认行为）。

## [0.7.2-alpha] - 2026-05-19

### 修复

- **transport 稳定性**：三平台 server 的长 tool（`run_powershell` / `run_zsh` / `run_applescript` / `adb_shell`）timeout 硬上限 clamp 到 **25s**，避开 fastmcp/mcp streamable-http transport 的 ~30s 死线（[jlowin/fastmcp#823](https://github.com/jlowin/fastmcp/issues/823) + [#508](https://github.com/jlowin/fastmcp/issues/508)，上游未修）。超过死线会触发 task-cancel-vs-respond race → 整个 MCP session crashed → 后续所有请求报 "Session not found"。本次 mitigation 在 wrapper 层 catch `TimeoutExpired` 优雅返回 partial output + `timed_out: true` + `hint`。
- **长任务迁移指引**：超过 25s 的命令请改用 `start_process` 后台启动 + `read_process_output` 轮询模式（毫秒返回 PID，不卡 transport）。Android 的 `install_apk` 等内部长操作暂保留 long timeout 路径，留 followup 重构。

### Client 侧建议（独立配置）

Claude Code 端默认 MCP tool call timeout 60s，但 fastmcp/mcp 内部死线更早。建议在 `~/.claude/settings.json` `env` 段显式调高 `MCP_TOOL_TIMEOUT`：

```json
{
  "env": {
    "MCP_TIMEOUT": "60000",
    "MCP_TOOL_TIMEOUT": "120000"
  }
}
```

server 端 clamp 已经保证不会触发 fastmcp 死线，client 调高是双保险（避免 client cancel 触发同 race）。

## [0.7.1-alpha] - 2026-05-19

### 修复

- **依赖**：`fastmcp` 加上限 `!=3.3.1`。PyPI 上的 `fastmcp==3.3.1` 是空 namespace 包（`dir(fastmcp)` 无 `Context` / `FastMCP`），server 启动时直接 `ImportError`。3.2.4 工作正常。本次修复防止 pip 解析器选中该 broken release。

## [0.7.0-alpha] - 2026-05-18

### 新增

- **多设备 Android 支持**：单 MCP 入口，所有工具新增 `device` 参数（serial 或别名），支持同一主机挂多台手机同时操作。
- **设备别名映射**：`~/.agent-fleet/android-aliases.json`，wizard 自动推断（格式：`{brand}-{slug(model)}`，重名按 serial 字典序追加 `-1/-2`，fallback 为 `phone-N`）。可单独运行 `python3 platforms/android/scripts/setup_aliases.py` 生成。
- **新工具 `set_default_device` / `get_default_device`**：MCP 会话级 sticky 默认，设置后同一会话内所有工具可省略 `device` 参数。
- **FastMCP `instructions=`**：MCP initialize 握手时自动注入已连接手机的摘要列表，Claude 无需调工具即可得知当前设备情况。
- **MCP resource `androidfleet://devices`**：实时设备 JSON 快照，随时可读。
- **per-device holder 锁**：`acquire_android` / `release_android` / `get_android_status` 全部按 `device` 维度隔离，支持多个 Claude 会话同时操作不同手机。

### 变更

- **`list_devices` 返回 shape 更新**：移除 `state` 字段；新增 `alias` / `brand` / `model` / `in_use` / `holder` / `default_for_session` 字段。
- **工具数 23 → 25**（新增 `set_default_device` / `get_default_device`）。
- **Roadmap 重排**：iOS bridge 由 `0.7.0` 顺延到 `0.8.0`，Cross-device coordination 由 `0.8.0` 顺延到 `0.9.0`。

### 迁移说明

- **单机用户无需修改任何配置**：未传 `device` 且只插 1 部手机时，行为与 v0.6.x 完全兼容，自动路由。
- **多机用户**：首次跑 `agent-fleet setup` / `setup_aliases.py` 生成别名配置；或手动写 `~/.agent-fleet/android-aliases.json`。

### 向后兼容

- 所有 `@mcp.tool` 的现有参数顺序保持不变；`device` / `ctx` 均为新增的尾部默认参数，不影响现有调用。

### 已知限制

- server 启动时一次性查 adb 以生成 `instructions=`，若 adb hang 可能导致最多 10s 冷启动延迟。
- hot-plug 通知（`notifications/resources/list_changed`）暂未实现；新插入/拔出的设备依赖 `list_devices()` 主动刷新。

## [0.6.15-alpha] - 2026-05-14

### Changed

- **No tool-surface, port, or API changes — this release is cleanup only.**
- **Stale SSE-transport references swept (PR-1).** Remaining `/sse` URL and `"type": "sse"` fragments in docs, scripts, and skills replaced with `/mcp` / `"type": "http"` (streamable-http). Stale version-planning notes in `docs/roadmap.md` and `docs/install-pattern.md` removed.
- **Open-source readiness (PR-2).** "Private, not open for contribution" language removed from README / CONTRIBUTING. Added `SECURITY.md`, `CODE_OF_CONDUCT.md`, and `.github/` issue + PR templates. `cli/README.md` fleshed out. Two hardcoded Chinese UI strings in `cli/src/fleet/cli.py` replaced with English.
- **`cli/` dead-code removal + bug fixes (PR-3).** Duplicate import in `installers/__init__.py` fixed. Dead code removed: `detect_existing_deployment`, `GuidanceStep.verify_fn` / `verify_label`, `SmokeResult.note`, a redundant override. Shared Android smoke-test helpers moved to `installers/_android.py`. `preflight()` wired up so missing-prerequisite detection actually runs. `[project.urls]` added to `cli/pyproject.toml`.
- **Structural alignment (PR-4 part 1).** Android setup guide moved from an inline wizard YAML to `docs/platforms/android.md`. Internal dev-process docs (`docs/superpowers/`, `docs/design/`) relocated to `docs/internal/`. `platforms/android/server/android_mcp.py` renamed to `android_device_mcp.py` (consistent with win/mac naming).
- **Metadata & dependency cleanup (PR-4 part 2).**
  - `platforms/windows/server/requirements.txt`: dropped leftover pre-v0.2 `mcp-proxy` dependency (not imported by `win_device_mcp.py`, not in `pyproject.toml`).
  - `platforms/macos/server/pyproject.toml`: added `pyobjc-framework-ApplicationServices>=10.0` that was only declared in `requirements.txt`.
  - `platforms/android/server/pyproject.toml`: aligned metadata (`authors`, `keywords`, `classifiers`, `[project.urls]`) with win/mac server pyproject template; dropped incorrect Windows-only OS classifier (the host can be Win/Mac/Linux); removed unneeded `wheel` from `build-system.requires`.
  - `platforms/android/skills/using-android/SKILL.md`: corrected stale tool count (20 → 23); removed "planned for v0.4.1" notes for `dump_ui_hierarchy`, `find_elements`, and `tap_element`, which are already implemented and shipping.
  - `platforms/macos/README.md`: removed hardcoded `v0.3.0` version pin from the opening line.
  - `docs/architecture.md`: repo-layout diagram now shows all three platforms under `platforms/` and all three platform guides under `docs/platforms/`.
- **Version bump 0.6.14 → 0.6.15** across `cli/pyproject.toml`, `cli/src/fleet/__init__.py`, `cli/tests/test_smoke.py`, `install.sh`, `install.ps1`, and `README.md` badge / uvx command refs. All three platform server `pyproject.toml` versions aligned to `0.6.15a1`.

## [0.6.14-alpha] - 2026-05-14

### Fixed

- **`agent-fleet setup` wizard no longer hangs or garbles prompts when a platform setup script needs user input.** The wizard captures setup-script output through a pipe (`subprocess.Popen(stdout=PIPE)`) to render it as progress. But a script's `Read-Host`/`read` prompt has no trailing newline, so it stalls in the pipe buffer — and the script shares the wizard's stdin, so typed input went nowhere. On Windows this fully broke `setup-android.ps1`'s "reuse config?" and "ADB mode [1/2/3]" prompts. Fix: all interactive choices are now collected **up front by the wizard** via questionary (same arrow-key UI as role selection) and handed to the scripts as env vars (`ATB_WIZARD_MANAGED`, `ATB_ANDROID_MODE`, `ATB_ANDROID_REUSE_CONFIG`). The setup scripts are env-var driven under the wizard and fall back to their original interactive prompts when run standalone. `setup-windows.ps1`'s lone `Read-Host "Press Enter"` (Tailscale-not-installed branch) now exits cleanly under the wizard instead of hanging.

## [0.6.13-alpha] - 2026-05-14

### Fixed

- **Setup scripts now report the Tailscale MagicDNS name, not the OS computer name.** All five setup scripts (`setup-android.{ps1,sh}`, `setup-android-linux.sh`, `setup-windows.ps1`, `setup-macos.sh`) read `tailscale status --json`'s `Self.HostName` field for the "send this to the agent operator" connection info. `Self.HostName` is the **OS computer name** (e.g. Windows `WIN-20251004GXJ`), which goes stale the moment a device is renamed in the Tailscale admin console — the rename only updates `Self.DNSName`. A user who renamed their device to `win-personal-qjl` in the admin console still got `WIN-20251004GXJ` printed, and that name isn't resolvable by other tailnet nodes via MagicDNS. The scripts now derive the hostname from the first label of `Self.DNSName` (the authoritative MagicDNS name), so the printed `agent URL` and `install-agent-side.py --hostname` command are correct even after an admin-console rename. `TS_HOST` is display-only — no service binding or config file was affected, so existing deployments only need to re-run setup if they want the corrected connection-info output.

## [0.6.12-alpha] - 2026-05-14

### Fixed

- **`interact_with_process` no longer raises a raw `OSError [Errno 22]` (Windows) or `BrokenPipeError` (macOS) when sending input to a process that has already exited.** Previously the tool only checked `proc.stdin.closed` before writing, but Python's file-object `.closed` flag does NOT update when the kernel PIPE handle is released as the child dies — so the check passed and the underlying `write()` failed with a confusing OS-level error. `proc.poll()` is now used as the authoritative aliveness check, and the tool returns a friendly `"process pid N already exited (exit_code=C); cannot send input"` instead. Applies to both `win-device` and `mac-device` MCP servers.

### Changed

- **Internal rename cleanup completed.** The GitHub repo was renamed `agent-test-bench` → `agent-fleet` during the v0.6.0 era (see [`docs/internal/design/2026-05-11-agent-fleet-cli.md`](docs/internal/design/2026-05-11-agent-fleet-cli.md)), but internal code, setup scripts, `pyproject.toml` package names, SKILL.md descriptions, and top-level docs (README / CONTRIBUTING / CHANGELOG release-links) all still referenced the old name. v0.6.12 finishes the migration: `pyproject.toml` package names are now `agent-fleet-{windows,macos,android}` (down from `agent-test-bench-*`), platform setup scripts reference the new name in banners and `setup-android-linux.sh`'s systemd unit Description, the no-legacy-naming regression test now blocks `agent-test-bench` from creeping back in, and the `docs/platforms/{windows,macos}.md` guides now lead with a 3-step "quick install" TL;DR pointing at the one-shot setup scripts. Historical design / plan documents (`docs/internal/design/`, `docs/internal/plans/`) intentionally retain the old name for record-keeping. **No service identifiers, ports, or APIs changed — the rename is cosmetic.** Existing deployments do not need to re-run setup for the rename portion, but **do** need to pull v0.6.12 and re-run setup to pick up the `interact_with_process` fix above (the bug is harmless until you try to send stdin to a dead process, but the fix should ship anyway).

## [0.6.11-alpha] - 2026-05-12

### Changed
Internal file rename for naming consistency with the v0.6.0 role-ID rename. The role-IDs were renamed `macbox-gui` → `mac-device`, `winpc-gui` → `win-device`, `android-gui` → `android-device` in v0.6.0, but the Python entry-point files and log filenames still carried `-gui`. v0.6.11 cleans up the remaining inconsistency:

- `platforms/windows/server/windows_gui_mcp.py` → `win_device_mcp.py`
- `platforms/macos/server/macos_gui_mcp.py` → `mac_device_mcp.py`
- Log filenames: `windows-gui.log` → `win-device.log`, `macos-gui.log` → `mac-device.log`
- `pyproject.toml` `py-modules`, all launcher scripts, setup scripts, docs, and skills updated accordingly.

`test_no_legacy_naming.py` blocklist extended with the new legacy strings (`macos_gui_mcp`, `windows_gui_mcp`, `macos-gui.log`, `windows-gui.log`). Legacy-cleanup migration blocks (which intentionally reference the old names) are marked with the keyword `legacy` on the same line so the regression test skips them.

No tool surface or service-port changes — this is purely internal naming hygiene. Existing deployments upgrade by re-running setup (which now kills orphaned `macos_gui_mcp.py` from before the rename, in addition to the standard `mac_device_mcp.py` cleanup).

## [0.6.10-alpha] - 2026-05-12

### Fixed
v0.6.9 was wrong: Register-ScheduledTask **does** need admin on Windows, AND legacy MCP-WindowsGui / MCP-AndroidGui tasks from pre-v0.6.x admin-installs can only be unregistered with admin. Symptom of running v0.6.9 non-admin:

```
Unregister-ScheduledTask : 拒绝访问 (legacy MCP-WindowsGui)
  removed legacy task MCP-WindowsGui   ← MISLEADING — echo fired despite error
Register-ScheduledTask : Access is denied. (new MCP-WinDevice)
  ok MCP-WinDevice registered          ← MISLEADING
Start-ScheduledTask : The system cannot find the file specified.  ← actual evidence
```

Why the misleading "ok" echoes: CIM cmdlets (Get/Set/New/Register/Unregister-ScheduledTask) emit **non-terminating** errors by default that don't trip `$ErrorActionPreference = "Stop"`. Need explicit `-ErrorAction Stop` AND try-catch wrappers to know what really happened.

### Solution
1. **install.ps1 detects admin upfront**, prints clear error + "right-click PowerShell → Run as administrator" instructions if not. Aborts before doing anything destructive.
2. **setup-windows.ps1 + setup-android.ps1 wrap Register/Unregister-ScheduledTask in try-catch with `-ErrorAction Stop`** so failures bubble up. The "removed legacy task" and "ok registered" echoes now only fire on actual success.
3. **README.md / docs** updated to say "Windows needs admin PowerShell" (the prior v0.6.9-era doc claim of "no admin needed" was wrong).

### Migration
- Run PowerShell as admin (right-click → Run as administrator)
- Re-run `irm ... | iex` install command. v0.6.10's admin check passes; setup scripts proceed.

---

## [0.6.9-alpha] - 2026-05-12

### Fixed

Three Windows-specific issues found in the first successful Win11 install attempt of v0.6.8:

1. **`#Requires -RunAsAdministrator` forced both setup-windows.ps1 and setup-android.ps1 to demand elevation**, blocking the normal install.ps1 flow with `ScriptRequiresElevation`. The directive was added defensively but isn't actually needed — task scheduler registration (user-scope) works without admin; only `New-NetFirewallRule` requires admin. Removed the `#Requires` and wrapped the firewall calls in `try { ... } catch { ... WARN ... }` so non-admin runs succeed with a clear graceful-degradation message.

2. **PowerShell error messages rendered as `��� ��� ���` mojibake** in the wizard. PS 5.1 writes stdout in the system code page (GBK on Chinese Windows), but v0.6.7's UTF-8 + errors=replace decoder treated GBK bytes as UTF-8 and substituted U+FFFD. Fixed by wrapping the PS invocation: `powershell.exe -Command "[Console]::OutputEncoding=[Encoding]::UTF8; $OutputEncoding=[Encoding]::UTF8; & 'script.ps1'"` — forces PS itself to emit UTF-8 before our decoder reads it.

3. **Firewall rule error swallowed install attempt**: `New-NetFirewallRule` raised an error that propagated to `$ErrorActionPreference = "Stop"`, killing the install mid-way. Now wrapped + explicit `-ErrorAction Stop` inside the try-catch, with `-ErrorAction SilentlyContinue` removed where it was masking real failures.

### Migration
No breaking changes. Re-run `agent-fleet setup`.

---

## [0.6.8-alpha] - 2026-05-12

### Fixed
- **install.ps1 crashed with `× Failed to resolve --with requirement / Git operation failed`** on Windows after install.ps1 successfully did `git clone` + `git checkout v0.6.7-alpha` via the system `git` CLI. uv's bundled git client (libgit2-backed) failed to fetch the **same tag** that system git just succeeded with — likely a TLS/cert/proxy difference between uv's bundled libgit2 and the system git. Symptom occurred on the user's first Win11 install attempt and was deterministic.

### Solution
Switched `install.sh` and `install.ps1` from `uvx --from "git+https://...@<tag>#subdirectory=cli"` to `uvx --from "$(pwd)/cli"` (local path). Since steps 2-3 already clone + cd into the repo, the local-path approach:
1. Bypasses uv's git client entirely — no more libgit2 failures.
2. Avoids a redundant second clone (uv was re-fetching the same repo we already had on disk).
3. Faster — no network round-trip after the initial system-git clone.

### Migration
No breaking changes. Re-run `agent-fleet setup` to pick up the new install.* scripts.

---

## [0.6.7-alpha] - 2026-05-12

### Fixed
- **Wizard crashed on Chinese Windows with `AttributeError: 'NoneType' object has no attribute 'strip'`** when invoking `tailscale status --json`. Root cause: `subprocess.run(..., text=True)` without an explicit `encoding` uses `locale.getpreferredencoding()`, which is **GBK** on Chinese Windows. Tailscale always emits UTF-8 JSON, so any tailnet that has a node with a CJK name (e.g. "Yi的MacBook Pro"), TM/©/® symbols, or em-dashes blew up the subprocess reader thread with `UnicodeDecodeError`. The thread death set `r.stdout = None`, and the next line `r.stdout.strip()` raised the AttributeError.
- Same encoding bug also lurked in `installers/{macos,windows,linux}.py` — they invoke setup scripts via `subprocess.Popen(..., text=True)` to stream output into the wizard's rendering. Fixed all four sites.

### Solution
- `detect_tailscale` and all `subprocess.Popen` calls now pass `encoding="utf-8", errors="replace"` (drop the bare `text=True`). UTF-8 is the right interpretation for Tailscale JSON; `errors="replace"` keeps the reader thread alive on stray non-UTF-8 bytes from any other tool (PowerShell 5.1 in GBK code page, etc.) by inserting `�` instead of crashing.
- Defensive: short-circuit to `None` if `r.stdout` is None for any reason (was: `r.stdout.strip()` unconditionally).
- Added regression test in `test_detect.py`.

### Migration
No breaking changes. Re-run `agent-fleet setup` (it'll fetch v0.6.7 cli via uvx and proceed past the crash).

---

## [0.6.6-alpha] - 2026-05-12

### Fixed
- **macOS legacy plist (`cc.metahub.macbox-gui` / `cc.metahub.android-gui`) not cleaned up by setup script after the v0.6.0 rename.** During end-to-end testing, the legacy plist still had `KeepAlive=true` from a pre-v0.6.0 install. It kept respawning the python server and squatting port 8767 (or 8768), so the newly-installed `cc.metahub.mac-device` plist's server couldn't bind. Symptom: even after `launchctl unload + load` cycles + service-restart shenanigans, Claude Code only saw 31 mac-device tools (the running old server) instead of 34 (the new server with v0.6.1+ UI tools). Took multiple manual interventions to get clean.
- **Fix in `setup-macos.sh` + `setup-android.sh` (mac host branch)**: explicit migration block before the new plist's `launchctl bootout` — detect either the legacy plist file OR the legacy label loaded in launchd, then `bootout` + `unload` + `rm -f`. Also `pkill -f "macos_gui_mcp\.py"` / `pkill -f "android_mcp\.py"` AFTER bootout to catch orphaned manually-launched python processes that escaped launchd management.

### Bonus
- Updated the stale `launchctl list | grep macbox` hint in setup-macos.sh's final output to `launchctl list | grep mac-device`.

### Migration
- Re-run `agent-fleet setup` on macOS — it'll auto-clean the legacy plist and any orphan processes on this single run. No manual intervention needed.

---

## [0.6.5-alpha] - 2026-05-12

### Fixed
Both v0.6.1-alpha UI element tools had a silent-failure bug — they returned successfully but with degraded data, so the failure only surfaced when callers tried to use the missing fields.

- **macOS `list_ui_elements` / `find_ui_element` / `click_ui_element` returned `position`/`size`/`center` as `null`**, making them unusable for clicking. Root cause: pyobjc's `AXValueGetValue` signature is `(ok, value) = AXValueGetValue(ref, type, None)` (returns a 2-tuple), not C-style `bool AXValueGetValue(ref, type, outPtr)`. We were passing a `CGPoint()` instance as the third arg, which raised `ValueError: 'valuePtr' should be None` silently inside the try block and left coordinates at `None`. Fixed.
- **Android `dump_ui_hierarchy` failed with `XML parse failed: no element found at line 1, column 0`**, even though `uiautomator dump` wrote a valid 36KB XML on the device. Root cause: `_adb_run(capture_bytes=True)` puts the raw bytes in `r["stdout_bytes"]` and sets `r["stdout"]` to `""`. We were reading `r["stdout"]`, which was always empty. Fixed to read `r["stdout_bytes"]` and surface a clearer "empty UI dump" error if it ever is empty.

### Migration
No breaking changes. Re-run `agent-fleet setup` or `git pull` in `~/agent-fleet` then restart the launchd / Task Scheduler / systemd services.

---

## [0.6.4-alpha] - 2026-05-12

### Fixed
- **Smoke runner connected via Tailscale MagicDNS hostname (`test-macpro-12`) instead of localhost**, so every test failed with `MCP connection failed: ExceptionGroup: ...`. The wizard runs on the same host that just deployed the servers, and a Tailscale node often can't resolve its own MagicDNS name from itself (depends on DNS search-domain config). Switched to `127.0.0.1` like `verify` already does. The agent-facing Tailscale URL is still shown in the final "Endpoints" panel.
- **`ExceptionGroup` swallowed the real error**: when the underlying connection failure happened inside an `asyncio.TaskGroup`, Python 3.11+ wraps it as `ExceptionGroup("unhandled errors in a TaskGroup (1 sub-exception)")` — the actual `ConnectionRefusedError` / `gaierror` was invisible. Added `_unwrap_exception()` that walks `.exceptions` to the innermost cause.
- **N copies of the same connection error + N misleading per-test hints**: when the server is unreachable, every test was reporting its own (irrelevant) hint. Collapsed to a single "MCP server unreachable" row with a role-specific diagnostic command (`launchctl list | grep cc.metahub.mac-device`, etc.).

### Migration
No breaking changes. Re-run `agent-fleet setup` to pick up the smoke fix.

---

## [0.6.3-alpha] - 2026-05-12

### Fixed
- **Smoke runner crashed with `AttributeError: 'ServerRole' object has no attribute 'smoke_tests'`** (regression from 0.6.2-alpha). `_run_install` was only returning `ServerRole` dataclasses (snippet-rendering shape) — the smoke runner needed the original installer instances to call `installer.smoke_tests()`. Now `_run_install` returns `(server_roles, installer_instances)` so both rendering and smoke share the same source of truth. Regression test added in `test_smoke_module.py`.

### Changed
- **Android setup guidance moved out of the wizard into [`docs/platforms/android.md`](docs/platforms/android.md).** The 3 in-wizard YAMLs previously listed 7+ OEM variants for each step (华为 / 小米 / Samsung / OPPO / vivo / Pixel / OnePlus / ...) — too much inline text for a CLI flow. They now show a 3-line summary + a link to the dedicated doc, which contains the full OEM-by-OEM unlock table, USB debugging quirks per ROM, and a side-by-side comparison of USB / Wireless / Hybrid connection methods with anchor-targeted sections (#step-1, #step-2, #step-3).

### Migration
No breaking changes. Re-run `agent-fleet setup` to pick up the smoke fix and the simplified guidance prose.

---

## [0.6.2-alpha] - 2026-05-12

### Added
- **Post-install smoke tests** (`cli/src/fleet/smoke.py`): after each role installs, the wizard automatically connects to its MCP server over Tailscale and invokes 4–5 representative tools (e.g. `take_screenshot`, `run_zsh`, `list_devices`).  A pass/fail/skip table surfaces TCC permission issues, missing device hardware, or venv dependency gaps **before** the user restarts their agent host — no more "wizard finished green, then half the tools fail at first use."
  - mac-device: `get_mac_status`, `run_zsh`, `get_screen_size`, `take_screenshot` (Screen Recording TCC), `run_applescript` (Automation TCC)
  - win-device: `get_winpc_status`, `run_powershell`, `get_screen_size`, `take_screenshot`, `list_windows`
  - android-device: `get_android_status`, `list_devices`, `get_screen_size`, `take_screenshot`, `current_app`
  - Each failure includes an actionable `hint_on_failure` line pointing the user at the specific fix (e.g. which Settings pane to open, which task scheduler entry to verify).
- `BaseInstaller.smoke_tests()` API for installers to declare their own smoke set.

### Fixed
- **setup-android prompt buffering**: the wizard's line-buffered subprocess pipe was eating `read -r -p "..."` prompts that lacked a trailing newline, leaving the user staring at a blank wizard. All 4 interactive `read -p` sites in `platforms/android/scripts/setup-android.{sh,linux.sh}` now use explicit `echo \"...\"` + `read` so the prompt flushes immediately.
- **Mode-switch prompt clarity**: the `reuse it? [Y/n]` prompt didn't make clear that pressing `n` leads to the USB/Wireless/Hybrid mode selection. Reworded to: *"Press Enter to keep this config, or 'n' to switch ADB mode (USB/Wireless/Hybrid)"*.

### Migration
No breaking changes. Re-run `agent-fleet setup` to refresh the installed wizard and pick up the new smoke test step.

---

## [0.6.1-alpha] - 2026-05-12

### Added
- **Android UI element introspection** (`platforms/android/server/android_mcp.py`):
  - `dump_ui_hierarchy()` — runs `uiautomator dump`, parses XML, returns flat element list with `bounds` / `center` / `text` / `resource_id` / `content_desc` / `clickable` / etc.
  - `find_elements(text=, resource_id=, content_desc=, class_name=, clickable_only=)` — substring-match filter across all elements, AND logic.
  - `tap_element(...)` — find-and-tap convenience; taps the center of the matched element instead of hardcoded pixel coordinates.
- **macOS UI element introspection** (`platforms/macos/server/macos_gui_mcp.py`) via pyobjc-framework-ApplicationServices:
  - `list_ui_elements(app=, max_depth=)` — walks an app's accessibility tree, returns elements with `role` / `title` / `label` / `position` / `size` / `center`.
  - `find_ui_element(app=, title=, role=, label=)` — filter by AX attributes.
  - `click_ui_element(...)` — find-and-click convenience.

### Why
v0.6.0-alpha end-to-end test surfaced that visual pixel estimation from screenshots is brittle: the agent missed the camera shutter button on the first try (tapped the "拍照" mode tab instead). Element-driven automation lets the agent look up controls by semantic attributes (text / role / resource-id), insulating from layout changes and screen resolution differences.

### Migration
No breaking changes. New tools added; existing tools unchanged. To get the new tools, re-run `agent-fleet setup` on each device (re-installs the venv with refreshed `requirements.txt` for the new pyobjc dep, then restarts the MCP server).

---

## [0.6.0-alpha] - 2026-05-12

### Breaking
- Renamed MCP role IDs: `macbox-gui` → `mac-device`, `winpc-gui` → `win-device`, `android-gui` → `android-device`. Existing users must update `~/.claude.json` `mcpServers` keys, redo the `agent-fleet setup` wizard, and let the new setup scripts clean up old launchd / Task Scheduler / systemd entries.
- Renamed service identifiers: launchd label `cc.metahub.macbox-gui` → `cc.metahub.mac-device`; Windows Task Scheduler `MCP-WindowsGui` → `MCP-WinDevice`, `MCP-AndroidGui` → `MCP-AndroidDevice`; Linux systemd unit `atb-android-gui.service` → `agent-fleet-android-device.service`.
- Renamed skills: `using-macbox` → `using-mac`, `using-winpc` → `using-win`.

### Added
- macOS TCC permission primer: wizard auto-triggers Accessibility / Screen Recording / Automation dialogs so Python.app pre-appears in System Settings (just toggle the switch, no manual drag).

### Migration
Old setup scripts auto-clean their legacy services when re-run. To migrate manually:
- macOS: `launchctl unload ~/Library/LaunchAgents/cc.metahub.macbox-gui.plist 2>/dev/null; rm -f ~/Library/LaunchAgents/cc.metahub.macbox-gui.plist`
- Windows: `Unregister-ScheduledTask -TaskName MCP-WindowsGui -Confirm:$false; Unregister-ScheduledTask -TaskName MCP-AndroidGui -Confirm:$false`
- Linux: `systemctl --user stop atb-android-gui.service; systemctl --user disable atb-android-gui.service; rm -f ~/.config/systemd/user/atb-android-gui.service; systemctl --user daemon-reload`

## [0.2.0-alpha – 0.6.0-alpha]

### Changed
- **🚨 BREAKING (transport): SSE → streamable-http for all 3 platforms.** Long-task `-32602` bug rooted out. SSE was a long-lived event channel; under Tailscale DERP relay or NAT middle-boxes, idle keepalive timed out at ~60-120s. When that happened the client kept its old `session_id` (the MCP SSE protocol has no auto-reconnect at the SDK level), the server didn't know it, and every subsequent call returned `-32602` until `/exit` + reopen Claude Code. Documented as a known issue across 3 skills as "/exit + reopen" workaround. Now fixed at the root: server transports flipped from `transport="sse"` to `transport="http"` (FastMCP's `streamable-http` alias) and client URLs from `:port/sse` to `:port/mcp`. streamable-http uses per-request streams instead of a long-lived event channel, so a stale connection is just one bad request away from auto-reconnect, not a session-killer. **Migration steps for existing deploys**:
  1. Device hosts: `git pull` + restart service (Win Task Scheduler `MCP-WindowsGui` / `MCP-AndroidGui`; macOS `launchctl kickstart -k gui/$UID/cc.metahub.macbox-gui` / `cc.metahub.android-gui`). The new code binds the same port, just on `/mcp` path instead of `/sse`.
  2. Agent hosts: re-run `python3 scripts/install-agent-side.py --platform <name> --hostname <host>` for each. The installer now writes `"type": "http"` + `/mcp` URL; backs up `~/.claude.json` with timestamp before overwriting. Then `/exit` + reopen Claude Code.
- All examples (`platforms/<plat>/examples/claude-settings.json` × 3, top-level `examples/multi-platform-claude-settings.json`) and docs (`docs/agent-host-setup.md`, `docs/install-pattern.md`, the 3 skill `SKILL.md` files) updated to reflect the new transport. The 3 skills' `-32602` failure rows now point at "your client config is still on legacy SSE -- re-run install-agent-side.py" rather than the old `/exit + reopen` workaround. New anti-pattern entry in `docs/install-pattern.md` § 6: don't use SSE for long tasks.
- Diagnosed by an external agent during a live macbox-gui session that hit `-32602` after a long tool call; verified against FastMCP 3.2.4 source (`run_http_async` accepts `transport in {"http","sse","streamable-http"}`; default `streamable_http_path = "/mcp"`); confirmed Claude Code accepts `"type": "http"` (alias for `"streamable-http"`).

### Added
- **🆕 Android platform bridge (v0.4.0).** Single-device pure-ADB implementation. No uiautomator2 / scrcpy dependency in v0.4 -- avoided to keep first deploys working on locked-down OEM ROMs (Huawei HarmonyOS / MIUI etc.). Tools: 16 across 7 categories (state 3 / device 1 / screen 2 / touch 3 / keyboard 2 / app 6 / shell 1 / file 2). Works on either Windows (PowerShell setup script) or macOS (bash setup script, lands in v0.4.1) host. ADB connection mode (USB / Wireless Debugging / Hybrid) is operator's choice at install, persisted to `~/.atb-android/config.toml`; the server itself is mode-agnostic. First validation: Huawei P30 Pro VOG-AL00 (HarmonyOS 4.0 / EMUI 14, reports as Android 10 / SDK 29 -- meaning native Wireless Debugging is unavailable on this phone, USB or Hybrid only).
- `platforms/android/server/{android_mcp.py, requirements.txt, pyproject.toml}` (~600 lines server, deps: fastmcp + pillow + pydantic only).
- `platforms/android/scripts/setup-android.ps1` (Win11 host) + `_launch-android.ps1` -- 9-stage setup, idempotent, mirrors winpc-gui's Task Scheduler + restart-loop pattern. Asks ADB mode and writes `~/.atb-android/config.toml`.
- `platforms/android/scripts/setup-android.sh` (macOS host) + `_launch-android.sh` -- 8-stage symmetric setup using brew + launchd. Inherits all the macOS Tier-3 brew tolerance (ERR trap, dir-permission preflight, `|| true` on brew install) from setup-macos.sh. launchd plist invokes venv python directly (no bash hop). Per-launch `ATB_ANDROID_ADB` env var so the server doesn't have to re-resolve adb at startup. NOTE for macOS hosts: this server does NOT need Accessibility / Screen Recording / Automation grants (it doesn't capture anything on the Mac itself; only shells out to adb).
- `platforms/android/skills/using-android/SKILL.md` -- mental model (you drive server, server drives ADB, ADB drives phone), tap-not-click, app lifecycle pattern, multi-agent coord.
- `platforms/android/examples/claude-settings.json` mirrors the windows / macos pattern.
- `scripts/install-agent-side.py` PLATFORMS dict gains `android-gui`.
- `examples/multi-platform-claude-settings.json`: `_planned_android` is now real `android-gui`; legend updated.

### Added
- **🎯 Developer-facing baseline doc + one-command agent-side installer.** New repo-level entrypoints that let someone who just cloned the repo install the MCP server and skill correctly without reading 5 platform docs first:
  - `docs/install-pattern.md` (~200 lines): two roles, two install paths, directory contract, "add new platform in 8 steps" recipe, anti-patterns, recommended reading order.
  - `scripts/install-agent-side.py`: cross-platform Python script. `python3 scripts/install-agent-side.py --platform macbox-gui --hostname mac-test` does (1) timestamped backup of `~/.claude.json` (2) merges the SSE entry into `mcpServers` (3) symlinks `platforms/<dir>/skills/using-<name>` into `~/.claude/skills/`. Idempotent (re-run reports "ok already configured"). `--dry-run` previews without writing. Refuses to overwrite invalid JSON or non-symlink files at the skill destination.
  - README `快速开始` section now points new joiners at install-pattern.md FIRST.
  - `docs/agent-host-setup.md` § 3.4 documents the one-liner.
- **🆕 platforms/android/ skeleton (v0.4 placeholder).** Empty directories with `.gitkeep` files documenting what each will hold (server / scripts / skills / examples), plus a `README.md` describing the planned architecture, tool surface, and dev-loop. Mirrors windows/ and macos/ structure exactly so adding the real code is a port not a fresh design.

### Changed
- **Version-number cleanup across `README.md` and `docs/roadmap.md`.** Reality: Windows shipped v0.2 (consolidated), macOS shipped v0.3, Android moved to v0.4, iOS moved to v0.5, cross-device coord moved to v0.6. README ASCII diagram, status table, "快速开始" role table, and 目录布局 all reflect this. Roadmap gets dated v0.2/v0.3 sections describing what actually shipped (not the original guesses) and bumps Android/iOS/cross-device version numbers down by one.
- **`docs/agent-host-setup.md` § 3.3 generalized from Windows-only to multi-platform.** Now lists acquire/release/status tools for every released platform in a table, not just `acquire_winpc`.
- **`platforms/macos/examples/`** is no longer empty -- mirrors windows/examples by adding `claude-settings.json` with the macbox-gui SSE entry skeleton.

### Fixed
- **macOS docs explicitly recommend Full Disk Access + warn against granting Photos / Calendar / Reminders / Contacts.** First-deploy session triggered 5 separate per-folder prompts (照片 / 桌面 / 日历 / 提醒事项 / 文稿) the moment a probe ran `find ~ -maxdepth 3`, which surprised the operator. Two doc updates: (1) `docs/platforms/macos.md` § 4.3.8 introduces the capability-vs-user-data permission split and recommends one-shot Full Disk Access for Python.app to cover Documents / Desktop / Downloads / all of ~/Library; warns operators to refuse Photos / Calendar / Reminders / Contacts since agent-driven testing doesn't need them. (2) `using-macbox` skill gets a "Avoid scanning protected user-data directories" subsection that tells agents to scope `start_search` / `list_directory` to known workspace roots, not blanket-scan home, and to use `run_zsh "ls -d ~/*workspace* ~/code"` for discovery instead.
- **macOS Accessibility / Screen Recording: explain why brew's symlink path and Cellar resolved path produce TWO TCC entries.** First-deploy users see "Python" entry from dragging in the .app bundle (recorded under symlink path `/usr/local/opt/python@3.12/.../Python.app`), then a second prompt auto-adds "python3.12" (recorded under resolved Cellar path `/usr/local/Cellar/python@3.12/<ver>/.../Python.app/Contents/MacOS/Python`). Both must be ticked. macOS uses the canonicalized exec path as TCC key, but the Privacy panes only accept `.app` bundles when manually adding -- so the symlink-path entry never matches at runtime. Deferred grant via auto-prompt is what makes the second (correct) entry appear. Verified end-to-end: after adding python3.12 to Accessibility, cross-app AppleScript window enumeration (`tell application "System Events" to count windows of process X`) succeeds. The previously-documented "TCC -25211 limit" in this file was a misdiagnosis from incomplete grant -- removed. New section 4.3.7 in `docs/platforms/macos.md` explains the symlink/Cellar duality so future deploys know both prompts are normal and not a bug.
- **macOS docs now warn loudly about `launchctl bootout gui/$UID` without a plist path.** Real-incident from a Mac deployment: a multi-line copy-paste of `launchctl bootout "gui/$(id -u)" ~/Library/LaunchAgents/cc.metahub.macbox-gui.plist` got split at the newline and bash executed `launchctl bootout "gui/501"` as a standalone command -- which Apple defines as "remove every LaunchAgent in the user's GUI domain", causing immediate logout + black screen + return to login window. New section 7.0.5 in `docs/platforms/macos.md` documents the correct restart sequences (`kickstart -k` for code reload; `bootout`+`bootstrap` for plist changes) with explicit single-line warnings. Section 6 (Uninstall) also got the same warning prepended.
- **launchd plist now invokes the venv python directly, no `bash` wrapper.** macOS TCC walks the responsible-process chain to decide which binary needs Accessibility / Screen Recording permission. With the previous `launchd -> /bin/bash _launch-macos-gui.sh -> python` chain, TCC asked the user to grant `bash` permission *in addition* to Python.app -- a confusing second prompt that wasn't explained anywhere in the docs. Plist `ProgramArguments` is now `[$VENV_PY, $SERVER_PY]`, so the chain is just `launchd -> python` and only Python.app needs perms. `_launch-macos-gui.sh` is kept in the repo as a CLI debug entry point (`bash _launch-macos-gui.sh`) for inspecting startup behavior outside launchd; not in the launchd path anymore.
- **`take_screenshot` now returns logical-pixel images** matching `click(x, y)` and `get_screen_size`. Previously the raw `ImageGrab.grab()` returned physical pixels (2880x1800 on Retina) while `pyautogui.click` used logical (1440x900) -- so an agent reading the screenshot would compute coordinates that landed off-screen or in the wrong quadrant. The tool now resizes the capture to logical size before returning.
- **GUI-permission docs now point to the framework `Python.app`, not the venv's `bin/python3` symlink.** macOS Privacy & Security > Accessibility / Screen Recording panes refuse symlinks and CLI binaries (the entry shows up greyed out). The brew framework Python ships a `Python.app` at `<brew_prefix>/opt/python@3.12/Frameworks/Python.framework/Versions/3.12/Resources/Python.app` which IS draggable. `setup-macos.sh` now resolves and prints this path at the end of the run; `docs/platforms/macos.md` § 4 calls out the trap explicitly with both Intel and Apple-Silicon paths.
- **`docs/platforms/macos.md` validation snippets no longer hard-code `~/agent-fleet`** -- they use `<repo>/platforms/macos/server/.venv/bin/python3` so users with a non-default clone path (e.g. `~/code/agent-fleet`, `~/qjl-workspace/agent-fleet`) don't get a confusing `No such file or directory`.
- **`setup-macos.sh` no longer dies silently on brew permission glitches or Tier-3 (macOS 12) brew oddities.** Three changes: (1) An ERR trap now prints which step exploded and the failing line -- `set -e` previously killed the script with no output, leaving first-time users guessing. (2) New `[0/5]` pre-flight checks `/usr/local/share`, `/usr/local/lib`, `/usr/local/Cellar`, `/usr/local/var/homebrew` writability and prints the exact `sudo chown -R` command if any is owned by root (the most common macOS 12 trap). (3) `brew install python@3.12` is now wrapped in `|| true`; success is verified by direct binary existence check (`brew --prefix python@3.12/bin/python3.12`, with fallbacks to `/usr/local/bin/python3.12` and `/opt/homebrew/bin/python3.12`) -- brew's exit code on Tier-3 macOS is unreliable. New troubleshooting section 7.0 in `docs/platforms/macos.md` documents the root causes.

### Added
- **🆕 macOS platform bridge (v0.3.0 base).** New `macbox-gui` MCP server in `platforms/macos/`, mirroring the Windows architecture: FastMCP on SSE, port 8767, advisory acquire/release state model (`acquire_mac` / `release_mac` / `get_mac_status`), ~30 tools across state / screen / mouse / keyboard / process / file / search / shell. Mac-specific: `open_app` instead of `launch_app` (uses `open -a`); `run_zsh` + `run_applescript` instead of `run_powershell`; `press_key` accepts `cmd` / `option` aliases. Tools missing in v0.3.0 (deferred to a later minor): `list_windows` / `inspect_window` / `focus_window` -- on Windows these come from pywinauto; macOS equivalents need AppleScript or NSAccessibility, currently reachable indirectly via `run_applescript`.
- `setup-macos.sh` provisions Tailscale + brew Python + venv + a launchd plist (`~/Library/LaunchAgents/cc.metahub.macbox-gui.plist`). launchd's native `KeepAlive={Crashed=true,SuccessfulExit=false}` + `ThrottleInterval=3` gives us free crash-restart and rate-limiting -- no need for the while-loop launcher hack the Windows side has. The bash launcher (`_launch-macos-gui.sh`) is therefore much thinner: it just `exec`s python and lets launchd handle restart.
- `using-macbox` skill at `platforms/macos/skills/using-macbox/SKILL.md`. Same structure as `using-winpc` (coordinate scaling / long task pattern / multi-agent coordination / common failures), specialized for macOS gotchas (Cmd vs Ctrl, Accessibility / Screen Recording / Automation permission grants, AppleScript automation).
- `docs/platforms/macos.md` setup guide (~150 lines): 7-section walkthrough including the GUI permission grant procedure, validation snippets, common failures, and uninstall steps.
- `examples/multi-platform-claude-settings.json` updated: `macbox-gui` is now a real entry; updated comment to reflect winpc-gui (v0.2) + macbox-gui (v0.3) both being live.

### Changed
- **🚀 Consolidated `winpc-shell` into `winpc-gui` (single MCP server architecture).** Previously the Windows bridge ran two MCP services side-by-side: `winpc-gui` on 8766 (FastMCP, our own GUI tools) and `winpc-shell` on 8765 (mcp-proxy + npm `desktop-commander` providing shell / file / process tools). The `winpc-shell` chain hit several upstream issues over the past iterations (single-client lockout when one agent holds the SSE connection; npm `_npx` cache ENOTEMPTY race on Task Scheduler restart; supergateway IPv6-only bind requiring `netsh portproxy`; mcp-proxy default-mode tying stdio child lifetime to the first SSE client; puppeteer postinstall failing on restricted networks). v0.2 ports the desktop-commander tools — `read_file`, `write_file`, `edit_block`, `list_directory`, `create_directory`, `move_file`, `get_file_info`, `start_process`, `read_process_output`, `interact_with_process`, `force_terminate`, `list_sessions`, `start_search`, `get_more_search_results`, `list_searches`, `stop_search` — into Python inside `windows_gui_mcp.py`. FastMCP supports multi-client SSE natively, so multiple agents can connect simultaneously without the supergateway-style lockout. Net effect: one service instead of two, no Node.js / npm dependency, no portproxy, no mcp-proxy, no per-launch download race. setup-windows.ps1 step 0 cleans up all v0.1 leftovers (old scheduled task, firewall rule, npm globals, portproxy entry, dead launcher script).
- **In-use state model (`acquire_winpc` / `release_winpc` / `get_winpc_status`).** Foundation for multi-agent coordination on a shared Windows test machine. Module-level holder state with 10-minute idle timeout; advisory enforcement (tools work for everyone, but status reports who claimed it). Each tool call refreshes the holder's `last_used_at`. v0.5 plans hard enforcement (reject calls from non-holder when set). Three new tools at the top of the tool list.
- Replaced supergateway with mcp-proxy as the stdio→SSE bridge for desktop-commander. supergateway 3.4.3 has a fatal design bug: it tries to reuse the same MCP `Server` (`Protocol`) instance across SSE connections, so the second SSE client gets `Error: Already connected to a transport. Call close() before connecting to a new transport, or use a separate Protocol instance per connection.` and the process exits with code 1. Claude Code reconnects SSE on every session restart, so every restart killed the bridge. mcp-proxy (Python, `sparfenyuk/mcp-proxy`) is designed for repeated client connections, plus it natively binds `0.0.0.0` via `--sse-host` (no more netsh portproxy workaround) and lives in the same Python venv we already maintain for windows-gui (one fewer toolchain).
- `requirements.txt` adds `mcp-proxy>=0.4`.
- `setup-windows.ps1` step 3 no longer installs supergateway globally; only desktop-commander stays on `npm -g`. If supergateway is detected from a prior version of the script, it is uninstalled.
- `setup-windows.ps1` step 5 stops adding the netsh `v4tov6` portproxy entry (and removes any leftover one).
- `_launch-desktop-commander.ps1` now invokes `python -m mcp_proxy --sse-host 0.0.0.0 --sse-port 8765 -- desktop-commander` and uses `Tee-Object -Append` instead of `*>> $Log` redirection (the latter wrote UTF-16 LE under PowerShell 5.1, mojibake-ing the log so the supergateway crash trace was unreadable until decoded with `[System.Text.Encoding]::Unicode`).
- `diagnose.ps1` section 5b inverted: now expects "no legacy portproxy entry"; warns if one is left over.

### Fixed
- **`_launch-windows-gui.ps1` now wraps python.exe in a restart loop.** Rationale: when Windows kills our python.exe externally (session lock, modern standby, log-off; observed exit code 1067 = `ERROR_PROCESS_ABORTED`), Task Scheduler's `-RestartCount` does NOT trigger because the launcher action itself is still running its `& python` call. The `AtLogOn` trigger also doesn't re-fire on lock/unlock. Result: service stays dead until manual `Start-ScheduledTask`. Loop respawns python within 3s after any external kill, with a rapid-fail safety (3 crashes within 6s = give up, so config errors stay observable). Same pattern we used for the v0.1 mcp-proxy launcher.
- **Documentation pointed at the wrong file for Claude Code MCP config.** `docs/agent-host-setup.md`, `examples/multi-platform-claude-settings.json`, and `platforms/windows/examples/claude-settings.json` all said to merge `mcpServers` into `~/.claude/settings.json`. Claude Code actually reads MCP config from `~/.claude.json` (the top-level single-file state) and `<repo>/.mcp.json` (project-level); `mcpServers` placed in `~/.claude/settings.json` is silently ignored. Verified empirically: editing `settings.json` left `/mcp` showing only built-in plugin servers; moving the same block to `~/.claude.json` made `winpc-shell` and `winpc-gui` connect on next session start. All four files updated, with an added inline warning explaining the trap.
- **Setup script was killing svchost.exe and taking Tailscale down with it.** The user reported Tailscale stopping every time `setup-windows.ps1` reached step 5/6, with the daemon log showing `Got Windows Service event: Stop`. Root cause traced to step 6's port-cleanup loop:
  ```powershell
  Get-NetTCPConnection -LocalPort 8765,8766 -State Listen | ForEach-Object {
      Stop-Process -Id $_.OwningProcess -Force
  }
  ```
  This was supposed to kill leftover MCP service instances. After we added `netsh interface portproxy v4tov6` (the IPv4-IPv6 bridge for supergateway's IPv6-only bind), port 8765 has two listeners: `node.exe` (supergateway, on `::`) AND `svchost.exe` hosting the IP Helper service `iphlpsvc` (the portproxy kernel forwarder, on `0.0.0.0`). The blanket `Stop-Process -Force` was killing svchost. svchost hosts many shared services — including Tailscale — so the entire group went down with it. Fixed by restricting the kill list to known MCP process names (`node`, `python`, `powershell`, `cmd`) only.
- **Firewall rules go orphaned when Tailscale service stops.** Setup previously bound `New-NetFirewallRule -InterfaceAlias Tailscale`; Windows resolves the alias to the adapter's GUID at rule-creation time. When the Tailscale service stops (e.g. after Windows modern-standby), the adapter is removed and the rule's GUID becomes invalid. Even if Tailscale restarts and the adapter returns, a new GUID may not match the rule. Switched to `-RemoteAddress 100.64.0.0/10, fd7a:115c:a1e0::/48` (Tailscale CGNAT IPv4 range + Tailscale ULA IPv6 prefix). Rule now matches by source IP regardless of adapter state, survives Tailscale service restarts, and is tighter than adapter binding (only Tailscale-IP traffic accepted, not arbitrary traffic that happens to enter via the Tailscale adapter).
- diagnose.ps1 grew section 0 (Tailscale daemon health) at the very top: shows the Windows service state and a 3-line `tailscale status` head. Most failures we have hit cascade from "Tailscale daemon down on Windows", and burying that in section 7 made it the last thing read.
- **`npm install -g @wonderwhy-er/desktop-commander` failing on restricted networks.** desktop-commander has `puppeteer` as a transitive dep; puppeteer's postinstall downloads `chrome-headless-shell` from `storage.googleapis.com`, which is unreliable on networks with poor Google-CDN connectivity (China, GFW-affected regions). A half-finished download leaves a directory shell that breaks all subsequent installs with `"browser folder exists but executable is missing"`. Setup script now sets `PUPPETEER_SKIP_DOWNLOAD=true` before `npm install` and clears any stale `~/.cache/puppeteer` directory. desktop-commander's core tools (shell / file / process) work without the browser; for browser automation use the playwright MCP server instead.
- **desktop-commander silently exiting with code 1 a few seconds after launch.** Diagnosed by spawning the npm package directly with stdio capture: `npx -y` extracts the package into a per-invocation cache (`%APPDATA%\npm-cache\_npx\<hash>`). When Task Scheduler retries the launcher fast (we set `RestartCount=5 RestartInterval=1m`), two extracts race on the same path and one dies with `ENOTEMPTY: directory not empty, rename '...node_modules/<dep>' -> '...<dep>-<random>'` during npm's atomic-move step. Fix: setup-windows.ps1 now does `npm install -g supergateway @wonderwhy-er/desktop-commander`, and the launcher invokes `supergateway --stdio "desktop-commander"` — globals live in a stable `%APPDATA%\npm` location with no per-run extract step. Bonus: significantly faster startup (no re-download).
- **desktop-commander unreachable from agent over Tailscale IPv4.** supergateway 3.4.3 calls `app.listen(port)` with no host argument; on Windows, Node defaults to binding `::` (IPv6 only, not dual-stack), so connections from a Tailscale IPv4 peer hit TCP RST. Workaround: setup-windows.ps1 now adds `netsh interface portproxy v4tov6` mapping `0.0.0.0:8765 -> ::1:8765`. Built-in Windows feature, kernel-level forwarder, no external dependency. Tracked for v0.5.x: open an upstream PR at supercorp-ai/supergateway to add a `--host` flag, then drop the workaround.
- diagnose.ps1 grew section 5b which prints `netsh portproxy show v4tov6` so the workaround state is visible.
- Windows docs § 6 (uninstall) now also removes the portproxy entry.
- `setup-windows.ps1` source-parse failed on zh-CN Windows due to PowerShell 5.1 reading UTF-8 (no BOM) source as the system code page (GBK). Rewrote all user-facing strings to ASCII / English. Localized output stays in Markdown docs which are not parsed by PowerShell. Top-of-file note added for future contributors.
- `setup-windows.ps1` runtime-failed parsing `tailscale status --json` on zh-CN Windows: the JSON contains the account display name (which can be CJK), but PowerShell 5.1 reads child-process stdout using the OEM code page, mangling the bytes and breaking `ConvertFrom-Json`. Force `[Console]::OutputEncoding = UTF-8` at script start. Also improved the error path to distinguish "tailscale daemon down" vs "json parse failed" vs "not logged in".
- MCP services started by Task Scheduler showed visible console windows: `python.exe` is a console app (always opens a window), and `cmd.exe /c npx ...` shows a CMD window. Closing the window killed the service. Switched to a hidden PowerShell launcher pattern for both services: `powershell.exe -WindowStyle Hidden -File _launch-<service>.ps1`. The launcher invokes the underlying program (`python.exe` for windows-gui, `npx supergateway` for desktop-commander) which inherits the parent's hidden console — no visible window, but real std handles, and stdout / stderr are appended to a per-service log under `platforms/windows/logs/`.
- An earlier attempt at hiding the windows-gui service used `pythonw.exe`, which exits with code 1 when starting FastMCP/uvicorn (those expect real std handles, but pythonw binds them to NUL). Reverted to `python.exe` inside the hidden launcher.
- Setup script now stops existing tasks and kills any leftover process bound to 8765/8766 before re-registering, so re-running the script cleanly replaces older visible-window instances.

### Changed
- **Breaking · removed SSH from the standard flow.** All Linux↔Windows interaction now goes through MCP only (desktop-commander on 8765 + windows-gui on 8766). Existing v0.1.0 deployments can clean up: stop & uninstall OpenSSH Server, remove `C:\ProgramData\ssh\administrators_authorized_keys`, drop the SSH firewall rule.
- `setup-windows.ps1` now auto-discovers `server/` relative to itself; runs the GUI MCP directly from the cloned repo (no more `C:\mcp\gui` copy). Single source of truth.
- `setup-windows.ps1` auto-installs Python 3.12 if missing (or version < 3.10).
- `setup-windows.ps1` registers Task Scheduler tasks under `$env:USERNAME` instead of hardcoded `Administrator`.
- `setup-windows.ps1` adds 60s post-start verification with port-listen polling.

### Added
- `docs/agent-host-setup.md`: agent-side configuration guide (Tailscale + MCP client setup), audience-separated from the Windows guide.
- `README.md`: role-based entry points (device admin vs agent admin).
- `platforms/windows/scripts/diagnose.ps1`: read-only diagnostic that prints listening-address bind state, owning process, localhost / Tailscale-IP self-tests, MCP firewall rules with their interface filter, Tailscale adapter, last scheduled task result, **service log tails** (sections 9), and **recent Task Scheduler events** (section 10). Triages "agent host cannot reach the MCP services" in under a minute. Surfaced at the top of `docs/platforms/windows.md` § 7.
- Per-service log files at `platforms/windows/logs/{desktop-commander,windows-gui}.log` (gitignored). Both launchers append stdout + stderr so silent service failures (the hardest kind) are debuggable post-mortem.
- `scripts/check-ps-syntax.sh`: AST-parse all `.ps1` files in the repo via PowerShell 7's parser. Runs locally to catch syntax errors before pushing.

### Removed
- `setup-windows.ps1`: OpenSSH Server installation, default-shell registry tweak, `administrators_authorized_keys` setup, port 22 firewall rule.
- `docs/platforms/windows.md`: SSH key generation, `administrators_authorized_keys` placement, ssh-config setup, ssh test verification, file-transfer-via-http.server section. Doc is now Windows-administrator-focused (~150 lines, was ~500).

## [0.1.0] - 2026-05-06

Initial private release. Windows platform bridge.

### Added
- **Windows 11 platform bridge** (`platforms/windows/`)
  - `windows_gui_mcp.py`: FastMCP server exposing 17 tools over SSE on port 8766
    - Screen: `get_screen_size`, `take_screenshot`
    - Window: `list_windows`, `inspect_window`, `focus_window`
    - Mouse: `click`, `move_mouse`
    - Keyboard: `type_text`, `paste_text`, `press_key`
    - Process: `launch_app`, `kill_process`, `list_processes`
    - Shell: `run_powershell`
  - `setup-windows.ps1`: one-click installer covering Tailscale check, Node.js LTS, Python venv, firewall rules, and Task Scheduler auto-start for both MCP services
  - `requirements.txt` + `pyproject.toml` for installation
  - `claude-settings.json` reference config for the agent host's Claude Code
- **Tailscale-based cross-network connectivity** (works across LANs, no port-forwarding required)
- **desktop-commander** integration on port 8765 (community shell/file/process MCP via supergateway stdio→SSE bridge)
- **Architecture document** (`docs/architecture.md`) — defines the universal three-segment bridge model and the Universal Tool Set contract that all platforms must implement
- **Roadmap** (`docs/roadmap.md`) — version targets for macOS (0.2.0), Android (0.3.0), iOS (0.4.0), cross-device coordination (0.5.0), public OSS release (1.0.0)
- **Setup guide** (`docs/platforms/windows.md`) — operations manual in Chinese with troubleshooting checklist

### Security
- MCP ports (8765/8766) are restricted to the Tailscale network interface via Windows Firewall rules; not exposed to LAN or internet

[0.7.0-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.7.0-alpha
[0.6.15-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.15-alpha
[0.6.14-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.14-alpha
[0.6.13-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.13-alpha
[0.6.12-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.12-alpha
[0.6.11-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.11-alpha
[0.6.10-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.10-alpha
[0.6.9-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.9-alpha
[0.6.8-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.8-alpha
[0.6.7-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.7-alpha
[0.6.6-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.6-alpha
[0.6.5-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.5-alpha
[0.6.4-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.4-alpha
[0.6.3-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.3-alpha
[0.6.2-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.2-alpha
[0.6.1-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.1-alpha
[0.6.0-alpha]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.6.0-alpha
[0.1.0]: https://github.com/metahub-tech/agent-fleet/releases/tag/v0.1.0

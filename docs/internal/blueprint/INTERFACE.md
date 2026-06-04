# Project INTERFACE（自动生成 · 请勿手编）

_由 `scripts/gen-blueprint-interface.sh` 从代码自动生成。各平台 MCP server 上的工具签名集 = agent 跨平台调用的 universal tool set。_

> **覆盖范围**：仅列各 server 里 `@*.tool` 静态装饰的函数。
> **不在覆盖范围**：能力框架运行时动态注入的可选能力工具（如 Windows / macOS 上的 `agent_browser` / `human_browser_open` 系列，共 ~28 个）——这些工具运行时通过 `list_capabilities()` 取真实清单；文档侧见各平台 README 的 "浏览器能力（可选）/ Platform-specific extensions" 节。

## android

源：`platforms/android/server/android_device_mcp.py`

- `acquire(device: Annotated[Optional[str], Field(description="serial or alias; omit if only 1 phone or you've set a default")], holder_name: Annotated[str, Field(description="Human-readable identifier (e.g. 'agent-A', 'qjl-laptop')")]) -> dict`
- `current_app(device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `deliver_staged(stage_id: Annotated[str | None, Field(description='已完成的分片暂存 id；与 url 二选一')], url: Annotated[str | None, Field(description='http/https 链接（主机后台下载）；与 stage_id 二选一')], device_path: Annotated[str | None, Field(description='设备目标路径；缺省 /sdcard/Download/<filename>')], install: Annotated[bool, Field(description='true=push 后 pm install（APK）')], make_visible: Annotated[bool, Field(description='图片则 push 后扫描进相册')], device: Annotated[str | None, Field(description='serial/alias；单机可省')]) -> dict`
- `dump_ui(max_depth: Annotated[int, Field(ge=1, le=20, description='Max tree depth to walk')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `find_elements(text: Annotated[Optional[str], Field(description='Substring-match Element.text')], resource_id: Annotated[Optional[str], Field(description='Substring-match resource_id')], content_desc: Annotated[Optional[str], Field(description='Substring-match content_desc (a11y label)')], class_name: Annotated[Optional[str], Field(description="Substring-match class (e.g. 'android.widget.Button')")], clickable_only: Annotated[bool, Field(description='Only return clickable=true elements')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `get_default_device() -> dict`
- `get_screen_size(device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `get_status(device: Annotated[Optional[str], Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `get_upload_endpoint() -> dict`
- `install_app(path: Annotated[str, Field(description='Absolute path to .apk on the HOST machine')], replace: Annotated[bool, Field(description='-r flag: replace existing')], grant_runtime: Annotated[bool, Field(description='-g flag: grant all runtime permissions')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `job_status(job_id: Annotated[str, Field(description='deliver_staged 返回的 job_id')]) -> dict`
- `launch_app(target: Annotated[str, Field(description="Package id, e.g. 'com.android.settings'")], activity: Annotated[Optional[str], Field(description="Activity name (e.g. '.MainActivity'). None = use launcher intent.")], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `list_devices() -> dict`
- `list_packages(filter_substring: Annotated[Optional[str], Field(description='Filter package names containing this substring; None = all')], only_user: Annotated[bool, Field(description='Only third-party (non-system) packages')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `long_press(x: int, y: int, duration_ms: Annotated[int, Field(ge=300, le=10000, description='Hold duration in ms')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `press_key(key: Annotated[str, Field(description='Key name: back/home/menu/recent/power/wake/volume_up/volume_down/enter/tab/del/space/search/camera')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `pull_file(device_path: Annotated[str, Field(description='Source path on the DEVICE')], host_path: Annotated[str, Field(description='Destination path on the HOST (parent dir must exist)')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `push_file(host_path: Annotated[str, Field(description='Absolute path on the HOST')], device_path: Annotated[str, Field(description='Destination path on the DEVICE (e.g. /sdcard/foo.txt)')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `release(device: Annotated[Optional[str], Field(description="serial or alias; omit if only 1 phone or you've set a default")], holder_name: Annotated[str, Field(description='Must match the name used in acquire')]) -> dict`
- `run_shell(script: Annotated[str, Field(description='Shell command to run ON the device')], timeout: Annotated[int, Field(ge=1, le=25, description='Seconds; hard-capped to 25 — fastmcp transport dies past ~30s (jlowin/fastmcp#823)')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `set_default_device(device: Annotated[str, Field(description='serial or alias to use as the default for this session')]) -> dict`
- `stage_upload(content_base64: Annotated[str, Field(description='本片字节的 base64')], stage_id: Annotated[str | None, Field(description='缺省=新建会话；给定=向该会话追加')], last: Annotated[bool, Field(description='true=收尾，标记暂存文件完成')], filename: Annotated[str | None, Field(description='新建会话时的文件名')], device: Annotated[str | None, Field(description='serial/alias；单机可省')]) -> dict`
- `swipe(x1: Annotated[int, Field(ge=0, description='Start X')], y1: Annotated[int, Field(ge=0, description='Start Y')], x2: Annotated[int, Field(ge=0, description='End X')], y2: Annotated[int, Field(ge=0, description='End Y')], duration_ms: Annotated[int, Field(ge=50, le=10000, description='Swipe duration in ms')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `take_screenshot(device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> Image`
- `tap(x: Annotated[int, Field(ge=0, description='X coordinate in screen pixels')], y: Annotated[int, Field(ge=0, description='Y coordinate in screen pixels')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `tap_element(text: Annotated[Optional[str], Field(description='Substring-match Element.text')], resource_id: Annotated[Optional[str], Field(description='Substring-match resource_id')], content_desc: Annotated[Optional[str], Field(description='Substring-match content_desc')], class_name: Annotated[Optional[str], Field(description='Substring-match class')], nth: Annotated[int, Field(ge=0, description='If multiple match, tap the nth (0-indexed)')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `terminate_app(target: Annotated[str, Field(description='Package id to force-stop')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `type_text(text: Annotated[str, Field(description='Text to type. Whitespace and special chars handled.')], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `uninstall_app(target: Annotated[str, Field(description="Package id, e.g. 'com.example.app'")], device: Annotated[str | None, Field(description="serial or alias; omit if only 1 phone or you've set a default")]) -> dict`
- `upload_media(content_base64: Annotated[str | None, Field(description='文件字节的 base64；与 url 二选一')], url: Annotated[str | None, Field(description='http/https 链接；与 content_base64 二选一')], device_path: Annotated[str | None, Field(description='设备目标路径；缺省 /sdcard/Pictures/<filename>')], filename: Annotated[str | None, Field(description='文件名；缺省从 url 尾段或自动生成')], make_visible: Annotated[bool, Field(description='图片 push 后触发 MediaStore 扫描使相册可见')], device: Annotated[str | None, Field(description='serial/alias；单机可省')]) -> dict`

## ios

源：`platforms/ios/server/ios_device_mcp.py`

- `acquire(device: Annotated[str | None, Field(description="udid or alias; omit if only 1 device or you've set a default")], holder_name: Annotated[str, Field(description="Human-readable identifier (e.g. 'agent-A')")]) -> dict`
- `activate_app(bundle_id: Annotated[str, Field(description='Bundle ID to bring to foreground (must be already running)')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `current_app(device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `device_info(device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `dump_ui(max_depth: Annotated[int | None, Field(description='Optional depth limit for the UI tree; currently advisory (WDA returns the full tree, depth limit is not enforced).')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `find_elements(using: Annotated[str, Field(description="Locator strategy: 'class chain' (recommended) | 'xpath' | 'predicate string' | 'name' | 'accessibility id'")], value: Annotated[str, Field(description='Locator value. Class chain example: **/XCUIElementTypeButton[`name == "Done"`]')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `get_default_device() -> dict`
- `get_screen_size(device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `get_status(device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `get_upload_endpoint() -> dict`
- `install_app(path: Annotated[str, Field(description='Absolute path to .ipa on the HOST (macmini)')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `launch_app(target: Annotated[str, Field(description="Bundle ID to launch, e.g. 'com.apple.MobileSafari'")], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `list_apps(filter_substring: Annotated[Optional[str], Field(description='Filter bundle IDs containing this substring; None = all')], only_user: Annotated[bool, Field(description='Only user-installed apps (skip system)')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `list_devices() -> dict`
- `long_press(x: Annotated[int, Field(description='X coordinate', ge=0)], y: Annotated[int, Field(description='Y coordinate', ge=0)], duration_ms: Annotated[int, Field(description='Hold duration in ms', ge=50, le=10000)], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `press_key(key: Annotated[str, Field(description='Physical button name: home | volume_up | volume_down | lock')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `pull_file_from_app(bundle_id: Annotated[str, Field(description="Source app's bundle ID")], device_relpath: Annotated[str, Field(description="Source path inside the app sandbox (same relativity rules as push_file_to_app's device_relpath).")], host_path: Annotated[str, Field(description='Destination path on HOST (parent dir auto-created)')], documents_only: Annotated[bool, Field(description='True: Documents-only (UIFileSharingEnabled apps). False: full container (dev-signed apps only).')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `push_file_to_app(host_path: Annotated[str, Field(description='Absolute path on the HOST (macmini)')], bundle_id: Annotated[str, Field(description="Target app's bundle ID")], device_relpath: Annotated[str, Field(description="Destination path inside the app sandbox. With documents_only=True it's relative to Documents (e.g. 'inbox/foo.txt'); with documents_only=False it's relative to container root (e.g. 'Documents/foo.txt').")], documents_only: Annotated[bool, Field(description='True: Documents-only (UIFileSharingEnabled apps). False: full container (dev-signed apps only).')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `release(device: Annotated[str | None, Field(description='udid or alias')], holder_name: Annotated[str, Field(description="Must match acquire's holder_name")]) -> dict`
- `set_default_device(device: Annotated[str, Field(description='udid or alias to use as the default for this session')]) -> dict`
- `swipe(x1: Annotated[int, Field(description='Start X', ge=0)], y1: Annotated[int, Field(description='Start Y', ge=0)], x2: Annotated[int, Field(description='End X', ge=0)], y2: Annotated[int, Field(description='End Y', ge=0)], duration_ms: Annotated[int, Field(description='Swipe duration in ms', ge=50, le=10000)], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `take_screenshot(region: Annotated[list[int] | None, Field(description='[x,y,w,h] crop; None=full screen (crop not yet implemented)')], device: Annotated[str | None, Field(description='udid or alias')]) -> Image`
- `tap(x: Annotated[int, Field(description='X coordinate in points', ge=0)], y: Annotated[int, Field(description='Y coordinate in points', ge=0)], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `tap_element(element_id: Annotated[str | None, Field(description='WDA element ELEMENT id from find_elements. If None, supply using+value below.')], using: Annotated[str | None, Field(description='If element_id is None: locator strategy. Same options as find_elements.')], value: Annotated[str | None, Field(description='If element_id is None: locator value.')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `terminate_app(target: Annotated[str, Field(description='Bundle ID to terminate')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `type_text(text: Annotated[str, Field(description='Text to type via the on-screen keyboard')], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `uninstall_app(target: Annotated[str, Field(description="Bundle ID to uninstall, e.g. 'com.example.MyApp'")], device: Annotated[str | None, Field(description='udid or alias')]) -> dict`
- `upload_to_app(bundle_id: Annotated[str, Field(description='目标 app bundle id')], relpath: Annotated[str, Field(description='app 沙盒内相对路径（默 Documents 下；documents_only=True）')], content_base64: Annotated[Optional[str], Field(description='文件字节 base64；与 url 二选一')], url: Annotated[Optional[str], Field(description='http/https 链接；与 content_base64 二选一')], documents_only: Annotated[bool, Field(description='True=Documents-only；False=full container（dev-signed apps）')], device: Annotated[Optional[str], Field(description='udid 或 alias')]) -> dict`
- `upload_to_photos(content_base64: Annotated[Optional[str], Field(description='文件字节 base64；与 url 二选一')], url: Annotated[Optional[str], Field(description='http/https 链接；与 content_base64 二选一')], filename: Annotated[Optional[str], Field(description='原文件名（必填，决定 image/video）')], device: Annotated[Optional[str], Field(description='udid 或 alias')]) -> dict`

## macos

源：`platforms/macos/server/mac_device_mcp.py`

- `acquire(holder_name: Annotated[str, Field(description="Human-readable identifier (e.g. 'agent-A', 'qjl-laptop')")]) -> dict`
- `create_directory(path: Annotated[str, Field(description='Absolute directory path')]) -> dict`
- `current_app() -> dict`
- `dump_ui(max_depth: Annotated[Optional[int], Field(description='Max AX tree depth (1-15). Defaults to 6 if not specified.', ge=1, le=15)]) -> dict`
- `edit_block(path: Annotated[str, Field(description='Absolute path to the file')], old_string: Annotated[str, Field(description='Exact text to find')], new_string: Annotated[str, Field(description='Text to replace it with')], replace_all: Annotated[bool, Field(description='Replace all occurrences (default: only first)')], encoding: Annotated[str, Field(description='Text encoding')]) -> dict`
- `find_elements(query: Annotated[str, Field(description="Case-insensitive substring matched against an element's AXTitle / AXDescription(label) / value / AXRole (highest-priority field wins; exact match ranks first). e.g. 'Save', '9'")], app: Annotated[Optional[str], Field(description='App name substring to scope the AX search; default = current frontmost app')], include_disabled: Annotated[bool, Field(description='Include disabled (AXEnabled=false) elements (default: only enabled)')], max_results: Annotated[int, Field(ge=1, le=100, description='Cap on returned candidates')], max_depth: Annotated[int, Field(ge=1, le=15, description='Max AX tree depth')]) -> dict`
- `force_terminate(pid: Annotated[int, Field(description='PID returned by start_process')]) -> dict`
- `get_default_device() -> dict`
- `get_file_info(path: Annotated[str, Field(description='Absolute path to file or directory')]) -> dict`
- `get_more_search_results(search_id: Annotated[str, Field(description='Returned by start_search')], offset: Annotated[int, Field(description='Start match index (0-based)')], length: Annotated[int, Field(description='Max matches to return', ge=1, le=1000)]) -> dict`
- `get_screen_size() -> dict`
- `get_status() -> dict`
- `interact_with_process(pid: Annotated[int, Field(description='PID returned by start_process')], input_text: Annotated[str, Field(description='Text to send to the process stdin (newline added automatically)')]) -> dict`
- `kill_process(pid: int) -> dict`
- `launch_app(target: Annotated[str, Field(description="App name (e.g. 'Safari', 'Terminal') or full path")], args: Annotated[Optional[list[str]], Field(description='Files / URLs to open with the app')]) -> dict`
- `list_devices() -> list[dict]`
- `list_directory(path: Annotated[str, Field(description='Absolute directory path')], depth: Annotated[int, Field(description='Recursion depth (1 = direct children only)', ge=1, le=10)], include_hidden: Annotated[bool, Field(description='Include dotfiles')]) -> dict`
- `list_processes(name_filter: Annotated[Optional[str], Field(description='Substring filter on process name; None = all')]) -> list[dict]`
- `list_searches() -> list[dict]`
- `list_sessions() -> list[dict]`
- `list_ui_elements(app: Annotated[str, Field(description="App name (e.g. 'Safari', 'Calculator', 'Code'); case-insensitive substring match on process name")], max_depth: Annotated[int, Field(ge=1, le=15, description='Max tree depth from app root')]) -> dict`
- `move_file(src: Annotated[str, Field(description='Absolute source path')], dst: Annotated[str, Field(description='Absolute destination path')]) -> dict`
- `move_mouse(x: int, y: int, duration: Annotated[float, Field(description='Seconds to take; 0 = instant')]) -> dict`
- `paste_text(text: Annotated[str, Field(description='Any text including CJK / Unicode')]) -> dict`
- `press_key(keys: Annotated[str, Field(description="Single key or combo, e.g. 'enter' / 'cmd+s' / 'cmd+space' / 'cmd+tab'")]) -> dict`
- `read_file(path: Annotated[str, Field(description='Absolute path to the file')], offset: Annotated[int, Field(description='Start line (0=from start, negative=tail N)')], length: Annotated[int, Field(description='Max lines to return', ge=1, le=10000)], encoding: Annotated[str, Field(description='Text encoding')]) -> dict`
- `read_process_output(pid: Annotated[int, Field(description='PID returned by start_process')], offset: Annotated[int, Field(description='Start line (0=from start, negative=tail N)')], length: Annotated[int, Field(description='Max lines to return', ge=1, le=5000)]) -> dict`
- `release(holder_name: Annotated[str, Field(description='Must match the holder_name used in acquire')]) -> dict`
- `run_applescript(script: Annotated[str, Field(description='AppleScript content')], timeout: Annotated[int, Field(ge=1, le=25, description=f'Hard-capped to {_FASTMCP_DEADLINE_SAFE_SECONDS}s — fastmcp transport dies past ~30s.')]) -> dict`
- `run_shell(script: Annotated[str, Field(description='zsh script content')], timeout: Annotated[int, Field(ge=1, le=25, description=f'Hard-capped to {_FASTMCP_DEADLINE_SAFE_SECONDS}s — fastmcp transport dies past ~30s. Use start_process for longer jobs.')]) -> dict`
- `set_default_device(device: Annotated[str, Field(description='ignored on single-device platforms')]) -> dict`
- `start_process(command: Annotated[str, Field(description='Command line to execute')], shell: Annotated[str, Field(description='zsh / bash / sh / direct (no shell, splits args by shlex)')]) -> dict`
- `start_search(path: Annotated[str, Field(description='Root directory to search')], pattern: Annotated[str, Field(description='Regex pattern (Python re syntax)')], file_glob: Annotated[str, Field(description="Filename glob, e.g. '*.py' or '*'")], case_sensitive: Annotated[bool, Field(description='Case-sensitive matching')]) -> dict`
- `stop_search(search_id: Annotated[str, Field(description='Returned by start_search')]) -> dict`
- `swipe(x1: Annotated[int, Field(description='start x')], y1: Annotated[int, Field(description='start y')], x2: Annotated[int, Field(description='end x')], y2: Annotated[int, Field(description='end y')], duration_ms: Annotated[int, Field(description='drag duration in ms')]) -> dict`
- `take_screenshot(region: Annotated[Optional[tuple[int, int, int, int]], Field(description='(left, top, right, bottom) in logical pixels; None = full screen')]) -> Image`
- `tap(x: Annotated[int, Field(description='Screen x coordinate')], y: Annotated[int, Field(description='Screen y coordinate')], button: Annotated[str, Field(description='left / right / middle')], clicks: Annotated[int, Field(ge=1, le=3)]) -> dict`
- `tap_element(query: Annotated[str, Field(description='Element query (see find_elements). The best-ranked match is clicked.')], app: Annotated[Optional[str], Field(description='App name substring to scope; default = frontmost')], nth: Annotated[Optional[int], Field(ge=0, description='Click the nth candidate (0 = first/best-ranked). Omit for auto (single/exact → click; multiple ambiguous → returns candidates). Pass an explicit nth after find_elements to disambiguate.')], include_disabled: Annotated[bool, Field(description='Allow clicking disabled elements')]) -> dict`
- `terminate_app(target: Annotated[str, Field(description="App name or bundle identifier substring to match (e.g. 'Safari', 'com.apple.safari'). Short or generic substrings can over-match unintended processes; prefer the full app name or bundle ID.")]) -> dict`
- `type_text(text: Annotated[str, Field(description='ASCII text')], interval: Annotated[float, Field(description='Per-char delay in seconds')]) -> dict`
- `write_file(path: Annotated[str, Field(description='Absolute path to the file')], content: Annotated[str, Field(description='Text content to write')], mode: Annotated[str, Field(description='rewrite (default) or append')], encoding: Annotated[str, Field(description='Text encoding')]) -> dict`

## windows

源：`platforms/windows/server/win_device_mcp.py`

- `acquire(holder_name: Annotated[str, Field(description="Human-readable identifier (e.g. 'agent-A', 'qjl-laptop')")]) -> dict`
- `create_directory(path: Annotated[str, Field(description='Absolute directory path')]) -> dict`
- `current_app() -> dict`
- `dump_ui(max_depth: Annotated[Optional[int], Field(description='UI tree max depth (1-10). Defaults to 4 if not specified.', ge=1, le=10)]) -> dict`
- `edit_block(path: Annotated[str, Field(description='Absolute path to the file')], old_string: Annotated[str, Field(description='Exact text to find')], new_string: Annotated[str, Field(description='Text to replace it with')], replace_all: Annotated[bool, Field(description='Replace all occurrences (default: only first)')], encoding: Annotated[str, Field(description='Text encoding')]) -> dict`
- `find_elements(query: Annotated[str, Field(description="Case-insensitive substring matched against an element's name / automation-id / control-type / class-name (highest-priority field wins; exact match ranks first). e.g. 'Save', 'Submit'")], window_title: Annotated[Optional[str], Field(description='Restrict to the window whose title contains this; default = current foreground window')], control_type: Annotated[Optional[str], Field(description="Pre-filter by UIA control type (e.g. 'Button', 'Edit', 'MenuItem', 'CheckBox') to narrow + speed up the search")], include_disabled: Annotated[bool, Field(description='Include disabled elements (default: only enabled)')], max_results: Annotated[int, Field(ge=1, le=100, description='Cap on returned candidates')]) -> dict`
- `focus_window(title_substring: Annotated[str, Field(description='Window whose title contains this substring')]) -> dict`
- `force_terminate(pid: Annotated[int, Field(description='PID returned by start_process')]) -> dict`
- `get_default_device() -> dict`
- `get_file_info(path: Annotated[str, Field(description='Absolute path to file or directory')]) -> dict`
- `get_more_search_results(search_id: Annotated[str, Field(description='Returned by start_search')], offset: Annotated[int, Field(description='Start match index (0-based)')], length: Annotated[int, Field(description='Max matches to return', ge=1, le=1000)]) -> dict`
- `get_screen_size() -> dict`
- `get_status() -> dict`
- `inspect_window(title_substring: Annotated[str, Field(description='Window whose title contains this substring')], max_depth: Annotated[int, Field(description='UI tree max depth', ge=1, le=10)]) -> str`
- `interact_with_process(pid: Annotated[int, Field(description='PID returned by start_process')], input_text: Annotated[str, Field(description='Text to send to the process stdin (newline added automatically)')]) -> dict`
- `kill_process(pid: int) -> dict`
- `launch_app(target: Annotated[str, Field(description='Executable path or PATH-resolvable command')], args: Annotated[Optional[list[str]], Field(description='Command-line arguments')]) -> dict`
- `list_devices() -> list[dict]`
- `list_directory(path: Annotated[str, Field(description='Absolute directory path')], depth: Annotated[int, Field(description='Recursion depth (1 = direct children only)', ge=1, le=10)], include_hidden: Annotated[bool, Field(description='Include dotfiles')]) -> dict`
- `list_processes(name_filter: Annotated[Optional[str], Field(description='Substring filter on process name; None = all')]) -> list[dict]`
- `list_searches() -> list[dict]`
- `list_sessions() -> list[dict]`
- `list_windows() -> list[dict]`
- `move_file(src: Annotated[str, Field(description='Absolute source path')], dst: Annotated[str, Field(description='Absolute destination path')]) -> dict`
- `move_mouse(x: int, y: int, duration: Annotated[float, Field(description='Seconds to take; 0 = instant')]) -> dict`
- `paste_text(text: Annotated[str, Field(description='Any text including CJK / Unicode')]) -> dict`
- `press_key(keys: Annotated[str, Field(description="Single key or combo, e.g. 'enter' / 'ctrl+s' / 'alt+f4' / 'win+d'")]) -> dict`
- `read_file(path: Annotated[str, Field(description='Absolute path to the file')], offset: Annotated[int, Field(description='Start line (0=from start, negative=tail N)')], length: Annotated[int, Field(description='Max lines to return', ge=1, le=10000)], encoding: Annotated[str, Field(description='Text encoding')]) -> dict`
- `read_process_output(pid: Annotated[int, Field(description='PID returned by start_process')], offset: Annotated[int, Field(description='Start line (0=from start, negative=tail N)')], length: Annotated[int, Field(description='Max lines to return', ge=1, le=5000)]) -> dict`
- `release(holder_name: Annotated[str, Field(description='Must match the holder_name used in acquire')]) -> dict`
- `run_shell(script: Annotated[str, Field(description='PowerShell script content')], timeout: Annotated[int, Field(ge=1, le=25, description=f'Hard-capped to {_FASTMCP_DEADLINE_SAFE_SECONDS}s — fastmcp transport dies past ~30s. Use start_process for longer jobs.')]) -> dict`
- `set_default_device(device: Annotated[str, Field(description='ignored on single-device platforms')]) -> dict`
- `start_process(command: Annotated[str, Field(description='Command line to execute')], shell: Annotated[str, Field(description='powershell / cmd / pwsh / direct (no shell)')]) -> dict`
- `start_search(path: Annotated[str, Field(description='Root directory to search')], pattern: Annotated[str, Field(description='Regex pattern (Python re syntax)')], file_glob: Annotated[str, Field(description="Filename glob, e.g. '*.py' or '*'")], case_sensitive: Annotated[bool, Field(description='Case-sensitive matching')]) -> dict`
- `stop_search(search_id: Annotated[str, Field(description='Returned by start_search')]) -> dict`
- `swipe(x1: Annotated[int, Field(description='start x')], y1: Annotated[int, Field(description='start y')], x2: Annotated[int, Field(description='end x')], y2: Annotated[int, Field(description='end y')], duration_ms: Annotated[int, Field(description='drag duration in ms')]) -> dict`
- `take_screenshot(region: Annotated[Optional[tuple[int, int, int, int]], Field(description='(left, top, right, bottom); None = full screen')]) -> Image`
- `tap(x: Annotated[int, Field(description='Screen x coordinate')], y: Annotated[int, Field(description='Screen y coordinate')], button: Annotated[str, Field(description='left / right / middle')], clicks: Annotated[int, Field(ge=1, le=3)]) -> dict`
- `tap_element(query: Annotated[str, Field(description='Element query (see find_elements). The best-ranked match is clicked.')], window_title: Annotated[Optional[str], Field(description='Restrict to this window; default = foreground')], control_type: Annotated[Optional[str], Field(description='Pre-filter by UIA control type')], nth: Annotated[Optional[int], Field(ge=0, description='Click the nth candidate (0 = first/best-ranked). Omit for auto (single/exact → click; multiple ambiguous → returns candidates). Pass an explicit nth after find_elements to disambiguate.')], button: Annotated[str, Field(description='left / right / middle')], include_disabled: Annotated[bool, Field(description='Allow clicking disabled elements')]) -> dict`
- `terminate_app(target: Annotated[str, Field(description="Process name (e.g. 'notepad.exe') or executable path substring to match. Short or generic substrings can over-match unintended processes; prefer the full process name.")]) -> dict`
- `type_text(text: Annotated[str, Field(description='ASCII text')], interval: Annotated[float, Field(description='Per-char delay in seconds')]) -> dict`
- `write_file(path: Annotated[str, Field(description='Absolute path to the file')], content: Annotated[str, Field(description='Text content to write')], mode: Annotated[str, Field(description='rewrite (default) or append')], encoding: Annotated[str, Field(description='Text encoding')]) -> dict`


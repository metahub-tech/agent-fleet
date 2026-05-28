# Android Agent 文件上传 — agent 字节 → 设备主机暂存 → 手机(快/稳两条路径)

**Date:** 2026-05-28
**Status:** approved (design), pending spec review
**Platform:** android-device (v0.7.0-alpha)

## Problem

agent 在用 android-device 给手机操作时(实例:给小红书换背景图),**无法把文件传到手机上**。根因有两层:

1. **传输断层(今天的真实阻塞)。** android-device MCP 是跑在**设备主机**上的 streamable-http 服务(`0.0.0.0:8768/mcp`),agent 经 Tailscale 远程接入。现有 `push_file(host_path, device_path)` 的 `host_path` 读的是**设备主机本地磁盘**,而 agent 要上传的图片在 **agent 自己的机器**(云端)上——服务端根本看不见 agent 的文件系统,所以 agent 持有的字节传不到设备主机,自然也推不进手机。

2. **大文件 25s 上限。** 调用方即便传大超时(`push_file` 传 `timeout=300`、`install_app` 传 `120`),也会被 `_adb_run` 内部的 `min(timeout, _FASTMCP_DEADLINE_SAFE_SECONDS)` 统一降到 **25s**(fastmcp streamable-http 在 ~30s 必断,jlowin/fastmcp#823)。一个几十~上百 MB 的 APK 光 `adb push` 就 10–30s+,叠加 `pm install` 必然超时——即使解决了传输断层,大文件仍卡死。代码 line 137 的 hint 已预告需要 "start_process-based async install/push API"。

3. **相册可见性。** 即便图片落到 `/sdcard`,Android MediaStore 不一定立即索引,小红书等 app 的选图器看不到——"换背景"这类用例本质上需要图片出现在相册里。

## Goal

让 agent 能把**自己持有的字节**(本地文件 / URL / 内联 base64)可靠地传到手机,并对图片**自动进相册**;大文件(APK/视频)不受 25s 上限限制。

设计成**两条共享暂存层的路径**:
- **快路径(同步)**:小图片一次调用搞定——覆盖"换背景"的真实痛点。
- **稳路径(异步)**:大文件经主机暂存 + 后台任务 + 轮询——覆盖 APK/大素材。

## Architecture

### 核心模型:暂存在主机,慢操作异步化

所有上传字节**先落到设备主机的暂存目录** `~/.agent-fleet/uploads/`,再 `adb push` 到手机。设备主机就是 agent 与手机之间天然的"跳板机"。

```
agent 字节 ──①──▶ 设备主机暂存目录 ──②──▶ 手机 ──③──▶ 进相册 / 装 APK
            base64/url            adb push       媒体扫描 / pm install
```

两条路径共享暂存层,差别只在 ①②③ 中**耗时的部分是否异步**:

- **快路径**:小文件,①②③ 全在一次 ≤25s 同步调用内完成。
- **稳路径**:大文件,把 url 下载(①)、`adb push`(②)、`pm install`(③)丢进**主机后台任务**,工具立即返回 `job_id`,agent 轮询拿结果。

### 后台任务运行器(新增基础设施)

现有 `_adb_run` 把调用方的超时 `min()` 到 25s,无法承载大文件。新增 `_adb_popen`:用 `subprocess.Popen` 在**守护线程**里跑长命令,**不经 25s 钳制**;线程完成时把结果写入**内存 job 注册表**(加锁,带 TTL 回收)。这套 runner 也为将来异步 `install_app` 复用(line 137 预告的方向)。

**孤儿进程处置(关键)**:守护线程是进程内的,但 `Popen` 出去的 `adb push` 子进程是**独立进程**——若 FastMCP server 因并发 adb 超时崩溃/重启,守护线程与内存 job 注册表都没了,但孤儿 `adb push` 仍在跑、占着(不稳定的)无线 ADB 连接,与 job 状态彻底脱节(华为无线 ADB 不稳,这是真实场景)。处置:① 每个后台 job 把子进程 PID 写到 `~/.agent-fleet/uploads/jobs/<job_id>.pid`;② **server 启动时**扫描该目录,对仍存活的残留 PID 逐一 `kill` 并清理对应暂存文件与 pid 文件(确保重启后无脱管的 adb 子进程);③ job 正常结束时删除自己的 pid 文件。

> 由根因决定的约束:**没有 `local_path` 入参**——服务端在设备主机上看不见 agent 的磁盘。"agent 本地文件"这一来源 = agent 自行读取并 base64 后经 `content_base64` 传入(小文件走 `upload_media`,大文件走 `stage_upload` 分片)。

## Tool Surface

新增 4 个工具;`push_file` / `install_app` 保留为底层主机磁盘→设备原语,不动。

### 1. `upload_media`(快路径,同步)
```
upload_media(
    content_base64: str | None = None,   # 与 url 异或
    url: str | None = None,              # 与 content_base64 异或
    device_path: str | None = None,      # 默认 /sdcard/Pictures/<filename>
    filename: str | None = None,         # 缺省从 url 尾段 / 自动生成
    make_visible: bool = True,           # 图片 push 后触发 MediaStore 扫描
    device: str | None = None,
) -> dict
```
- 同步:解码/下载到暂存 → `adb push` → (图片且 make_visible)触发媒体扫描 → 清理暂存。
- **大小上限**:`content_base64` 解码后 ≤ ~6MB;`url` 同步上限**随连接模式可配**——USB 模式 ~20MB 稳,**无线 ADB(~3-10MB/s)安全阈值约 5-8MB**(下载+push 要一起塞进 25s),默认取保守值并在文档注明连接模式影响。超限 → 返回 `{ok: false, error, hint: "用 stage_upload/deliver_staged 异步路径"}`。
- 返回 `{ok, device_path, size, visible_in_gallery: bool, content_uri?: str}`。

### 2. `stage_upload`(异步预备:大本地文件分片)
```
stage_upload(
    content_base64: str,                 # 本片字节(base64)
    stage_id: str | None = None,         # 缺省=新建会话;给定=向该会话追加
    last: bool = False,                  # true=收尾,标记暂存文件完成
    filename: str | None = None,         # 新建会话时用于命名暂存文件
    device: str | None = None,
) -> dict
```
- 仅服务**大本地文件**(无 URL 时):多次调用把字节追加进主机暂存文件,每次 ≤25s。
- 返回 `{ok, stage_id, bytes_received, complete: bool}`。
- url 来源**不走** stage_upload —— 由 `deliver_staged` 内部后台下载(省一轮往返)。

### 3. `deliver_staged`(异步交付)
```
deliver_staged(
    stage_id: str | None = None,         # 与 url 异或:已完成的分片暂存
    url: str | None = None,              # 与 stage_id 异或:主机在后台任务里下载
    device_path: str | None = None,      # 默认 /sdcard/Download/<filename>
    install: bool = False,               # true=push 后 pm install(APK)
    make_visible: bool = True,           # 图片则 push 后扫描进相册
    device: str | None = None,
) -> dict
```
- 起一个**后台 job**:(url 则先下载到暂存)→ `adb push` →(install 则 `pm install` / 图片则媒体扫描)→ 清理暂存。
- 立即返回 `{ok, job_id, state: "running"}`。

### 4. `job_status`(轮询)
```
job_status(job_id: str) -> dict
```
- 返回 `{job_id, kind: "deliver", state: "running"|"succeeded"|"failed",
  device_path?, bytes_total?, bytes_done?, returncode?, error?, started_at, finished_at?}`。
- `bytes_done` 尽力而为(解析 `adb push` 进度输出;拿不到则省略)。

## Data Flow(典型流程)

1. **换背景(小图)**
   `upload_media(content_base64=…, device_path="/sdcard/Pictures/bg.jpg")` → 一次返回,`visible_in_gallery: true`,小红书选图器可见。

2. **装 APK(有 URL)**
   `deliver_staged(url=…, install=True)` → `job_id` → `job_status` 轮询至 `succeeded`。

3. **装 APK(本地大文件)**
   `stage_upload(content_base64=片1)` → `stage_upload(stage_id, content_base64=片N, last=True)` → `deliver_staged(stage_id, install=True)` → `job_status` 轮询。

## Media Visibility(③ 的机制与风险)

图片 push 到 `/sdcard/Pictures/` 后让选图器立刻可见:

- **主方案**:`adb shell am broadcast -a android.intent.action.MEDIA_SCANNER_SCAN_FILE -d file://<device_path>`。该 API 自 29 标记弃用,但 EMUI/华为多数 ROM 仍触发 MediaProvider 扫描。目标机 huawei-vog-al00 = 华为 P30 Pro(EMUI)。
- **兜底**:若广播在该机无效,用 `adb shell content insert --uri content://media/external/images/media …` 直插 MediaStore。注意调用方是 **`adb shell content`(shell uid)**——Android 10+ 普通 app 直插需 `MANAGE_MEDIA` 权限,而 shell uid 不受此限,故兜底必须走 adb shell 而非 app 进程。
- **可见性确认**:`content query --uri content://media/external/images/media --where "_data='<path>'"` 验证已被索引。
- **⚠️ 风险点**:媒体扫描是全设计最不确定处,**实现阶段必须在真机上验证并据结果定稿**(主方案失败则落兜底)。VOG-AL00 为 EMUI 9.x,`MEDIA_SCANNER_SCAN_FILE` 广播实测尚可,但行为依 ROM 版本而异——以真机结果为准。
- **实现注意**:扫描命令用 `_adb_run(["shell","am","broadcast", …])` 的**列表参数**逐项传。注意根因不是 Python 层 `.split()`(`_adb_exec` 的 `shell` 路径是 `["shell", cmd]` 整串传入,并不在 Python 侧切割),而是**整串会交给设备端 shell 再解析**——文件名含空格/特殊字符时需正确引用/转义;用列表参数分项传更稳。

## Error Handling & Security

- **入参异或**:`upload_media` 的 `content_base64`/`url`、`deliver_staged` 的 `stage_id`/`url`——都给或都不给 → 明确报错。
- **base64**:解码失败 → `{ok: false, error}`。
- **url**:仅允许 `http`/`https` scheme;大小上限可配(默认 200MB,超限/缺 `Content-Length` 时边下边计数,超阈值中止);连接/读取超时;轻度 SSRF 防护(拒绝 `localhost`/`127.0.0.0/8`/`169.254.169.254` 等元数据地址)。
- **路径穿越**:`filename` 拒绝路径分隔符与 `..`;`device_path` 校验落在受信前缀(`/sdcard/`)内,暂存路径限定在 `~/.agent-fleet/uploads/`。
- **命令注入**:所有 adb 调用走列表参数(非 shell 字符串拼接)。
- **暂存目录**:写前检查可用空间,**剩余 < 500MB 则拒绝新会话/新 job**(多并发 agent 分片上传会让 `~/.agent-fleet/uploads/` 快速膨胀);分片会话带 TTL(如 30min 未收尾即回收);job 完成/失败后清理临时文件;server 启动时清理残留 `uploads/` 与脱管的 pid(见"孤儿进程处置")。
- **job 注册表**:内存态(server 重启丢失,文档说明);加锁;完成态带 TTL 回收(如 1h)。后台进程用 `Popen` + 守护线程,**不经** 25s 钳制;起始 `_state_registry.touch(serial)`;子进程 PID 落 `uploads/jobs/<job_id>.pid` 以便重启清场。
- **wireless ADB 中断**:后台 push 中断 → job 置 `failed` 并带 returncode/stderr。

## Files

- **新增** `platforms/android/server/_uploads.py` —— 暂存目录管理、分片会话、后台 job 注册表 + `_adb_popen` runner、媒体扫描 helper、校验 helper(异或/base64/路径穿越/url)。把重逻辑从主文件剥离,保持 `android_device_mcp.py` 精简。
- **改** `platforms/android/server/android_device_mcp.py` —— 新增 4 个薄 `@mcp.tool` 包装(`upload_media`/`stage_upload`/`deliver_staged`/`job_status`),复用 `_resolve_device`/`_state_registry`/`_adb_run`。
- **新增** `platforms/android/server/tests/test_uploads.py` —— 单测。
- **改文档**:android 工具清单 + 工具计数(架构文档现写 "25 tools" → 29);`using-android` skill 增补上传用法;CHANGELOG。

## Testing

- **单测**(mock subprocess):异或校验、base64 解码失败、路径穿越拒绝、url scheme/SSRF 拒绝、分片会话追加+收尾、job 状态机迁移(running→succeeded/failed)、暂存清理。
- **真机**(huawei-vog-al00,按既有约定自主验证):
  1. `upload_media` 小图 → 设备有文件 + `content query` 确认 MediaStore 已索引 + 选图器可见。
  2. 异步:分片上传较大文件 → `deliver_staged(stage_id)` → `job_status` 轮询 → 设备校验。
  3. APK:`deliver_staged(url, install=True)` → 轮询 → `pm list packages` 确认安装;再验本地分片 + `deliver_staged(stage_id, install=True)`。
  4. **媒体扫描机制单独验证**(最高风险项):主方案不行则切兜底,据结果定稿。
- **质量门禁**:实现后派 code-reviewer 复核,无阻断再合并主分支。

## Out of Scope / Future

- **iOS**:模型不同(`push_file_to_app` 为 app 沙盒级,相册注入另一套机制),列为后续并行项。
- **重构 `install_app`**:其大文件异步化复用本设计的 job 运行器,留作后续小改,本轮不动。
- **>200MB 断点续传 / 进度条**:url + 分片已够用;真正超大文件留作后续。
- **跨 MCP 复用 desktop-commander 的 start_process** 来跑后台 adb:本设计选择 android-device 自给自足,不依赖 host 是否部署 desktop-commander。

# wizard 模式下 setup 脚本零交互 — 设计

**日期**: 2026-05-14
**状态**: 设计已确认，待写实施计划

## 问题

`agent-fleet setup` wizard 调用平台 setup 脚本时，用 `subprocess.Popen(stdout=PIPE, stderr=STDOUT, bufsize=1)` 捕获脚本输出，逐行 `readline()` 包装成 `InstallEvent` 美化显示（`cli/src/fleet/installers/{windows,macos,linux}.py`）。

但这与脚本内的交互式 prompt 冲突：

- `readline()` 按 `\n` 切分；PowerShell 的 `Read-Host` prompt **不带换行符** → prompt 文本卡在管道 buffer 里出不来。
- 子进程与 wizard **共享同一个 stdin**（`Popen` 未设 `stdin=`）→ 用户输入被谁读走不确定。

实测现象（用户在 Windows 上跑 `setup-android.ps1`）：
1. `reuse it? [Y/n]:` prompt 夹在 config 文件内容中间，位置错乱。
2. 在 reuse prompt 处输入 `n` 没反应。
3. ADB 模式选择是裸 `Read-Host "mode [1/2/3]"`，与 wizard 其余步骤的 questionary 选择风格不一致。

三个现象是**同一个根因**的不同表现。bash 脚本作者曾用"prompt 必须带换行符"workaround（`setup-android.sh:196-200` 注释），让 bash 版勉强能用，但 PowerShell 的 `Read-Host` 无法加换行，问题在 Windows 上完整暴露。

## 受影响的交互点

| 脚本 | 交互点 | wizard 模式下表现 |
|---|---|---|
| `setup-android.ps1` | config reuse 判断 (`Read-Host`)、ADB mode 选择 (`Read-Host 1/2/3`) | 卡死 / 错乱 |
| `setup-android.sh` | 同上（`read`） | 靠 `echo` 带换行勉强能用 |
| `setup-android-linux.sh` | 同上（`read`） | 同上 |
| `setup-windows.ps1` | L109 `Read-Host "Press Enter to continue"`（仅 Tailscale CLI 未装时触发） | 卡死 |
| `setup-macos.sh` | 无交互 | — |

## 核心原则

**所有需要用户输入的交互都在 Python wizard（questionary）里完成。** setup 脚本退化成"参数驱动 + 独立运行时 fallback 交互"。wizard 模式下脚本不出现任何 `Read-Host` / `read`。

## 设计

### 1. 传参机制：环境变量

wizard 通过 `subprocess.Popen(env=...)` 把用户选择传给脚本。

| env var | 值 | 含义 |
|---|---|---|
| `ATB_WIZARD_MANAGED` | `1` | 标记"由 wizard 调用"——脚本据此跳过所有 `Read-Host`/`read` 暂停点 |
| `ATB_ANDROID_MODE` | `usb` / `wireless` / `hybrid` | wizard 收集的 ADB 连接模式 |
| `ATB_ANDROID_REUSE_CONFIG` | `1` | 复用现有 `~/.atb-android/config.toml`，脚本跳过 mode 选择与写 config |

选环境变量而非命令行参数：不改脚本签名、跨 PowerShell/bash 一致、`Popen(env=)` 原生支持。命名沿用现有 `ATB_ANDROID_ADB` / `ATB_ANDROID_SERIAL` 前缀风格。

env 传递时以**当前进程环境为基底再叠加**（`env={**os.environ, ...}`），避免丢失 PATH 等。

### 2. wizard 端（`cli/src/fleet/cli.py` + 3 个 installers）

wizard 与 setup 脚本运行在**同一台 device host** 上（`install.sh`/`install.ps1` 在被控设备上启动 wizard），所以 wizard 能直接 stat `~/.atb-android/config.toml`。

android-device role 选中后、调 setup 脚本**之前**，wizard：

- 检测 `~/.atb-android/config.toml`：
  - **存在** → 打印文件内容 + `questionary.confirm("复用现有配置？")`
    - 复用 → 传 `ATB_ANDROID_REUSE_CONFIG=1`
    - 不复用 → 继续问 mode ↓
  - **不存在 / 不复用** → `questionary.select("ADB 连接模式", choices=[USB / Wireless / Hybrid])` → 传 `ATB_ANDROID_MODE=<选中值>`
- 所有 installer（win-device / mac-device / android-device 各平台）调 setup 脚本时统一带 `ATB_WIZARD_MANAGED=1`。

config.toml 的存在检测、内容打印、reuse 询问都在 wizard 里用 Python 完成——无 PowerShell buffering race。

### 3. setup 脚本端

**3 个 android 脚本** 的 "ADB connection mode" 步骤改为：

```
if  ATB_ANDROID_REUSE_CONFIG 有值: 用现有 config，不交互、不重写
elif ATB_ANDROID_MODE 有值:        用它写 config，不交互
else:                              fallback —— 保留原交互逻辑（独立跑脚本时）
```

`ATB_ANDROID_MODE` 值非法（不在 usb/wireless/hybrid 内）时，脚本报错 exit 非 0，不静默接受。

**`setup-windows.ps1` L109**（Tailscale CLI 未装时的 `Read-Host "Press Enter"`）：

```
if ATB_WIZARD_MANAGED 有值: 打印 "Tailscale 刚装好，请在系统托盘登录后重新运行 wizard" → exit 1
else:                       保留原 Read-Host 暂停（独立跑脚本时）
```

wizard 模式下无法"按回车继续"，最干净的做法是退出，让 wizard 显示明确的退出原因，用户登录 Tailscale 后重跑。

### 4. 两条路径都根治

- **wizard 模式**：脚本零交互 → 无 pipe race。
- **独立运行脚本**：走 fallback 交互 → stdout 直通终端 → 本来就无 race。

### 5. 跨平台一致

3 个 android 脚本（`.ps1` / `.sh` / `-linux.sh`）统一改成参数驱动。bash 版虽然现在"勉强能用"，也一起改，彻底消除 race 隐患并保持三平台逻辑一致。

## 涉及文件

**修改**:
- `cli/src/fleet/cli.py` — android-device 选中后插入 questionary（config reuse / ADB mode）
- `cli/src/fleet/installers/windows.py` — `_run_setup_ps1` 接受并传递 env；`ATB_WIZARD_MANAGED=1`
- `cli/src/fleet/installers/macos.py` — setup runner 传 env
- `cli/src/fleet/installers/linux.py` — setup runner 传 env
- `platforms/android/scripts/setup-android.ps1` — ADB mode 步骤参数驱动 + fallback
- `platforms/android/scripts/setup-android.sh` — 同上
- `platforms/android/scripts/setup-android-linux.sh` — 同上
- `platforms/windows/scripts/setup-windows.ps1` — L109 Read-Host 在 wizard 模式下改 exit 1

**版本**: bump 0.6.13 → 0.6.14；CHANGELOG 新增 entry。

## 非目标 / scope 边界

- 不改 wizard 输出捕获机制本身（`stdout=PIPE` + readline 美化保留）——只是让脚本在 wizard 模式下不产生需要 stdin 的 prompt。
- 不重做 config.toml 格式。
- 不动 `setup-macos.sh`（无交互点）。

## 测试

- **可单元测**: wizard 端构造 env dict 的逻辑（给定 config 存在/不存在 + 用户选择 → 期望的 env var 集合）。
- **手动验证 + reviewer**: 脚本的参数驱动分支与 fallback 分支（涉及 subprocess + questionary，自动化成本高）。
  - wizard 模式：questionary 选 mode → 脚本无交互、config 写对。
  - 独立运行：不带 env var 跑脚本 → fallback 交互正常。
- 真机验证：在 `win-personal-qjl` 上跑完整 wizard 流程确认三个原始现象消失。

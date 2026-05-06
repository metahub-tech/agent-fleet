"""Windows GUI MCP Server.

暴露 Windows 桌面控制能力给 Claude Code：截屏、键鼠、窗口/控件树、
进程管理、PowerShell 执行。

通过 FastMCP 的 SSE 传输监听 0.0.0.0:8766，靠 Windows 防火墙 + Tailscale
ACL 限制只有 tailnet 内节点可达。
"""

from __future__ import annotations

import contextlib
import io
import subprocess
from typing import Annotated, Optional

import psutil
import pyautogui
import pyperclip
from PIL import ImageGrab
from pydantic import Field

from fastmcp import FastMCP
from fastmcp.utilities.types import Image

from pywinauto import Desktop

# 关掉 pyautogui 的"鼠标到角落=终止"安全机制（远程调试时容易误触发）
pyautogui.FAILSAFE = False
pyautogui.PAUSE = 0.05


mcp = FastMCP("windows-gui")


# ---------- 屏幕 / 视觉 ----------

@mcp.tool
def get_screen_size() -> dict:
    """返回主屏幕逻辑分辨率（不含 DPI 缩放推算）。"""
    w, h = pyautogui.size()
    return {"width": w, "height": h}


@mcp.tool
def take_screenshot(
    region: Annotated[
        Optional[tuple[int, int, int, int]],
        Field(description="(left, top, right, bottom) 截取矩形；None 则整屏"),
    ] = None,
) -> Image:
    """截屏并返回 PNG 图像。"""
    img = ImageGrab.grab(bbox=region) if region else ImageGrab.grab()
    buf = io.BytesIO()
    img.save(buf, format="PNG")
    return Image(data=buf.getvalue(), format="png")


# ---------- 窗口 / 控件树 ----------

@mcp.tool
def list_windows() -> list[dict]:
    """列出所有可见的顶层窗口（标题、类名、矩形、PID）。"""
    out: list[dict] = []
    for w in Desktop(backend="uia").windows():
        try:
            if w.is_visible() and w.window_text():
                r = w.rectangle()
                out.append({
                    "title": w.window_text(),
                    "class_name": w.class_name(),
                    "left": r.left,
                    "top": r.top,
                    "right": r.right,
                    "bottom": r.bottom,
                    "pid": w.process_id(),
                })
        except Exception:
            continue
    return out


@mcp.tool
def inspect_window(
    title_substring: Annotated[str, Field(description="标题包含此子串的窗口")],
    max_depth: Annotated[int, Field(description="控件树最大深度", ge=1, le=10)] = 4,
) -> str:
    """打印指定窗口的 UIA 控件树，用于定位按钮/输入框等元素。"""
    try:
        win = Desktop(backend="uia").window(title_re=f".*{title_substring}.*")
        win.wait("visible", timeout=3)
        buf = io.StringIO()
        with contextlib.redirect_stdout(buf):
            win.print_control_identifiers(depth=max_depth)
        return buf.getvalue()
    except Exception as e:
        return f"ERROR: {type(e).__name__}: {e}"


@mcp.tool
def focus_window(
    title_substring: Annotated[str, Field(description="标题包含此子串的窗口")],
) -> dict:
    """把指定窗口拉到前台并设为焦点。"""
    try:
        win = Desktop(backend="uia").window(title_re=f".*{title_substring}.*")
        win.set_focus()
        return {"ok": True, "title": win.window_text()}
    except Exception as e:
        return {"ok": False, "error": f"{type(e).__name__}: {e}"}


# ---------- 鼠标 / 键盘 ----------

@mcp.tool
def click(
    x: Annotated[int, Field(description="屏幕 x 坐标")],
    y: Annotated[int, Field(description="屏幕 y 坐标")],
    button: Annotated[str, Field(description="left / right / middle")] = "left",
    clicks: Annotated[int, Field(ge=1, le=3)] = 1,
) -> dict:
    """在屏幕坐标点击鼠标。"""
    pyautogui.click(x=x, y=y, clicks=clicks, button=button)
    return {"ok": True, "x": x, "y": y, "button": button, "clicks": clicks}


@mcp.tool
def move_mouse(
    x: int,
    y: int,
    duration: Annotated[float, Field(description="移动耗时秒，0=瞬移")] = 0.0,
) -> dict:
    """移动鼠标到指定坐标。"""
    pyautogui.moveTo(x, y, duration=duration)
    return {"ok": True, "x": x, "y": y}


@mcp.tool
def type_text(
    text: Annotated[str, Field(description="ASCII 文本")],
    interval: Annotated[float, Field(description="每个字符间隔秒")] = 0.02,
) -> dict:
    """在当前焦点位置键入文本。仅 ASCII；中文请用 paste_text。"""
    pyautogui.typewrite(text, interval=interval)
    return {"ok": True, "len": len(text)}


@mcp.tool
def paste_text(
    text: Annotated[str, Field(description="任意文本，含中文/Unicode")],
) -> dict:
    """通过剪贴板 + Ctrl+V 输入文本，支持中文。"""
    pyperclip.copy(text)
    pyautogui.hotkey("ctrl", "v")
    return {"ok": True, "len": len(text)}


@mcp.tool
def press_key(
    keys: Annotated[
        str,
        Field(description="单键或组合键，例：'enter' / 'ctrl+s' / 'alt+f4' / 'win+d'"),
    ],
) -> dict:
    """按下键或组合键。"""
    parts = [k.strip() for k in keys.split("+")]
    if len(parts) == 1:
        pyautogui.press(parts[0])
    else:
        pyautogui.hotkey(*parts)
    return {"ok": True, "keys": keys}


# ---------- 进程 / 应用 ----------

@mcp.tool
def launch_app(
    path: Annotated[str, Field(description="可执行文件路径或 PATH 中的命令")],
    args: Annotated[Optional[list[str]], Field(description="命令行参数列表")] = None,
) -> dict:
    """启动 Windows 应用程序，返回 PID。"""
    cmd = [path, *(args or [])]
    p = subprocess.Popen(cmd, shell=False)
    return {"pid": p.pid, "cmd": cmd}


@mcp.tool
def kill_process(pid: int) -> dict:
    """根据 PID 杀进程。"""
    p = psutil.Process(pid)
    name = p.name()
    p.kill()
    return {"ok": True, "pid": pid, "name": name}


@mcp.tool
def list_processes(
    name_filter: Annotated[
        Optional[str],
        Field(description="进程名包含此子串才返回；None=全部"),
    ] = None,
) -> list[dict]:
    """列出运行中进程的概要信息。"""
    out: list[dict] = []
    for p in psutil.process_iter(["pid", "name", "username", "memory_percent"]):
        try:
            info = p.info
            if name_filter is None or (
                info["name"] and name_filter.lower() in info["name"].lower()
            ):
                out.append(info)
        except (psutil.NoSuchProcess, psutil.AccessDenied):
            continue
    return out


# ---------- Shell ----------

@mcp.tool
def run_powershell(
    script: Annotated[str, Field(description="PowerShell 脚本内容")],
    timeout: Annotated[int, Field(ge=1, le=600)] = 60,
) -> dict:
    """执行 PowerShell 脚本，返回 stdout/stderr/退出码。"""
    r = subprocess.run(
        ["powershell", "-NoProfile", "-NonInteractive", "-Command", script],
        capture_output=True,
        text=True,
        timeout=timeout,
        encoding="utf-8",
        errors="replace",
    )
    return {
        "returncode": r.returncode,
        "stdout": r.stdout,
        "stderr": r.stderr,
    }


if __name__ == "__main__":
    # 监听所有接口，由 Windows 防火墙限制只有 Tailscale 接口可达
    mcp.run(transport="sse", host="0.0.0.0", port=8766)

"""与桌宠统一风格的音量面板，通过 stdout 回传设置。"""

from pathlib import Path
from threading import Lock
from typing import Any, Callable, Dict, Optional
from ctypes import wintypes

import argparse
import ctypes
import json
import math
import os
import sys


def checked_volume(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("音量必须是数字")
    volume = float(value)
    if not math.isfinite(volume) or not 0 <= volume <= 100:
        raise ValueError("音量必须为 0～100%")
    return round(volume, 2)


class VolumeApi:
    """只开放音量、就绪和关闭操作，页面不能执行任意窗口指令。"""

    def __init__(self, initial: float, emit: Callable[[Dict[str, Any]], None], smoke_test: bool = False) -> None:
        self._volume = checked_volume(initial)
        self._emit = emit
        self._smoke_test = smoke_test
        self._lock = Lock()
        self._window: Optional[Any] = None

    def _prepare(self, window: Any) -> None:
        """透明 WebView 不能带系统 Mica 底板，整个客户区由 DWM 合成。"""
        from Microsoft.Win32 import SystemEvents
        from System.Drawing import Color

        SystemEvents.UserPreferenceChanged -= window.native.on_system_theme_changed
        hwnd = window.native.Handle.ToInt64()
        dwm = ctypes.WinDLL("dwmapi")
        dwm.DwmSetWindowAttribute.argtypes = [wintypes.HANDLE, wintypes.DWORD, ctypes.c_void_p, wintypes.DWORD]
        dwm.DwmSetWindowAttribute.restype = wintypes.LONG
        if sys.getwindowsversion().build >= 22621:
            backdrop = ctypes.c_int(1)
            result = dwm.DwmSetWindowAttribute(hwnd, 38, ctypes.byref(backdrop), ctypes.sizeof(backdrop))
            if result:
                raise OSError(f"关闭音量面板系统背景失败: 0x{result & 0xFFFFFFFF:08X}")
        window.native.BackColor = Color.Black
        margins = (ctypes.c_int * 4)(-1, -1, -1, -1)
        dwm.DwmExtendFrameIntoClientArea.argtypes = [wintypes.HANDLE, ctypes.c_void_p]
        dwm.DwmExtendFrameIntoClientArea.restype = wintypes.LONG
        result = dwm.DwmExtendFrameIntoClientArea(hwnd, ctypes.byref(margins))
        if result:
            raise OSError(f"启用音量面板透明背景失败: 0x{result & 0xFFFFFFFF:08X}")

    def fit(self, scale: float) -> None:
        """以页面实际 DPR 校正尺寸，包含 Windows 文本缩放，防止内容挤出滚动条。"""
        if not math.isfinite(scale) or not 0.5 <= scale <= 8:
            raise ValueError("无效的窗口缩放倍率")
        if self._window is None:
            raise RuntimeError("音量面板尚未创建")
        user = ctypes.WinDLL("user32", use_last_error=True)
        user.SetWindowPos.argtypes = [wintypes.HANDLE, wintypes.HANDLE, ctypes.c_int, ctypes.c_int,
                                      ctypes.c_int, ctypes.c_int, wintypes.UINT]
        user.SetWindowPos.restype = wintypes.BOOL
        if not user.SetWindowPos(self._window.native.Handle.ToInt64(), None, 0, 0,
                                 round(400 * scale), round(454 * scale), 0x0016):
            raise ctypes.WinError(ctypes.get_last_error())

    def get_state(self) -> Dict[str, Any]:
        with self._lock:
            return {"volume": self._volume, "smoke_test": self._smoke_test}

    def set_volume(self, value: float) -> Dict[str, float]:
        volume = checked_volume(value)
        with self._lock:
            self._emit({"type": "volume", "value": volume})
            self._volume = volume
        return {"volume": volume}

    def ready(self) -> None:
        self._emit({"type": "ready"})

    def close(self) -> None:
        if self._window is None:
            raise RuntimeError("音量面板尚未创建")
        self._window.destroy()


def run_window(initial: float, smoke_test: bool = False, preview: bool = False) -> None:
    checked_volume(initial)
    # stdout 是插件协议；WebView2 和底层库的日志只能进入 stderr。
    protocol = open(os.dup(1), "w", encoding="utf-8", newline="\n")
    os.dup2(2, 1)
    sys.stdout = sys.stderr
    output_lock = Lock()
    def emit(event: Dict[str, Any]) -> None:
        with output_lock:
            protocol.write(json.dumps(event) + "\n")
            protocol.flush()

    import webview

    api = VolumeApi(initial, emit, smoke_test)
    api._window = webview.create_window(
        "钢管音量 · 预览" if preview else "钢管音量",
        url=(Path(__file__).resolve().parent / "web" / "volume.html").as_uri(),
        js_api=api, width=400, height=454, min_size=(400, 454),
        frameless=True, easy_drag=False, resizable=False, transparent=True,
        on_top=True, shadow=False, hidden=smoke_test,
    )
    api._window.events.before_show += api._prepare
    try:
        webview.start(gui="edgechromium", private_mode=True)
    finally:
        protocol.close()


if __name__ == "__main__":
    parser = argparse.ArgumentParser()
    parser.add_argument("--volume", type=float, default=1)
    parser.add_argument("--smoke-test", action="store_true")
    parser.add_argument("--preview", action="store_true")
    arguments = parser.parse_args()
    if sys.platform != "win32":
        raise RuntimeError("音量面板仅支持 Windows")
    run_window(arguments.volume, arguments.smoke_test, arguments.preview)

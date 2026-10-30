"""短生命周期、鼠标穿透的小麦麦窗口；只依赖 Windows API 和 Python 标准库。"""

from ctypes import wintypes
from dataclasses import dataclass
from pathlib import Path
from typing import Optional

import argparse
import ctypes
import math
import random
import struct
import sys
import time
import zlib

SPRITE = Path(__file__).resolve().parent / "assets" / "mini_maimai.png"
MINI_WIDTH = 75
MINI_HEIGHT = 54


@dataclass
class FallingMotion:
    x: float
    y: float
    floor: float
    left: float
    right: float
    scale: float = 1.0
    vx: float = 40.0
    vy: float = 0.0
    resting: bool = False

    def step(self, seconds: float) -> None:
        if self.resting:
            return
        delta = max(0.0, min(seconds, 0.05))
        self.vy += 1600 * self.scale * delta
        self.x += self.vx * delta
        self.y += self.vy * delta
        if self.x < self.left or self.x > self.right:
            self.x = min(max(self.x, self.left), self.right)
            self.vx *= -0.6
        if self.y >= self.floor:
            self.y = self.floor
            self.vy *= -0.42
            self.vx *= 0.6
            if abs(self.vy) < 70 * self.scale:
                self.resting = True


def render_sprite(pixels: ctypes.c_void_p, width: int, height: int) -> None:
    """GDI+ 高质量缩放原图，直接写入分层窗口使用的预乘 BGRA 缓冲区。"""
    library = ctypes.WinDLL("gdiplus")
    handle = ctypes.c_void_p

    class StartupInput(ctypes.Structure):
        _fields_ = [("version", wintypes.UINT), ("callback", handle),
                    ("suppress_thread", wintypes.BOOL), ("suppress_codecs", wintypes.BOOL)]

    signatures = [
        ("GdiplusStartup", [ctypes.POINTER(ctypes.c_size_t), ctypes.POINTER(StartupInput), handle], ctypes.c_int),
        ("GdiplusShutdown", [ctypes.c_size_t], None),
        ("GdipLoadImageFromFile", [wintypes.LPCWSTR, ctypes.POINTER(handle)], ctypes.c_int),
        ("GdipCreateBitmapFromScan0", [ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, handle, ctypes.POINTER(handle)], ctypes.c_int),
        ("GdipGetImageGraphicsContext", [handle, ctypes.POINTER(handle)], ctypes.c_int),
        ("GdipSetInterpolationMode", [handle, ctypes.c_int], ctypes.c_int),
        ("GdipSetPixelOffsetMode", [handle, ctypes.c_int], ctypes.c_int),
        ("GdipSetCompositingMode", [handle, ctypes.c_int], ctypes.c_int),
        ("GdipGraphicsClear", [handle, wintypes.DWORD], ctypes.c_int),
        ("GdipDrawImageRectI", [handle, handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int], ctypes.c_int),
        ("GdipFlush", [handle, ctypes.c_int], ctypes.c_int),
        ("GdipDeleteGraphics", [handle], ctypes.c_int),
        ("GdipDisposeImage", [handle], ctypes.c_int),
    ]
    for name, arguments, result in signatures:
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, result

    def checked(result: int, operation: str) -> None:
        if result:
            raise RuntimeError(f"{operation} 失败: GDI+ status={result}")

    token = ctypes.c_size_t()
    checked(library.GdiplusStartup(ctypes.byref(token), ctypes.byref(StartupInput(version=1)), None), "GdiplusStartup")
    image, surface, graphics = handle(), handle(), handle()
    try:
        checked(library.GdipLoadImageFromFile(str(SPRITE), ctypes.byref(image)), "读取主桌宠原图")
        checked(library.GdipCreateBitmapFromScan0(width, height, width * 4, 0x000E200B, pixels, ctypes.byref(surface)), "创建透明画布")
        checked(library.GdipGetImageGraphicsContext(surface, ctypes.byref(graphics)), "创建绘图上下文")
        checked(library.GdipSetInterpolationMode(graphics, 7), "设置高质量缩放")
        checked(library.GdipSetPixelOffsetMode(graphics, 4), "设置像素对齐")
        checked(library.GdipSetCompositingMode(graphics, 1), "设置透明通道复制")
        checked(library.GdipGraphicsClear(graphics, 0), "清空透明画布")
        checked(library.GdipDrawImageRectI(graphics, image, 0, 0, width, height), "缩放主桌宠原图")
        checked(library.GdipFlush(graphics, 1), "完成绘制")
    finally:
        if graphics.value:
            library.GdipDeleteGraphics(graphics)
        if surface.value:
            library.GdipDisposeImage(surface)
        if image.value:
            library.GdipDisposeImage(image)
        library.GdiplusShutdown(token)


def run_window(offset_x: int, offset_y: int, scale: float, lifetime: float, preview: Optional[Path]) -> None:
    user = ctypes.WinDLL("user32", use_last_error=True)
    gdi = ctypes.WinDLL("gdi32", use_last_error=True)
    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    handle = wintypes.HANDLE
    intptr = ctypes.c_ssize_t
    uintptr = ctypes.c_size_t
    wndproc_type = ctypes.WINFUNCTYPE(intptr, handle, wintypes.UINT, uintptr, intptr)

    class WndClass(ctypes.Structure):
        _fields_ = [
            ("style", wintypes.UINT), ("wndproc", wndproc_type), ("cls_extra", ctypes.c_int),
            ("wnd_extra", ctypes.c_int), ("instance", handle), ("icon", handle),
            ("cursor", handle), ("background", handle), ("menu_name", wintypes.LPCWSTR),
            ("class_name", wintypes.LPCWSTR),
        ]

    class BlendFunction(ctypes.Structure):
        _fields_ = [("operation", ctypes.c_ubyte), ("flags", ctypes.c_ubyte),
                    ("opacity", ctypes.c_ubyte), ("alpha_format", ctypes.c_ubyte)]

    class MonitorInfo(ctypes.Structure):
        _fields_ = [("size", wintypes.DWORD), ("monitor", wintypes.RECT), ("work", wintypes.RECT), ("flags", wintypes.DWORD)]

    # 明确声明每个指针参数和返回类型，防止 64 位窗口句柄被 ctypes 默认的 int 截断。
    signatures = [
        (kernel, "GetModuleHandleW", [wintypes.LPCWSTR], handle),
        (user, "SetProcessDpiAwarenessContext", [handle], wintypes.BOOL),
        (user, "GetCursorPos", [ctypes.POINTER(wintypes.POINT)], wintypes.BOOL),
        (user, "MonitorFromPoint", [wintypes.POINT, wintypes.DWORD], handle),
        (user, "GetMonitorInfoW", [handle, ctypes.POINTER(MonitorInfo)], wintypes.BOOL),
        (user, "RegisterClassW", [ctypes.POINTER(WndClass)], wintypes.ATOM),
        (user, "UnregisterClassW", [wintypes.LPCWSTR, handle], wintypes.BOOL),
        (user, "CreateWindowExW", [wintypes.DWORD, wintypes.LPCWSTR, wintypes.LPCWSTR, wintypes.DWORD,
                                    ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int,
                                    handle, handle, handle, ctypes.c_void_p], handle),
        (user, "DefWindowProcW", [handle, wintypes.UINT, uintptr, intptr], intptr),
        (user, "UpdateLayeredWindow", [handle, handle, ctypes.POINTER(wintypes.POINT), ctypes.POINTER(wintypes.SIZE),
                                       handle, ctypes.POINTER(wintypes.POINT), wintypes.DWORD,
                                       ctypes.POINTER(BlendFunction), wintypes.DWORD], wintypes.BOOL),
        (user, "SetWindowPos", [handle, handle, ctypes.c_int, ctypes.c_int, ctypes.c_int, ctypes.c_int, wintypes.UINT], wintypes.BOOL),
        (user, "SetTimer", [handle, uintptr, wintypes.UINT, ctypes.c_void_p], uintptr),
        (user, "KillTimer", [handle, uintptr], wintypes.BOOL),
        (user, "DestroyWindow", [handle], wintypes.BOOL),
        (user, "PostQuitMessage", [ctypes.c_int], None),
        (user, "GetMessageW", [ctypes.POINTER(wintypes.MSG), handle, wintypes.UINT, wintypes.UINT], ctypes.c_int),
        (user, "TranslateMessage", [ctypes.POINTER(wintypes.MSG)], wintypes.BOOL),
        (user, "DispatchMessageW", [ctypes.POINTER(wintypes.MSG)], intptr),
        (user, "GetDC", [handle], handle), (user, "ReleaseDC", [handle, handle], ctypes.c_int),
        (gdi, "CreateCompatibleDC", [handle], handle),
        (gdi, "CreateDIBSection", [handle, ctypes.c_void_p, wintypes.UINT, ctypes.POINTER(ctypes.c_void_p), handle, wintypes.DWORD], handle),
        (gdi, "SelectObject", [handle, handle], handle),
        (gdi, "DeleteObject", [handle], wintypes.BOOL), (gdi, "DeleteDC", [handle], wintypes.BOOL),
    ]
    for library, name, args, result in signatures:
        function = getattr(library, name)
        function.argtypes, function.restype = args, result

    user.SetProcessDpiAwarenessContext(handle(-4))
    point = wintypes.POINT()
    if not user.GetCursorPos(ctypes.byref(point)):
        raise ctypes.WinError(ctypes.get_last_error())
    point.x += offset_x
    point.y += offset_y
    monitor = MonitorInfo(size=ctypes.sizeof(MonitorInfo))
    if not user.GetMonitorInfoW(user.MonitorFromPoint(point, 2), ctypes.byref(monitor)):
        raise ctypes.WinError(ctypes.get_last_error())
    width, height = round(MINI_WIDTH * scale), round(MINI_HEIGHT * scale)
    work = monitor.work
    left, right = work.left, max(work.left, work.right - width)
    floor = work.bottom - height - round(3 * scale)
    motion = FallingMotion(
        x=min(max(point.x - width / 2, left), right), y=min(point.y - height / 2, floor),
        floor=floor, left=left, right=right, scale=scale, vx=random.uniform(-65, 65) * scale,
    )
    screen = user.GetDC(None)
    dc = gdi.CreateCompatibleDC(screen)
    info = ctypes.create_string_buffer(struct.pack("<IiiHHIIiiII", 40, width, -height, 1, 32, 0, 0, 0, 0, 0, 0))
    pixels = ctypes.c_void_p()
    bitmap = gdi.CreateDIBSection(screen, info, 0, ctypes.byref(pixels), None, 0)
    user.ReleaseDC(None, screen)
    if not dc or not bitmap or not pixels.value:
        if bitmap:
            gdi.DeleteObject(bitmap)
        if dc:
            gdi.DeleteDC(dc)
        raise ctypes.WinError(ctypes.get_last_error())
    original_bitmap = gdi.SelectObject(dc, bitmap)
    created = time.monotonic()
    previous = created
    callback_error = []

    def present(window: int, opacity: int) -> None:
        position = wintypes.POINT(round(motion.x), round(motion.y))
        size, origin = wintypes.SIZE(width, height), wintypes.POINT(0, 0)
        blend = BlendFunction(0, 0, opacity, 1)
        if not user.UpdateLayeredWindow(window, None, ctypes.byref(position), ctypes.byref(size), dc,
                                        ctypes.byref(origin), 0, ctypes.byref(blend), 2):
            raise ctypes.WinError(ctypes.get_last_error())

    @wndproc_type
    def procedure(hwnd: int, message: int, wparam: int, lparam: int) -> int:
        nonlocal previous
        try:
            if message == 0x0084:  # WM_NCHITTEST / HTTRANSPARENT
                return -1
            if message == 0x0014:  # WM_ERASEBKGND
                return 1
            if message == 0x0113:  # WM_TIMER
                now = time.monotonic()
                elapsed = now - created
                if elapsed >= lifetime:
                    user.DestroyWindow(hwnd)
                    return 0
                motion.step(now - previous)
                previous = now
                alpha = round(255 * min(1, (lifetime - elapsed) / 0.5))
                present(hwnd, alpha)
                return 0
            if message == 0x0002:  # WM_DESTROY
                user.KillTimer(hwnd, 1)
                user.PostQuitMessage(0)
                return 0
            return user.DefWindowProcW(hwnd, message, wparam, lparam)
        except Exception as exc:
            # ctypes 回调异常不能传出原生调用栈；结束消息循环后由 Python 完整抛出。
            callback_error.append(exc)
            user.PostQuitMessage(1)
            return 0

    instance = kernel.GetModuleHandleW(None)
    class_name = "MaimaiSprinkles"
    registered = False
    hwnd = None
    try:
        render_sprite(pixels, width, height)
        if preview is not None:
            bgra = ctypes.string_at(pixels, width * height * 4)
            rows = bytearray()
            for y in range(height):
                rows.append(0)
                for x in range(width):
                    start = (y * width + x) * 4
                    b, green, r, alpha = bgra[start:start + 4]
                    # 预览 PNG 使用普通 RGBA，窗口缓冲区保持预乘格式。
                    rows.extend((min(255, round(r * 255 / alpha)), min(255, round(green * 255 / alpha)),
                                 min(255, round(b * 255 / alpha)), alpha) if alpha else (0, 0, 0, 0))
            def chunk(kind: bytes, data: bytes) -> bytes:
                return struct.pack(">I", len(data)) + kind + data + struct.pack(">I", zlib.crc32(kind + data))
            preview.write_bytes(
                b"\x89PNG\r\n\x1a\n" + chunk(b"IHDR", struct.pack(">IIBBBBB", width, height, 8, 6, 0, 0, 0))
                + chunk(b"IDAT", zlib.compress(rows)) + chunk(b"IEND", b"")
            )
            return
        definition = WndClass(wndproc=procedure, instance=instance, class_name=class_name)
        if not user.RegisterClassW(ctypes.byref(definition)):
            raise ctypes.WinError(ctypes.get_last_error())
        registered = True
        hwnd = user.CreateWindowExW(
            0x00080000 | 0x00000020 | 0x00000080 | 0x08000000,
            class_name, "小麦麦", 0x80000000, round(motion.x), round(motion.y), width, height,
            None, None, instance, None,
        )
        if not hwnd:
            raise ctypes.WinError(ctypes.get_last_error())
        present(hwnd, 255)
        if not user.SetWindowPos(hwnd, handle(-1), 0, 0, 0, 0, 0x0053):
            raise ctypes.WinError(ctypes.get_last_error())
        if not user.SetTimer(hwnd, 1, 16, None):
            raise ctypes.WinError(ctypes.get_last_error())
        msg = wintypes.MSG()
        while (result := user.GetMessageW(ctypes.byref(msg), None, 0, 0)) != 0:
            if result == -1:
                raise ctypes.WinError(ctypes.get_last_error())
            user.TranslateMessage(ctypes.byref(msg))
            user.DispatchMessageW(ctypes.byref(msg))
        if callback_error:
            raise callback_error[0]
    finally:
        if hwnd:
            user.DestroyWindow(hwnd)
        if registered:
            user.UnregisterClassW(class_name, instance)
        gdi.SelectObject(dc, original_bitmap)
        gdi.DeleteObject(bitmap)
        gdi.DeleteDC(dc)


def main() -> None:
    parser = argparse.ArgumentParser()
    parser.add_argument("--offset-x", type=int, default=0)
    parser.add_argument("--offset-y", type=int, default=30)
    parser.add_argument("--scale", type=float, default=1)
    parser.add_argument("--lifetime", type=float, default=5)
    parser.add_argument("--preview", type=Path)
    args = parser.parse_args()
    if sys.platform != "win32":
        raise RuntimeError("小麦麦动画窗口仅支持 Windows")
    if not math.isfinite(args.scale) or not 0.5 <= args.scale <= 8:
        raise ValueError("scale 应为 0.5～8 的有限数值")
    if not math.isfinite(args.lifetime) or not 1 <= args.lifetime <= 15:
        raise ValueError("lifetime 应为 1～15 秒")
    run_window(args.offset_x, args.offset_y, args.scale, args.lifetime, args.preview)


if __name__ == "__main__":
    main()

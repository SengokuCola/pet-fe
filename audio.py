"""每次播放使用独立的 Windows 音频句柄，允许同一音效重叠。"""

from array import array
from ctypes import wintypes
from pathlib import Path

import ctypes
import math
import time
import wave


def scale_pcm_16(samples: bytes, volume_percent: float) -> bytes:
    if not math.isfinite(volume_percent) or not 0 <= volume_percent <= 100:
        raise ValueError("音量必须为 0～100%")
    if volume_percent == 100:
        return samples
    values = array("h", samples)
    gain = volume_percent / 100
    return array("h", (round(sample * gain) for sample in values)).tobytes()


def play_wav(path: Path, volume_percent: float = 1.0) -> None:
    """同步等待此轮播放完成；调用方必须放到工作线程中执行。"""
    with wave.open(str(path), "rb") as sound:
        channels = sound.getnchannels()
        rate = sound.getframerate()
        sample_bytes = sound.getsampwidth()
        duration = sound.getnframes() / rate
        samples = sound.readframes(sound.getnframes())
    if not samples or sample_bytes != 2:
        raise ValueError("点击音效必须是非空的 16 位 PCM WAV")
    samples = scale_pcm_16(samples, volume_percent)
    if volume_percent == 0:
        return

    class WaveFormat(ctypes.Structure):
        _pack_ = 1
        _fields_ = [
            ("format_tag", wintypes.WORD), ("channels", wintypes.WORD),
            ("sample_rate", wintypes.DWORD), ("bytes_per_second", wintypes.DWORD),
            ("block_align", wintypes.WORD), ("bits_per_sample", wintypes.WORD), ("extra_size", wintypes.WORD),
        ]

    class WaveHeader(ctypes.Structure):
        _fields_ = [
            ("data", ctypes.c_void_p), ("buffer_length", wintypes.DWORD),
            ("bytes_recorded", wintypes.DWORD), ("user", ctypes.c_size_t),
            ("flags", wintypes.DWORD), ("loops", wintypes.DWORD),
            ("next", ctypes.c_void_p), ("reserved", ctypes.c_size_t),
        ]

    kernel = ctypes.WinDLL("kernel32", use_last_error=True)
    winmm = ctypes.WinDLL("winmm")
    handle = wintypes.HANDLE
    signatures = [
        (kernel, "CreateEventW", [ctypes.c_void_p, wintypes.BOOL, wintypes.BOOL, wintypes.LPCWSTR], handle),
        (kernel, "CloseHandle", [handle], wintypes.BOOL),
        (kernel, "WaitForSingleObject", [handle, wintypes.DWORD], wintypes.DWORD),
        (winmm, "waveOutOpen", [ctypes.POINTER(handle), wintypes.UINT, ctypes.POINTER(WaveFormat),
                                 ctypes.c_size_t, ctypes.c_size_t, wintypes.DWORD], wintypes.UINT),
        (winmm, "waveOutPrepareHeader", [handle, ctypes.POINTER(WaveHeader), wintypes.UINT], wintypes.UINT),
        (winmm, "waveOutWrite", [handle, ctypes.POINTER(WaveHeader), wintypes.UINT], wintypes.UINT),
        (winmm, "waveOutUnprepareHeader", [handle, ctypes.POINTER(WaveHeader), wintypes.UINT], wintypes.UINT),
        (winmm, "waveOutReset", [handle], wintypes.UINT),
        (winmm, "waveOutClose", [handle], wintypes.UINT),
        (winmm, "waveOutGetErrorTextW", [wintypes.UINT, wintypes.LPWSTR, wintypes.UINT], wintypes.UINT),
    ]
    for library, name, arguments, result in signatures:
        function = getattr(library, name)
        function.argtypes, function.restype = arguments, result

    def checked(result: int, operation: str) -> None:
        if result:
            message = ctypes.create_unicode_buffer(256)
            winmm.waveOutGetErrorTextW(result, message, len(message))
            raise OSError(result, f"{operation}: {message.value}")

    event = kernel.CreateEventW(None, False, False, None)
    if not event:
        raise ctypes.WinError(ctypes.get_last_error())
    output = handle()
    block_align = channels * sample_bytes
    format_info = WaveFormat(1, channels, rate, rate * block_align, block_align, sample_bytes * 8, 0)
    # 缓冲区、头和事件必须活到播放完成并解除准备之后。
    buffer = ctypes.create_string_buffer(samples)
    header = WaveHeader(data=ctypes.addressof(buffer), buffer_length=len(samples))
    prepared = False
    try:
        checked(winmm.waveOutOpen(ctypes.byref(output), 0xFFFFFFFF, ctypes.byref(format_info), event, 0, 0x00050000), "waveOutOpen")
        try:
            checked(winmm.waveOutPrepareHeader(output, ctypes.byref(header), ctypes.sizeof(header)), "waveOutPrepareHeader")
            prepared = True
            checked(winmm.waveOutWrite(output, ctypes.byref(header), ctypes.sizeof(header)), "waveOutWrite")
            deadline = time.monotonic() + duration + 2
            # CALLBACK_EVENT 也会在打开设备时触发，必须检查 WHDR_DONE，不能把首次通知当作播完。
            while not header.flags & 1:
                remaining = deadline - time.monotonic()
                if remaining <= 0:
                    raise TimeoutError("点击音效播放超时")
                result = kernel.WaitForSingleObject(event, math.ceil(remaining * 1000))
                if result == 0xFFFFFFFF:
                    raise ctypes.WinError(ctypes.get_last_error())
                if result == 0x102:
                    raise TimeoutError("点击音效播放超时")
        finally:
            try:
                if prepared:
                    if not header.flags & 1:
                        checked(winmm.waveOutReset(output), "waveOutReset")
                    checked(winmm.waveOutUnprepareHeader(output, ctypes.byref(header), ctypes.sizeof(header)), "waveOutUnprepareHeader")
            finally:
                checked(winmm.waveOutClose(output), "waveOutClose")
    finally:
        kernel.CloseHandle(event)

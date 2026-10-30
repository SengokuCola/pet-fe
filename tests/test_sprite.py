import ctypes
import sys

import pytest

from maimai_sprinkles.effect_window import MINI_HEIGHT, MINI_WIDTH, render_sprite


@pytest.mark.skipif(sys.platform != "win32", reason="桌面绘制使用 Windows GDI+")
def test_original_sprite_keeps_transparency_and_smooth_edges():
    buffer = ctypes.create_string_buffer(MINI_WIDTH * MINI_HEIGHT * 4)
    render_sprite(ctypes.cast(buffer, ctypes.c_void_p), MINI_WIDTH, MINI_HEIGHT)
    pixels = [tuple(buffer.raw[index:index + 4]) for index in range(0, len(buffer), 4)]
    assert pixels[0][3] == 0
    assert any(0 < alpha < 255 for _, _, _, alpha in pixels)
    assert sum(alpha == 255 for _, _, _, alpha in pixels) > len(pixels) / 4
    assert all(max(b, g, r) <= alpha for b, g, r, alpha in pixels)

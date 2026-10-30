from array import array
from types import SimpleNamespace
from unittest.mock import AsyncMock

import asyncio
import json

import pytest

from maimai_sprinkles import plugin as plugin_module
from maimai_sprinkles.audio import scale_pcm_16
from maimai_sprinkles.plugin import MaimaiSprinklesPlugin
from maimai_sprinkles.volume import read_volume, save_volume, validate_volume


def test_percent_applies_to_original_pcm_without_changing_source():
    samples = array("h", [-32000, -1000, 0, 1000, 32000]).tobytes()
    assert array("h", scale_pcm_16(samples, 1)).tolist() == [-320, -10, 0, 10, 320]
    assert array("h", scale_pcm_16(samples, 0)).tolist() == [0] * 5
    assert scale_pcm_16(samples, 100) == samples


@pytest.mark.parametrize("value", [True, "1", -1, 101, float("inf"), float("nan")])
def test_reject_invalid_volume(value):
    with pytest.raises(ValueError):
        validate_volume(value)


def test_volume_persists_and_default_remains_one_percent(tmp_path):
    path = tmp_path / "volume.json"
    assert read_volume(path) == 1
    save_volume(path, 2.5)
    assert read_volume(path) == 2.5
    assert not path.with_suffix(".tmp").exists()


@pytest.mark.asyncio
async def test_each_click_captures_current_volume(monkeypatch):
    plugin = MaimaiSprinklesPlugin()
    plugin.set_plugin_config(plugin.get_default_config())
    plugin._stopping = False
    sound = AsyncMock()
    monkeypatch.setattr(plugin_module.asyncio, "to_thread", sound)
    await plugin.clicked()
    plugin._volume_percent = 2.5
    await plugin.clicked()
    assert [call.args for call in sound.await_args_list] == [
        (plugin_module.play_click_sound, 1.0), (plugin_module.play_click_sound, 2.5),
    ]


@pytest.mark.asyncio
async def test_volume_window_events_save_setting_and_report_ready(tmp_path, monkeypatch):
    plugin = MaimaiSprinklesPlugin()
    plugin._set_context(SimpleNamespace(paths=SimpleNamespace(data_dir=tmp_path)))
    stream = asyncio.StreamReader()
    stream.feed_data(b'{"type":"ready"}\n{"type":"volume","value":3.5}\n')
    stream.feed_eof()
    stderr = asyncio.StreamReader()
    stderr.feed_eof()
    process = SimpleNamespace(stdout=stream, stderr=stderr, returncode=0, wait=AsyncMock(return_value=0))
    monkeypatch.setattr(plugin_module.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    plugin._volume_ready = asyncio.get_running_loop().create_future()
    await plugin._run_volume_window()
    assert plugin._volume_ready.done()
    assert plugin._volume_percent == 3.5
    assert json.loads((tmp_path / "volume.json").read_text()) == {"volume_percent": 3.5}


@pytest.mark.asyncio
async def test_button_rejects_unknown_action():
    plugin = MaimaiSprinklesPlugin()
    with pytest.raises(ValueError, match="未声明"):
        await plugin.on_desktop_pet_button_click("__init__")

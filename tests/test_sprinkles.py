from unittest.mock import AsyncMock

import asyncio
import wave

import pytest

from maimai_sprinkles import plugin as plugin_module
from maimai_sprinkles.effect_window import FallingMotion
from maimai_sprinkles.plugin import MaimaiSprinklesPlugin


@pytest.fixture
def plugin():
    instance = MaimaiSprinklesPlugin()
    instance.set_plugin_config(instance.get_default_config())
    instance._stopping = False
    return instance


@pytest.mark.asyncio
async def test_release_before_deadline_prevents_drop(plugin, monkeypatch):
    show = AsyncMock()
    monkeypatch.setattr(plugin, "_show_effect", show)
    await plugin.drag_started("one", 0, 20, 1)
    task = plugin._hold_task
    await asyncio.sleep(0)
    await plugin.drag_ended("one")
    assert task.cancelled()
    assert plugin._gesture_id == ""
    show.assert_not_awaited()


@pytest.mark.asyncio
async def test_late_start_of_finished_gesture_is_ignored(plugin):
    await plugin.drag_ended("old")
    await plugin.drag_started("old", 0, 20, 1)
    assert plugin._hold_task is None


@pytest.mark.asyncio
async def test_unrelated_release_does_not_cancel_current_hold(plugin):
    await plugin.drag_started("new", 0, 20, 1)
    task = plugin._hold_task
    await plugin.drag_ended("old")
    assert plugin._hold_task is task
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_duplicate_start_keeps_original_deadline(plugin):
    await plugin.drag_started("one", 0, 20, 1)
    task = plugin._hold_task
    await plugin.drag_started("one", 0, 20, 1)
    assert plugin._hold_task is task
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_visible_limit_prevents_spawning_more_windows(plugin, monkeypatch):
    show = AsyncMock()
    monkeypatch.setattr(plugin, "_show_effect", show)
    monkeypatch.setattr(plugin_module.asyncio, "sleep", AsyncMock())
    plugin.config.effects.max_visible = 1
    blocker = asyncio.create_task(asyncio.Event().wait())
    plugin._effects.add(blocker)
    blocker.add_done_callback(plugin._effect_finished)
    plugin._gesture_id = "one"
    await plugin._drop_after_hold("one", 0, 20, 1)
    show.assert_not_awaited()
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_one_drop_per_hold_and_cleanup(plugin, monkeypatch):
    reached = asyncio.Event()
    released = asyncio.Event()
    async def show(*args):
        reached.set()
        await released.wait()
    monkeypatch.setattr(plugin, "_show_effect", show)
    plugin._gesture_id = "one"
    # 只快进计时等待；原生窗口任务保持真实的异步生命周期。
    original_sleep = asyncio.sleep
    async def fast_sleep(delay):
        await original_sleep(0)
    monkeypatch.setattr(plugin_module.asyncio, "sleep", fast_sleep)
    await plugin._drop_after_hold("one", 0, 20, 1)
    await asyncio.wait_for(reached.wait(), 1)
    assert len(plugin._effects) == 1
    await plugin.on_unload()
    assert not plugin._effects


@pytest.mark.asyncio
async def test_hidden_pet_cancels_hold_and_ignores_late_start(plugin):
    await plugin.drag_started("one", 0, 20, 1)
    await plugin.visibility_changed(False)
    await plugin.drag_started("late", 0, 20, 1)
    assert plugin._hold_task is None
    await plugin.visibility_changed(True)
    await plugin.drag_started("two", 0, 20, 1)
    assert plugin._hold_task is not None
    await plugin.on_unload()


@pytest.mark.asyncio
async def test_sound_is_not_played_when_disabled(plugin, monkeypatch):
    sound = AsyncMock()
    monkeypatch.setattr(plugin_module.asyncio, "to_thread", sound)
    plugin.config.sound.enabled = False
    await plugin.clicked()
    sound.assert_not_awaited()
    plugin.config.sound.enabled = True
    await plugin.clicked()
    await plugin.clicked()
    assert sound.await_count == 2


@pytest.mark.asyncio
async def test_clicks_can_overlap_without_waiting_for_previous_sound(plugin, monkeypatch):
    release = asyncio.Event()
    both_started = asyncio.Event()
    started = []
    async def play(function, volume):
        started.append((function, volume))
        if len(started) == 2:
            both_started.set()
        await release.wait()
    monkeypatch.setattr(plugin_module.asyncio, "to_thread", play)
    tasks = [asyncio.create_task(plugin.clicked()) for _ in range(2)]
    try:
        await asyncio.wait_for(both_started.wait(), 1)
        assert started == [(plugin_module.play_click_sound, 1.0)] * 2
        assert not any(task.done() for task in tasks)
    finally:
        release.set()
        await asyncio.gather(*tasks)


@pytest.mark.asyncio
async def test_unload_kills_effect_process(plugin, monkeypatch):
    entered = asyncio.Event()
    class Process:
        returncode = None
        async def communicate(self):
            entered.set()
            await asyncio.Event().wait()
        def kill(self):
            self.returncode = -1
        async def wait(self):
            return self.returncode
    process = Process()
    monkeypatch.setattr(plugin_module.asyncio, "create_subprocess_exec", AsyncMock(return_value=process))
    task = asyncio.create_task(plugin._show_effect(0, 20, 1))
    plugin._effects.add(task)
    task.add_done_callback(plugin._effect_finished)
    await asyncio.wait_for(entered.wait(), 1)
    await plugin.on_unload()
    assert process.returncode == -1


def test_small_maimai_lands_and_settles_on_negative_coordinate_monitor():
    motion = FallingMotion(x=-1500, y=-100, floor=1000, left=-1920, right=-58, vx=-100)
    ys = []
    for _ in range(900):
        motion.step(1 / 60)
        ys.append(motion.y)
        assert motion.left <= motion.x <= motion.right
        assert motion.y <= motion.floor
    assert motion.resting and motion.y == motion.floor
    assert any(current < previous for previous, current in zip(ys, ys[1:]))  # 落地后确实弹跳。


def test_click_asset_is_valid_metal_pipe_pcm():
    with wave.open(str(plugin_module.ROOT / "assets" / "click.wav"), "rb") as sound:
        assert sound.getnchannels() == 2 and sound.getsampwidth() == 2
        assert sound.getframerate() == 44100
        assert 2.5 < sound.getnframes() / sound.getframerate() < 3

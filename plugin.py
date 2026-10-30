"""独立桌宠扩展：长时间提起后掉落小麦麦，单击播放金属管音效。"""

from collections import deque
from contextlib import suppress
from pathlib import Path
from typing import Any, Deque, Dict, Optional, Set

from maibot_sdk import HookHandler, MaiBotPlugin
from maibot_sdk.types import HookMode

import asyncio
import json
import logging
import math
import subprocess
import sys

from .audio import play_wav
from .settings import SprinklesConfig
from .volume import read_volume, save_volume, validate_volume

logger = logging.getLogger(__name__)
ROOT = Path(__file__).resolve().parent


def play_click_sound(volume_percent: float = 1.0) -> None:
    """每次播放在独立缓冲区应用音量，保持并发音效互不打断。"""
    play_wav(ROOT / "assets" / "metal_pipe.wav", volume_percent)


class MaimaiSprinklesPlugin(MaiBotPlugin):
    config_model = SprinklesConfig
    # 字典声明同样属于按钮协议，现有 SDK 2.20 也能使用；2.21 可改用 DesktopPetButton 模型。
    desktop_pet_buttons = [{"id": "volume", "label": "钢管音量", "icon": "volume", "order": 10}]

    def __init__(self) -> None:
        super().__init__()
        self._hold_task: Optional[asyncio.Task[None]] = None
        self._effects: Set[asyncio.Task[None]] = set()
        self._gesture_id = ""
        # 观察型 Hook 可能并发到达；结束事件先到时，迟到的开始事件不能再启动计时。
        self._ended: Deque[str] = deque(maxlen=64)
        self._stopping = True
        self._available = True
        self._volume_percent = 1.0
        self._volume_task: Optional[asyncio.Task[None]] = None
        self._volume_ready: Optional[asyncio.Future[None]] = None
        self._volume_error = ""

    async def on_load(self) -> None:
        if sys.platform != "win32":
            raise RuntimeError("小麦麦掉落扩展仅支持 Windows 桌面")
        self._stopping = False
        self._volume_percent = await asyncio.to_thread(read_volume, self.ctx.paths.data_dir / "volume.json")

    async def _cancel_hold(self) -> None:
        task, self._hold_task = self._hold_task, None
        self._gesture_id = ""
        if task is not None:
            task.cancel()
            await asyncio.gather(task, return_exceptions=True)

    async def _clear(self) -> None:
        await self._cancel_hold()
        tasks = tuple(self._effects)
        for task in tasks:
            task.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)

    async def on_unload(self) -> None:
        self._stopping = True
        await self._clear()
        if self._volume_task is not None:
            self._volume_task.cancel()
            await asyncio.gather(self._volume_task, return_exceptions=True)

    async def on_config_update(self, scope: str, config_data: Dict[str, Any], version: str) -> None:
        await self._clear()

    @HookHandler("desktop_pet.drag_started", mode=HookMode.OBSERVE)
    async def drag_started(
        self, gesture_id: str, offset_x: int, offset_y: int, scale: float, **kwargs: Any
    ) -> None:
        if self._stopping or not self._available or not self.config.effects.enabled or gesture_id in self._ended:
            return
        if gesture_id == self._gesture_id:
            return
        if not gesture_id or not math.isfinite(scale) or not 0.5 <= scale <= 8:
            raise ValueError("无效的桌宠拖动事件")
        await self._cancel_hold()
        if gesture_id in self._ended or self._stopping or not self._available:
            return
        self._gesture_id = gesture_id
        self._hold_task = asyncio.create_task(self._drop_after_hold(gesture_id, offset_x, offset_y, scale))

    @HookHandler("desktop_pet.drag_ended", mode=HookMode.OBSERVE)
    async def drag_ended(self, gesture_id: str, **kwargs: Any) -> None:
        self._ended.append(gesture_id)
        if gesture_id == self._gesture_id:
            await self._cancel_hold()

    @HookHandler("desktop_pet.closed", mode=HookMode.OBSERVE)
    async def closed(self, **kwargs: Any) -> None:
        self._available = False
        await self._clear()

    @HookHandler("desktop_pet.ready", mode=HookMode.OBSERVE)
    async def ready(self, **kwargs: Any) -> None:
        self._available = True

    @HookHandler("desktop_pet.visibility_changed", mode=HookMode.OBSERVE)
    async def visibility_changed(self, visible: bool, **kwargs: Any) -> None:
        self._available = visible
        if not visible:
            await self._clear()

    @HookHandler("desktop_pet.clicked", mode=HookMode.OBSERVE)
    async def clicked(self, **kwargs: Any) -> None:
        if self._stopping or not self.config.sound.enabled:
            return
        await asyncio.to_thread(play_click_sound, self._volume_percent)

    async def get_desktop_pet_button_states(self) -> Dict[str, Any]:
        return {"volume": {
            "visible": True,
            "disabled": self._stopping or (self._volume_task is not None and not self._volume_task.done()),
            "text": self._volume_error or f"当前音量：{self._volume_percent:g}%",
        }}

    async def on_desktop_pet_button_click(self, button_id: str) -> None:
        if button_id != "volume":
            raise ValueError("未声明的桌宠按钮")
        if self._stopping:
            raise RuntimeError("插件正在退出")
        if self._volume_task is not None and not self._volume_task.done():
            raise RuntimeError("音量调节窗口已经打开")
        self._volume_error = ""
        self._volume_ready = asyncio.get_running_loop().create_future()
        self._volume_task = asyncio.create_task(self._run_volume_window())
        self._volume_task.add_done_callback(self._volume_finished)
        try:
            await asyncio.wait_for(asyncio.shield(self._volume_ready), 6)
        except BaseException:
            self._volume_task.cancel()
            await asyncio.gather(self._volume_task, return_exceptions=True)
            raise

    def _volume_finished(self, task: asyncio.Task[None]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            self._volume_error = str(error)[:200]
            logger.error("钢管音量调节失败", exc_info=(type(error), error, error.__traceback__))
            if self._volume_ready is not None and not self._volume_ready.done():
                self._volume_ready.set_exception(error)
        if not self._stopping:
            refresh = asyncio.create_task(self.ctx.call_capability("desktop_pet.refresh_buttons"))
            refresh.add_done_callback(self._refresh_finished)

    @staticmethod
    def _refresh_finished(task: asyncio.Task[Any]) -> None:
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("桌宠按钮刷新失败", exc_info=(type(error), error, error.__traceback__))

    async def _run_volume_window(self) -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "volume_window.py"), "--volume", str(self._volume_percent),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.PIPE,
            stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        assert process.stdout is not None
        assert process.stderr is not None
        # stderr 并行读取，避免子进程输出填满管道而无法退出。
        stderr = asyncio.create_task(process.stderr.read())
        try:
            async for line in process.stdout:
                event = json.loads(line)
                if event["type"] == "ready":
                    if self._volume_ready is not None and not self._volume_ready.done():
                        self._volume_ready.set_result(None)
                elif event["type"] == "volume":
                    volume = validate_volume(event["value"])
                    await asyncio.to_thread(save_volume, self.ctx.paths.data_dir / "volume.json", volume)
                    self._volume_percent = volume
                else:
                    raise ValueError("未知音量窗口事件")
            code = await process.wait()
            details = (await stderr).decode("utf-8", "replace")[-4000:]
            if code:
                raise RuntimeError(f"音量窗口退出: {code}\n{details}")
            if self._volume_ready is not None and not self._volume_ready.done():
                raise RuntimeError("音量窗口未就绪便退出")
        finally:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()
            stderr.cancel()
            await asyncio.gather(stderr, return_exceptions=True)

    async def _drop_after_hold(self, gesture_id: str, offset_x: int, offset_y: int, scale: float) -> None:
        await asyncio.sleep(self.config.effects.hold_seconds)
        if self._stopping or self._gesture_id != gesture_id or len(self._effects) >= self.config.effects.max_visible:
            return
        # 每次提起只掉落一只；独立窗口进程承担动画和原生绘制，不占用 Runner 的事件循环。
        task = asyncio.create_task(self._show_effect(offset_x, offset_y, scale))
        self._effects.add(task)
        task.add_done_callback(self._effect_finished)

    def _effect_finished(self, task: asyncio.Task[None]) -> None:
        self._effects.discard(task)
        if not task.cancelled() and (error := task.exception()) is not None:
            logger.error("小麦麦掉落窗口失败", exc_info=(type(error), error, error.__traceback__))

    async def _show_effect(self, offset_x: int, offset_y: int, scale: float) -> None:
        process = await asyncio.create_subprocess_exec(
            sys.executable, str(ROOT / "effect_window.py"),
            "--offset-x", str(offset_x), "--offset-y", str(offset_y), "--scale", str(scale),
            "--lifetime", str(self.config.effects.lifetime_seconds),
            stdin=asyncio.subprocess.DEVNULL, stdout=asyncio.subprocess.DEVNULL,
            stderr=asyncio.subprocess.PIPE, creationflags=subprocess.CREATE_NO_WINDOW,
        )
        try:
            async with asyncio.timeout(self.config.effects.lifetime_seconds + 5):
                _, stderr = await process.communicate()
            if process.returncode:
                raise RuntimeError(f"小麦麦窗口退出: {process.returncode}\n{stderr.decode('utf-8', 'replace')[-4000:]}")
        finally:
            if process.returncode is None:
                with suppress(ProcessLookupError):
                    process.kill()
                await process.wait()


def create_plugin() -> MaimaiSprinklesPlugin:
    return MaimaiSprinklesPlugin()

# 麦麦钢管

MaiBot 的 Windows 桌宠扩展，默认启用。需要 MaiBot 1.3.19+、SDK 2.20.0+ 和 WebView2 Runtime。

- 提起并拖动桌宠，保持 1.5 秒后，从桌宠脚下掉出一只小麦麦。
- 小麦麦会落到所在显示器的桌面底部、弹跳并淡出，默认显示 5 秒。
- 小麦麦直接使用主程序内置麦麦的原始 SVG 缩小，保留身体比例、尾巴、芽叶和五官；大小约为主桌宠的一半。
- 每次提起只掉落一只，同时最多显示 3 只。
- 提前松手、取消拖动或隐藏桌宠，会取消尚未触发的掉落。
- 单击桌宠本体时播放约 2.8 秒的金属管掉落音效。
- 桌宠的「插件扩展 → 钢管音量」按钮可调节 0～100% 音量，默认 1%，可精确输入小数。

![小麦麦预览](preview.png)

## 使用

1. 从插件市场安装「麦麦钢管」，或将本仓库克隆到主程序的 `plugins/pet-fe` 下；重启或重新扫描插件。
2. 在 WebUI 主程序配置的「桌宠」中启用桌宠。
3. 在插件设置中可以调整提起时长、显示时长、数量上限，分别开关掉落和点击音效。

音量窗口关闭时通过 `desktop_pet.refresh_buttons` 刷新按钮上的当前音量，需要在清单声明此能力。插件不依赖蓝发女仆皮肤插件；任何桌宠皮肤都可以触发，掉落的始终是橙色小麦麦。效果窗口透明、置顶并且鼠标穿透，不抢焦点。

## 生命周期和实现

`desktop_pet.drag_started` 提供 `gesture_id`、光标到桌宠锚点的偏移以及缩放。插件异步等待达到配置时长后启动一个短生命周期原生窗口进程；光标位置只在特效启动时用于定位，不存储或传出。每个窗口只依赖 Python 标准库和 Windows API。

`desktop_pet.drag_ended` 使用相同 ID 取消计时；迟到的旧事件不会影响下一次拖动。隐藏或关闭桌宠、更新配置和卸载插件会回收效果窗口。Runner 异常退出时窗口也会在自身生命周期结束后消失。

形象来自主程序 `src/desktop_pet/web/index.html` 的 `builtin-pet` SVG；素材包含原始路径及原配色，运行时由 Windows GDI+ 高质量缩放，并用逐像素透明度绘制，不再使用独立的简笔画。素材和原始 MIT 许可分别保存在 `assets/mini_maimai.svg`、`assets/mini_maimai.png` 与 `assets/maimai-LICENSE`。素材在插件中独立分发，运行时不读取主程序源码。

点击音效通过 Windows 音频接口在工作线程中播放，每次点击创建独立的播放句柄，连续点击可以重叠播放。音频使用用户提供的 `metal pipe.mp3`，原文件保存在 `assets/metal_pipe.mp3`，解码为未调音量的 `assets/metal_pipe.wav`；每次播放在独立缓冲区应用当前音量，默认振幅为原音频的 1%（-40 dB）。旧版使用的 `assets/click.wav` 保留为 1% 音量，避免运行中的旧插件突然变响。运行插件无需 FFmpeg 或联网。

单击麦麦展开菜单，选择拼图图标「插件扩展」，再点「钢管音量」。音量面板使用和桌宠一致的暖色圆角界面；滑块实时生效，也可以输入百分比后点「应用」，或用「恢复 1%」「静音」按钮。新设置只影响之后的点击，正在播放的音效保持原音量。音量保存在 SDK 分配的数据目录 `data/plugins/sengokucola.maimai-sprinkles/volume.json`，重载和重启后仍会保留；卸载插件会关闭调节窗口。

本插件用字典声明按钮，因此已有 SDK 2.20 配合新版 Host 即可运行。SDK 2.21 额外提供 `DesktopPetButton` 和 `DesktopPetButtonState` 类型，以及 `ctx.desktop_pet.refresh_buttons()` 包装方法。

主程序负责按钮渲染、点击回调路由与 Hook；特效绘制、计时、音频、音量窗口和资源回收均在本插件中实现。

## 开发与验证

在本仓库根目录安装开发依赖并测试：

```powershell
uv sync --group dev
uv run pytest -q
uv run python volume_window.py --volume 1 --smoke-test
```

也可以复用主程序环境。以下示例假定插件目录名为 `pet-fe`：

```powershell
uv run --no-sync pytest plugins/pet-fe/tests -q
uv run --no-sync python plugins/pet-fe/effect_window.py --lifetime 3
uv run --no-sync python plugins/pet-fe/effect_window.py --scale 3 --preview plugins/pet-fe/preview.png
uv run --no-sync python plugins/pet-fe/volume_window.py --volume 1
uv run --no-sync --with resvg-py==0.5.0 python plugins/pet-fe/prepare_sprite.py
ffmpeg -i plugins/pet-fe/assets/metal_pipe.mp3 -c:a pcm_s16le plugins/pet-fe/assets/metal_pipe.wav
```

入口为 `plugin.py:create_plugin`。稳定插件 ID 为 `sengokucola.maimai-sprinkles`，与本地早期版本一致，改名不会改变数据目录。仓库地址：[SengokuCola/pet-fe](https://github.com/SengokuCola/pet-fe)。版本更新见 [CHANGELOG.md](CHANGELOG.md)。

代码使用 MIT 许可证；主桌宠素材保留原始 MIT 许可，音频来源说明见 [ASSETS.md](ASSETS.md)。运行配置 `config.toml`、缓存和虚拟环境不随仓库或 Release 分发。

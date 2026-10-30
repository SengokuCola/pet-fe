"""由插件 SDK 生成配置，不读写主程序配置。"""

from maibot_sdk import Field, PluginConfigBase


class PluginSettings(PluginConfigBase):
    __ui_label__ = "插件"

    enabled: bool = Field(default=True, description="启用桌宠的小麦麦掉落与点击音效")
    config_version: str = "1.0.0"


class EffectSettings(PluginConfigBase):
    __ui_label__ = "小麦麦掉落"

    enabled: bool = Field(default=True, description="提起桌宠一段时间后掉落一只小麦麦")
    hold_seconds: float = Field(default=1.5, ge=0.2, le=10, allow_inf_nan=False, description="提起多久后掉落（秒）")
    lifetime_seconds: float = Field(default=5, ge=1, le=15, allow_inf_nan=False, description="小麦麦显示多久后消失（秒）")
    max_visible: int = Field(default=3, ge=1, le=5, description="屏幕上同时出现的小麦麦数量上限")


class SoundSettings(PluginConfigBase):
    __ui_label__ = "点击音效"

    enabled: bool = Field(default=True, description="单击桌宠时播放金属管掉落音效")


class SprinklesConfig(PluginConfigBase):
    plugin: PluginSettings = Field(default_factory=PluginSettings)
    effects: EffectSettings = Field(default_factory=EffectSettings)
    sound: SoundSettings = Field(default_factory=SoundSettings)

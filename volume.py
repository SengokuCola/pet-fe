"""音量的单一持久化位置，与主程序配置无关。"""

from pathlib import Path

import json
import math


def validate_volume(value: object) -> float:
    if isinstance(value, bool) or not isinstance(value, (int, float)):
        raise ValueError("音量必须是数字")
    result = float(value)
    if not math.isfinite(result) or not 0 <= result <= 100:
        raise ValueError("音量必须为 0～100%")
    return result


def read_volume(path: Path) -> float:
    if not path.exists():
        return 1.0
    data = json.loads(path.read_text(encoding="utf-8"))
    return validate_volume(data["volume_percent"])


def save_volume(path: Path, value: float) -> None:
    volume = validate_volume(value)
    path.parent.mkdir(parents=True, exist_ok=True)
    temporary = path.with_suffix(".tmp")
    temporary.write_text(json.dumps({"volume_percent": volume}), encoding="utf-8")
    temporary.replace(path)

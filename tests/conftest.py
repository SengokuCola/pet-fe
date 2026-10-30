from importlib.util import module_from_spec, spec_from_file_location
from pathlib import Path

import sys

# 固定测试导入名，克隆成 pet-fe 或解压到任意目录时也能测试；不加载主程序及实际配置。
root = Path(__file__).resolve().parents[1]
spec = spec_from_file_location("maimai_sprinkles", root / "__init__.py", submodule_search_locations=[str(root)])
if spec is None or spec.loader is None:
    raise RuntimeError("无法加载插件测试包")
package = module_from_spec(spec)
sys.modules["maimai_sprinkles"] = package
spec.loader.exec_module(package)

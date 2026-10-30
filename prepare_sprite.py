"""开发时从 Host 原始 SVG 导出小麦麦素材；运行插件不需要 resvg。"""

from pathlib import Path

import argparse
import re
import shutil


def extract_builtin_svg(html: str) -> str:
    match = re.search(r'<svg id="builtin-pet".*?</svg>', html, re.S)
    if match is None:
        raise ValueError("源页面中没有 builtin-pet SVG")
    svg = match.group()
    svg = svg.replace('<svg ', '<svg xmlns="http://www.w3.org/2000/svg" ', 1)
    # 保留原图所有路径与比例，只将页面 CSS 变量固定为原值，并固定为睁眼待机状态。
    for name in ("ink", "orange", "cream", "leaf"):
        color = re.search(rf'--{name}:\s*(#[0-9a-fA-F]+)', html)
        if color is None:
            raise ValueError(f"缺少主桌宠颜色: {name}")
        svg = svg.replace(f"var(--{name})", color.group(1))
    end = svg.index(">") + 1
    svg = svg[:end] + '<style>.eye-happy,#mouth{display:none}</style>' + svg[end:]
    return svg


def main() -> None:
    from resvg_py import svg_to_bytes

    parser = argparse.ArgumentParser()
    parser.add_argument("--source", type=Path, default=Path(__file__).resolve().parents[2] / "src/desktop_pet/web/index.html")
    args = parser.parse_args()
    root = Path(__file__).resolve().parent
    assets = root / "assets"
    svg = extract_builtin_svg(args.source.read_text(encoding="utf-8"))
    (assets / "mini_maimai.svg").write_text(svg + "\n", encoding="utf-8")
    (assets / "mini_maimai.png").write_bytes(svg_to_bytes(svg_string=svg, width=600, skip_system_fonts=True))
    shutil.copyfile(args.source.parent.parent / "LICENSE", assets / "maimai-LICENSE")


if __name__ == "__main__":
    main()

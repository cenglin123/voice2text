#!/usr/bin/env python
# -*- coding: utf-8 -*-
"""从托盘麦克风造型生成 Windows 程序 ICO。"""
from pathlib import Path
import sys

from PIL import Image, ImageDraw

ROOT = Path(__file__).resolve().parent.parent
sys.path.insert(0, str(ROOT))

from voice2text.trayicon import draw_icon


def main() -> int:
    size = 256
    image = Image.new("RGBA", (size, size), (0, 0, 0, 0))
    draw = ImageDraw.Draw(image)
    draw.rounded_rectangle(
        (8, 8, size - 8, size - 8), radius=58,
        fill="#16243D", outline="#4C9DF8", width=10,
    )
    microphone = draw_icon("idle", 172, badge=False)
    image.alpha_composite(microphone, ((size - 172) // 2, (size - 172) // 2))
    image.save(
        ROOT / "voice2text.ico", format="ICO",
        sizes=[(16, 16), (24, 24), (32, 32), (48, 48), (64, 64), (128, 128), (256, 256)],
    )
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

"""不创建窗口的悬浮窗渲染回归：状态文字、声波、命中区域和比例边界。"""
from pathlib import Path
import argparse
import sys

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image
from voice2text.widget_render import WidgetRenderer, BASE_H, SS, STATUS_TEXT


def main() -> None:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    count = 0
    for scale in (0.5, 1.0, 1.5, 2.0, 3.0):
        for aspect in (1.0, 1.5, 2.19, 2.2, 3.27, 5.0):
            height = round(BASE_H * scale)
            width = round(height * aspect)
            for state in STATUS_TEXT:
                painter = WidgetRenderer(width, height, scale, state, phase=1)
                frame = painter.render()
                assert frame.size == (width, height)
                assert frame.getpixel((0, 0))[3] == 0
                for box in [*painter.text_bounds.values(), *painter.wave_bounds]:
                    assert 0 <= box[0] <= box[2] <= width * SS, (scale, aspect, state, box)
                    assert 0 <= box[1] <= box[3] <= height * SS, (scale, aspect, state, box)
                hits = list(painter.hits.values())
                for i, (x, y, radius) in enumerate(hits):
                    assert 0 <= x - radius < x + radius <= width
                    assert 0 <= y - radius < y + radius <= height
                    for x2, y2, r2 in hits[i + 1:]:
                        assert (x - x2) ** 2 + (y - y2) ** 2 >= (radius + r2) ** 2
                assert painter.render().tobytes() == frame.tobytes()
                count += 1
    if args.capture:
        grid = Image.new("RGB", (540, 128 * len(STATUS_TEXT) + 24), "#16243d")
        for row, state in enumerate(STATUS_TEXT):
            for x, aspect in ((16, 3.27), (400, 1.0)):
                frame = WidgetRenderer(round(BASE_H * aspect), BASE_H, 1.0, state, phase=1).render()
                grid.paste(frame, (x, 16 + row * 128), frame)
        args.capture.parent.mkdir(parents=True, exist_ok=True)
        grid.save(args.capture)
    print(f"PASS {count} widget layouts: text, waves, hit regions and deterministic preview")


if __name__ == "__main__":
    main()

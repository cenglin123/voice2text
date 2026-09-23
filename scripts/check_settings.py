"""设置页独立验证：圆角控件、尺寸同步、预览和保存数据，不改真实配置。"""
from pathlib import Path
import argparse
import sys
import tkinter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageGrab
from voice2text.settings_window import (
    SettingsWindow, RoundedButton, RoundedField, _normalize_combo,
)


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    parser.add_argument("--dpi", type=float, default=None, help="模拟系统 DPI 倍率，例如 1.5 或 2")
    args = parser.parse_args()
    assert _normalize_combo("Pause", set()) == "pause"
    assert _normalize_combo("F8", set()) == "f8"
    assert _normalize_combo("v", {"alt"}) == "alt+v"
    assert _normalize_combo("k", {"ctrl", "shift"}) == "ctrl+shift+k"
    assert _normalize_combo("Prior", set()) == "page up"
    applied = []
    cfg = {"hotkey": "alt+v", "widget_scale": 1.0, "widget_aspect": 3.27,
           "widget_opacity": 0.92, "proofread_enabled": True,
           "sound_cue": True, "autostart": False}
    preview = Image.new("RGBA", (340, 104), (30, 45, 70, 255))
    with patch("voice2text.settings_window.get_autostart", return_value=False), \
         patch("voice2text.settings_window.set_autostart", return_value=True), \
         patch("pathlib.Path.write_text", return_value=0):
        window = SettingsWindow(cfg, lambda value: applied.append(value) or value,
                                preview, dpi_scale=args.dpi)
        try:
            window.root.update()
            if args.capture:
                args.capture.parent.mkdir(parents=True, exist_ok=True)
                x, y = window.root.winfo_x(), window.root.winfo_y()
                capture_error = []
                def capture_window():
                    try:
                        ImageGrab.grab(bbox=(x - 8, y - 8,
                                             x + window.root.winfo_width() + 8,
                                             y + window.root.winfo_height() + 8)).save(args.capture)
                    except OSError as exc:
                        capture_error.append(exc)
                    finally:
                        window.root.quit()
                window.root.after(250, capture_window)
                window.root.mainloop()
                if capture_error:
                    raise capture_error[0]
            assert isinstance(window._hotkey_entry, RoundedField)
            assert isinstance(window._hotkey_btn, RoundedButton)
            assert len(window._corner_masks) == 4
            assert window.root.attributes("-transparentcolor") == "#010203"
            assert [mask.itemcget(1, "fill") for mask in window._corner_masks] == [
                "#1B2D4B", "#16243D", "#1B2D4B", "#16243D",
            ]
            assert all(mask.itemcget(1, "outline") == "#344865"
                       for mask in window._corner_masks)
            assert window._hotkey_entry.coords(window._hotkey_entry._window)[0] == window._px(13)
            assert window.root.winfo_width() == min(
                window._px(920), window.root.winfo_screenwidth() - window._px(64)
            )
            assert window._save_btn.winfo_rootx() + window._save_btn.winfo_width() <= (
                window.root.winfo_rootx() + window.root.winfo_width()
            )
            window._start_capture()
            window.root.event_generate("<KeyPress-Pause>", when="now")
            assert window._cfg["hotkey"] == "pause"
            assert not window._capturing
            window._start_capture()
            window.root.event_generate("<KeyPress-Control_L>", when="now")
            window.root.event_generate("<KeyPress-k>", when="now")
            assert window._cfg["hotkey"] == "ctrl+k"
            assert not window._capturing
            # 长宽比处于最小值时，左端圆点也必须完整落在 Canvas 边框内。
            left_knob = window._sliders[1].bbox("knob")
            assert left_knob is not None and left_knob[0] >= 1, left_knob
            window.sync_appearance(1.25, 1.0)
            window.root.update()
            assert window._scale_var.get() == 125
            assert window._aspect_var.get() == 100
            preview_side = window._px(104 * 1.25 * 0.6)
            assert window._preview_photo.width() == window._preview_photo.height() == preview_side
            window._save()
            assert applied[0]["widget_scale"] == 1.25
            assert applied[0]["widget_aspect"] == 1.0
        finally:
            if window.root.winfo_exists():
                window.root.destroy()
    print("PASS rounded controls, hotkey padding, aspect/scale sync and save")


if __name__ == "__main__":
    main()

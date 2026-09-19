"""设置页独立验证：圆角控件、尺寸同步、预览和保存数据，不改真实配置。"""
from pathlib import Path
import argparse
import sys
import tkinter
from unittest.mock import patch

sys.path.insert(0, str(Path(__file__).resolve().parents[1]))
from PIL import Image, ImageGrab
from voice2text.settings_window import SettingsWindow, RoundedButton, RoundedField


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--capture", type=Path)
    args = parser.parse_args()
    applied = []
    cfg = {"hotkey": "alt+v", "widget_scale": 1.0, "widget_aspect": 3.27,
           "widget_opacity": 0.92, "proofread_enabled": True,
           "sound_cue": True, "autostart": False}
    preview = Image.new("RGBA", (340, 104), (30, 45, 70, 255))
    with patch("voice2text.settings_window.get_autostart", return_value=False), \
         patch("voice2text.settings_window.set_autostart", return_value=True), \
         patch("pathlib.Path.write_text", return_value=0):
        window = SettingsWindow(cfg, lambda value: applied.append(value) or value, preview)
        try:
            window.root.update()
            if args.capture:
                args.capture.parent.mkdir(parents=True, exist_ok=True)
                x, y = window.root.winfo_x(), window.root.winfo_y()
                window.root.after(250, window.root.quit)
                window.root.mainloop()
                ImageGrab.grab(bbox=(x, y, x + window.root.winfo_width(),
                                     y + window.root.winfo_height())).save(args.capture)
            assert isinstance(window._hotkey_entry, RoundedField)
            assert isinstance(window._hotkey_btn, RoundedButton)
            assert window._hotkey_entry.coords(window._hotkey_entry._window)[0] == 13
            window.sync_appearance(1.25, 4.2)
            window.root.update()
            assert window._scale_var.get() == 125
            assert window._aspect_var.get() == 420
            window._save()
            assert applied[0]["widget_scale"] == 1.25
            assert applied[0]["widget_aspect"] == 4.2
        finally:
            if window.root.winfo_exists():
                window.root.destroy()
    print("PASS rounded controls, hotkey padding, aspect/scale sync and save")


if __name__ == "__main__":
    main()

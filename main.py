import sys
from utils import set_windows_app_id

# 必须在所有其他导入和窗口创建之前调用
set_windows_app_id()

import logging
import os
import threading
from app import GitHubApp
from utils import _setup_logging

try:
    import pystray
    from PIL import Image as PILImage

    TRAY_OK = True
except Exception:
    pystray = None
    TRAY_OK = False


def _load_tray_image(path):
    """从 .ico/.png 里取出最接近 64x64 的那一帧，避免把 16x16 放大成马赛克"""
    img = PILImage.open(path)
    target = (64, 64)
    try:
        if getattr(img, "ico", None) is not None:
            sizes = img.ico.sizes()
            nearest = min(sizes, key=lambda s: abs(s[0] - target[0]) + abs(s[1] - target[1]))
            img = img.ico.getimage(nearest).convert("RGBA")
        else:
            img = img.convert("RGBA")
    except Exception:
        img = img.convert("RGBA")

    if img.size != target:
        resample = getattr(PILImage, "Resampling", PILImage)
        img = img.resize(target, resample.LANCZOS)
    return img


def _start_tray(app: GitHubApp):
    if not TRAY_OK:
        return
    try:
        img = PILImage.new("RGBA", (64, 64), (36, 41, 47, 255))

        if os.path.exists(app.icon_path):
            try:
                img = _load_tray_image(app.icon_path)
            except Exception as e:
                logging.warning(f"托盘图标加载失败: {e}")

        icon_ref = {"icon": None}

        def _show():
            app.after(0, app.deiconify)

        def _quit():
            if icon_ref["icon"]:
                try:
                    icon_ref["icon"].stop()
                except Exception:
                    pass
            app.after(0, app.destroy)

        icon = pystray.Icon(
            "github-client", img, "GitHub 客户端",
            menu=pystray.Menu(
                pystray.MenuItem("显示", _show),
                pystray.MenuItem("退出", _quit),
            ))
        icon_ref["icon"] = icon
        threading.Thread(target=icon.run, daemon=True).start()
        app._tray_icon = icon
    except Exception:
        logging.exception("托盘启动失败")


def main():
    _setup_logging()
    logging.info("启动 GitHub 客户端")
    app = GitHubApp()

    if app.cfg.geometry and app.cfg.geometry != "zoomed":
        try:
            app.geometry(app.cfg.geometry)
        except Exception:
            pass

    def save_geometry():
        try:
            if app.state() == "zoomed":
                app.cfg.geometry = "zoomed"
            else:
                app.cfg.geometry = app.geometry()
            app.cfg.save()
        except Exception:
            pass

    def on_close():
        save_geometry()
        icon = getattr(app, "_tray_icon", None)
        if icon is not None:
            try:
                app.withdraw()
                return
            except Exception:
                pass
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)
    _start_tray(app)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        save_geometry()
        icon = getattr(app, "_tray_icon", None)
        if icon is not None:
            try:
                icon.stop()
            except Exception:
                pass
        logging.info("退出 GitHub 客户端")


if __name__ == "__main__":
    main()
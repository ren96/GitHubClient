import sys
from utils import set_windows_app_id

# 必须在所有其他导入和窗口创建之前调用
set_windows_app_id()

import logging
import os
import threading
import time
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


def _start_tray(app: GitHubApp) -> bool:
    """尝试启动托盘；返回是否成功。失败时关闭窗口将直接退出。"""
    if not TRAY_OK:
        return False
    try:
        img = PILImage.new("RGBA", (64, 64), (36, 41, 47, 255))

        if os.path.exists(app.icon_path):
            try:
                img = _load_tray_image(app.icon_path)
            except Exception as e:
                logging.warning(f"托盘图标加载失败: {e}")

        def _show():
            try:
                app.after(0, app.deiconify)
                app.after(0, app.lift)
            except Exception:
                pass

        def _quit():
            try:
                if getattr(app, "_tray_icon", None) is not None:
                    app._tray_icon.stop()
            except Exception:
                pass
            try:
                app.after(0, app.destroy)
            except Exception:
                pass

        icon = pystray.Icon(
            "github-client", img, "GitHub 客户端",
            menu=pystray.Menu(
                pystray.MenuItem("显示", _show, default=True),
                pystray.MenuItem("退出", _quit),
            ))

        def _runner():
            try:
                icon.run()
            except Exception:
                logging.exception("托盘运行时错误")

        threading.Thread(target=_runner, daemon=True).start()
        # 给后台线程 300ms 检查是否可见；不可见也不视为失败（部分平台 API 延迟）
        time.sleep(0.3)
        app._tray_icon = icon
        return True
    except Exception:
        logging.exception("托盘启动失败")
        return False


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

    tray_ok = _start_tray(app)

    def on_close():
        save_geometry()
        # 仅当托盘成功时才允许最小化到托盘；否则直接退出，避免窗口无法恢复
        if tray_ok and getattr(app, "_tray_icon", None) is not None:
            try:
                app.withdraw()
                return
            except Exception:
                pass
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)
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
import sys
from utils import set_windows_app_id

# 必须在所有其他导入和窗口创建之前调用
set_windows_app_id()

import logging
import os
from app import GitHubApp
from utils import _setup_logging


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
        app.destroy()

    app.protocol("WM_DELETE_WINDOW", on_close)
    try:
        app.mainloop()
    except KeyboardInterrupt:
        pass
    finally:
        save_geometry()
        logging.info("退出 GitHub 客户端")


if __name__ == "__main__":
    main()
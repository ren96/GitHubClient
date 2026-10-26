# about.py
"""关于对话框：展示版本、运行环境、第三方依赖、快捷操作。"""
import importlib
import importlib.metadata
import logging
import os
import platform
import sys
import tkinter as tk
import webbrowser
from tkinter import ttk

from version import __version__ as APP_VERSION, __app_name__, __app_id__
from utils import _config_dir, get_base_dir, open_path_in_os

LICENSE_TEXT = "MIT License"


# ---------- 信息采集 ----------
def _dep_version(pkg_name: str, mod_name: str = "") -> str:
    """优先通过 importlib.metadata 获取包版本，失败则回退到模块的 __version__"""
    try:
        return importlib.metadata.version(pkg_name)
    except importlib.metadata.PackageNotFoundError:
        if mod_name:
            try:
                m = importlib.import_module(mod_name)
                return getattr(m, "__version__", "") or "?"
            except Exception:
                pass
        return "未安装"
    except Exception:
        return "?"


def _collect_system_info() -> str:
    py_ver = f"{sys.version_info.major}.{sys.version_info.minor}.{sys.version_info.micro}"
    try:
        tk_ver = str(tk.TkVersion)
    except Exception:
        tk_ver = "?"
    try:
        cfg_dir = _config_dir()
    except Exception:
        cfg_dir = "?"
    try:
        plat = f"{platform.system()} {platform.release()}"
    except Exception:
        plat = "?"
    arch = platform.machine() or "?"
    frozen = "是（PyInstaller）" if getattr(sys, "frozen", False) else "否（源码运行）"
    return (
        f"应用：{__app_name__}\n"
        f"版本：v{APP_VERSION}\n"
        f"App ID：{__app_id__}\n"
        f"Python：{py_ver}\n"
        f"Tkinter：{tk_ver}\n"
        f"平台：{plat}\n"
        f"架构：{arch}\n"
        f"打包运行：{frozen}\n"
        f"配置目录：{cfg_dir}\n"
        f"日志文件：{os.path.join(cfg_dir, 'app.log')}\n"
    )


def _collect_deps() -> list[tuple[str, str, str]]:
    """返回 [(包名, 版本, 用途)]。"""
    # (pip 包名, 实际模块名, 用途)
    deps = [
        ("requests",   "requests",   "HTTP 请求"),
        ("keyring",    "keyring",    "系统密钥环存储 Token"),
        ("Pillow",     "PIL",        "图像处理（PIL）"),
        ("markdown",   "markdown",   "README Markdown 渲染"),
        ("tkhtmlview", "tkhtmlview", "README HTML 视图"),
    ]
    return [
        (pkg, _dep_version(pkg, mod), desc)
        for pkg, mod, desc in deps
    ]


# ---------- 对话框 ----------
class AboutDialog(tk.Toplevel):
    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title(f"关于 {__app_name__}")
        self.geometry("640x825")  # 调大默认高度，防止内容溢出
        self.minsize(560, 620)
        self.transient(app)
        try:
            if getattr(app, "icon_path", ""):
                self.iconbitmap(app.icon_path)
        except Exception:
            pass

        colors = getattr(app, "colors", {}) or {}
        self.colors = colors
        self.ui_font = getattr(app, "ui_font", "TkDefaultFont")
        self.mono_font = getattr(app, "mono_font", "TkFixedFont")

        # ---------- 底部按钮栏 ----------
        bar = ttk.Frame(self, padding=(16, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="关闭", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="📋 复制系统信息",
                   command=self._copy_info).pack(side="right", padx=(0, 8))
        ttk.Button(bar, text="📂 打开配置目录",
                   command=self._open_cfg_dir).pack(side="left")
        if (getattr(getattr(app, "cfg", None), "update_repo", "") or "").strip():
            repo = app.cfg.update_repo.strip()
            ttk.Button(bar, text="🌐 项目主页",
                       command=lambda u=f"https://github.com/{repo}": webbrowser.open(u)
                       ).pack(side="left", padx=(6, 0))

        # ---------- 主内容 ----------
        f = ttk.Frame(self, padding=(16, 16, 16, 0))
        f.pack(fill="both", expand=True)

        # Logo + 标题
        head = ttk.Frame(f)
        head.pack(fill="x", pady=(0, 12))
        self._logo_label = None
        logo_path = os.path.join(get_base_dir(), "tubiao", "logo.png")
        if os.path.exists(logo_path):
            try:
                from PIL import Image, ImageTk
                img = Image.open(logo_path).convert("RGBA")
                resample = getattr(Image, "Resampling", Image)
                img = img.resize((72, 72), resample.LANCZOS)
                self._logo = ImageTk.PhotoImage(img)
                self._logo_label = tk.Label(head, image=self._logo,
                                            bg=colors.get("BG", "#f6f8fa"))
                self._logo_label.pack(side="left", padx=(0, 14))
            except Exception as e:
                logging.warning("关于页 logo 加载失败: %s", e)

        info = ttk.Frame(head)
        info.pack(side="left", fill="x", expand=True)
        ttk.Label(info, text=__app_name__,
                  font=(self.ui_font, 16, "bold")).pack(anchor="w")
        ttk.Label(info, text=f"v{APP_VERSION}  ·  {LICENSE_TEXT}",
                  style="Subtitle.TLabel").pack(anchor="w", pady=(2, 0))
        ttk.Label(info, text="基于 Tkinter 的 GitHub 桌面客户端",
                  style="Hint.TLabel").pack(anchor="w", pady=(4, 0))

        # 说明文字（优先 pack，确保不会被列表挤出可视区）
        ttk.Label(
            f,
            text=("Token 保存在系统密钥环；若系统不支持密钥环，则回退到权限 600 的本地文件。\n"
                  "所有网络请求均可通过「设置 → 代理」走 HTTP/HTTPS 代理。"),
            style="Hint.TLabel", wraplength=560, justify="left",
        ).pack(side="bottom", anchor="w", pady=(12, 0), fill="x")

        # 运行环境
        ttk.Label(f, text="运行环境", font=(self.ui_font, 10, "bold")).pack(anchor="w", pady=(4, 4))
        sys_txt = tk.Text(
            f, height=8, wrap="word", font=(self.mono_font, 9),
            relief="solid", bd=1,
            bg=colors.get("ENTRY_BG", "#fff"), fg=colors.get("FG", "#000"),
            padx=10, pady=8)
        sys_txt.insert("1.0", _collect_system_info())
        sys_txt.configure(state="disabled")
        sys_txt.pack(fill="x")
        self._sys_text = sys_txt

        # 第三方依赖
        ttk.Label(f, text="第三方依赖", font=(self.ui_font, 10, "bold")).pack(anchor="w", pady=(12, 4))
        deps_wrap = ttk.Frame(f)
        deps_wrap.pack(fill="x") # 改为 fill="x" 而不是 expand=True
        cols = ("name", "version", "desc")
        deps_tree = ttk.Treeview(deps_wrap, columns=cols, show="headings", height=5)
        deps_tree.heading("name", text="包名")
        deps_tree.heading("version", text="版本")
        deps_tree.heading("desc", text="用途")
        deps_tree.column("name", width=140, anchor="w", stretch=False)
        deps_tree.column("version", width=100, anchor="w", stretch=False)
        deps_tree.column("desc", width=340, anchor="w")
        vs = ttk.Scrollbar(deps_wrap, orient="vertical", command=deps_tree.yview)
        deps_tree.configure(yscrollcommand=vs.set)
        deps_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        for i, (name, v, desc) in enumerate(_collect_deps()):
            deps_tree.insert("", "end", values=(name, v, desc),
                             tags=("odd",) if i % 2 else ("even",))
        try:
            app._tag_tree(deps_tree)
        except Exception:
            pass
        self._deps_tree = deps_tree

        # 主题监听
        try:
            app.register_theme_listener(self, self._apply_theme)
        except Exception:
            pass

        self.bind("<Escape>", lambda _e: self.destroy())

    # ---------- 主题刷新 ----------
    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.app.colors
        self.colors = c
        try:
            self._sys_text.configure(bg=c["ENTRY_BG"], fg=c["FG"])
            lbl = self._logo_label
            if lbl is not None and lbl.winfo_exists():
                lbl.configure(bg=c["BG"])
            self.app._tag_tree(self._deps_tree)
        except tk.TclError:
            pass

    # ---------- 操作 ----------
    def _copy_info(self):
        parts = [_collect_system_info(), "\n第三方依赖：\n"]
        for name, v, desc in _collect_deps():
            parts.append(f"  {name} {v}  — {desc}\n")
        text = "".join(parts)
        try:
            self.app.clipboard_clear()
            self.app.clipboard_append(text)
            if hasattr(self.app, "_status"):
                self.app._status("系统信息已复制到剪贴板", kind="ok")
        except Exception:
            pass

    def _open_cfg_dir(self):
        try:
            open_path_in_os(_config_dir())
        except Exception as e:
            logging.warning("打开配置目录失败：%s", e)
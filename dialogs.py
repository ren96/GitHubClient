import tkinter as tk
import threading
import webbrowser
import os
import re
from tkinter import ttk, messagebox, filedialog

from oauth import DeviceFlow
from utils import _fmt_bytes, SymbolCheckbutton
from version import __version__ as APP_VERSION
import updater

REPO_NAME_RE = re.compile(r"^[\w.-]{1,100}$")


def _resolve_fonts(parent):
    ui = getattr(parent, "ui_font", None) \
         or getattr(getattr(parent, "app", None), "ui_font", "TkDefaultFont")
    mono = getattr(parent, "mono_font", None) \
           or getattr(getattr(parent, "app", None), "mono_font", "TkFixedFont")
    colors = getattr(parent, "colors", None) \
             or getattr(getattr(parent, "app", None), "colors", {}) or {}
    icon = getattr(parent, "icon_path", None) \
           or getattr(getattr(parent, "app", None), "icon_path", None)
    return ui, mono, colors, icon


def _resolve_app(parent):
    """找到 GitHubApp 实例，用于注册主题监听器。"""
    if parent is None:
        return None
    if hasattr(parent, "register_theme_listener"):
        return parent
    app = getattr(parent, "app", None)
    if app is not None and hasattr(app, "register_theme_listener"):
        return app
    return None


def _register_theme(widget, parent):
    """把 widget._apply_theme 注册到 app 的主题监听器（如果可用）。"""
    app = _resolve_app(parent)
    if app is None:
        return
    cb = getattr(widget, "_apply_theme", None)
    if not callable(cb):
        return
    try:
        app.register_theme_listener(widget, cb)
    except Exception:
        pass


class IssueDialog(tk.Toplevel):
    def __init__(self, parent, title_text, initial_title="", initial_body="",
                 initial_state="open", is_edit=False, available_labels=None,
                 current_labels=None, assignees=""):
        super().__init__(parent)
        self.app = _resolve_app(parent)
        self.title(title_text)
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("760x640")
        self.minsize(560, 460)
        self._labels = available_labels or []
        self._initial_labels = set(current_labels or [])

        ui_font, mono, colors, icon_path = _resolve_fonts(parent)
        self.ui_font = ui_font
        self.mono_font = mono
        self.colors = colors

        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # 底部操作栏
        bar = ttk.Frame(self, padding=(18, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._save())

        # 主内容区
        f = ttk.Frame(self, padding=(18, 14, 18, 0))
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="标题", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.title_var = tk.StringVar(value=initial_title)
        e = ttk.Entry(f, textvariable=self.title_var)
        e.pack(fill="x", pady=(4, 12))
        e.focus_set()
        e.icursor("end")

        mid = ttk.Frame(f)
        mid.pack(fill="x", pady=(0, 12))
        ttk.Label(mid, text="指派人").pack(side="left")
        self.assignee_var = tk.StringVar(value=assignees)
        ttk.Entry(mid, textvariable=self.assignee_var, width=36).pack(side="left", padx=(8, 0))

        if self._labels:
            ttk.Label(f, text="标签（Ctrl 多选）",
                      font=(ui_font, 10, "bold")).pack(anchor="w")
            wrap = ttk.Frame(f)
            wrap.pack(fill="x", pady=(4, 12))
            self.label_list = tk.Listbox(
                wrap, selectmode="multiple", height=4, exportselection=False,
                relief="flat", bd=0, bg=colors.get("ENTRY_BG", "#fff"),
                fg=colors.get("FG", "#000"),
                selectbackground=colors.get("ACCENT", "#0969da"),
                selectforeground="white")
            for lb in self._labels:
                self.label_list.insert("end", lb["name"])
                if lb["name"] in self._initial_labels:
                    self.label_list.selection_set("end")
            self.label_list.pack(side="left", fill="x", expand=True)

        nb = ttk.Notebook(f)
        nb.pack(fill="both", expand=True)

        tab_edit = ttk.Frame(nb, padding=4)
        nb.add(tab_edit, text="✏️ 编辑")

        self.body_text = tk.Text(
            tab_edit, wrap="word", height=10, relief="solid", bd=1,
            font=(mono, 10), undo=True, maxundo=50,
            bg=colors.get("ENTRY_BG", "#fff"), fg=colors.get("FG", "#000"))
        vs = ttk.Scrollbar(tab_edit, orient="vertical", command=self.body_text.yview)
        self.body_text.configure(yscrollcommand=vs.set)
        self.body_text.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.body_text.insert("1.0", initial_body)

        tab_prev = ttk.Frame(nb, padding=4)
        nb.add(tab_prev, text="👁 预览")
        self.preview_text = tk.Text(
            tab_prev, wrap="word", height=10, relief="solid", bd=1,
            font=(ui_font, 10), state="disabled",
            bg=colors.get("ENTRY_BG", "#fff"), fg=colors.get("FG", "#000"),
            padx=8, pady=8)
        self.preview_text.pack(fill="both", expand=True)

        def on_tab_change(e):
            if nb.index(nb.select()) == 1:
                self._render_preview()

        nb.bind("<<NotebookTabChanged>>", on_tab_change)

        self.state_var = None
        if is_edit:
            row = ttk.Frame(f)
            row.pack(anchor="w", pady=(12, 0))
            self.state_var = tk.StringVar(value=initial_state)
            ttk.Radiobutton(row, text="🟢 打开", variable=self.state_var,
                            value="open").pack(side="left", padx=(0, 16))
            ttk.Radiobutton(row, text="🔴 关闭", variable=self.state_var,
                            value="closed").pack(side="left")

        _register_theme(self, parent)

    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.app.colors if self.app else self.colors
        try:
            self.body_text.configure(bg=c["ENTRY_BG"], fg=c["FG"])
            self.preview_text.configure(bg=c["ENTRY_BG"], fg=c["FG"])
            if hasattr(self, "label_list") and self.label_list.winfo_exists():
                self.label_list.configure(
                    bg=c["ENTRY_BG"], fg=c["FG"],
                    selectbackground=c["ACCENT"], selectforeground="white")
        except tk.TclError:
            pass

    def _render_preview(self):
        txt = self.body_text.get("1.0", "end-1c")
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.tag_configure("b", font=(self.ui_font, 10, "bold"))
        self.preview_text.tag_configure("code", font=(self.mono_font, 10))

        lines = txt.split("\n")
        in_code = False
        for line in lines:
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                self.preview_text.insert("end", line + "\n", "code")
            else:
                parts = re.split(r"(\*\*.*?\*\*)", line)
                for p in parts:
                    if p.startswith("**") and p.endswith("**"):
                        self.preview_text.insert("end", p[2:-2], "b")
                    else:
                        self.preview_text.insert("end", p)
                self.preview_text.insert("end", "\n")
        self.preview_text.configure(state="disabled")

    def _save(self):
        title = self.title_var.get().strip()
        if not title:
            messagebox.showwarning("提示", "标题不能为空", parent=self)
            return
        labels = []
        if hasattr(self, "label_list"):
            labels = [self.label_list.get(i) for i in self.label_list.curselection()]
        assignees = [x.strip() for x in self.assignee_var.get().split(",") if x.strip()]
        self.result = {
            "title": title, "body": self.body_text.get("1.0", "end-1c"),
            "state": self.state_var.get() if self.state_var else None,
            "labels": labels, "assignees": assignees,
        }
        self.destroy()


class CreateRepoDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.app = _resolve_app(parent)
        self.title("新建仓库")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("540x420")
        self.minsize(450, 380)

        ui_font, _mono, _colors, icon_path = _resolve_fonts(parent)
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        bar = ttk.Frame(self, padding=(18, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="创建", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))

        f = ttk.Frame(self, padding=(18, 14, 18, 0))
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="仓库名称 *", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.name_var = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.name_var)
        e.pack(fill="x", pady=(4, 4))
        e.focus_set()
        ttk.Label(f, text="字母、数字、.、-、_，最长 100 字符",
                  style="Hint.TLabel").pack(anchor="w")
        ttk.Label(f, text="描述", font=(ui_font, 10, "bold")).pack(anchor="w", pady=(14, 0))
        self.desc_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.desc_var).pack(fill="x", pady=(4, 12))
        self.private_var = tk.BooleanVar()
        self.init_var = tk.BooleanVar(value=True)
        SymbolCheckbutton(f, text="私有仓库", variable=self.private_var).pack(anchor="w")
        SymbolCheckbutton(f, text="自动初始化 README",
                        variable=self.init_var).pack(anchor="w", pady=(6, 0))

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "名称不能为空", parent=self)
            return
        if not REPO_NAME_RE.match(name):
            messagebox.showwarning("提示", "名称格式非法", parent=self)
            return
        self.result = {"name": name, "description": self.desc_var.get().strip(),
                       "private": self.private_var.get(), "auto_init": self.init_var.get()}
        self.destroy()


class EditRepoDialog(tk.Toplevel):
    def __init__(self, parent, repo_data):
        super().__init__(parent)
        self.app = _resolve_app(parent)
        self.title(f"编辑仓库 — {repo_data['full_name']}")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("560x520")
        self.minsize(450, 450)

        ui_font, _mono, _colors, icon_path = _resolve_fonts(parent)
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        bar = ttk.Frame(self, padding=(18, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))

        f = ttk.Frame(self, padding=(18, 14, 18, 0))
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="描述", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.desc_var = tk.StringVar(value=repo_data.get("description") or "")
        ttk.Entry(f, textvariable=self.desc_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="主页", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.home_var = tk.StringVar(value=repo_data.get("homepage") or "")
        ttk.Entry(f, textvariable=self.home_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="Topics（逗号分隔）",
                  font=(ui_font, 10, "bold")).pack(anchor="w")
        self.topics_var = tk.StringVar(
            value=", ".join(repo_data.get("topics") or []))
        ttk.Entry(f, textvariable=self.topics_var).pack(fill="x", pady=(4, 12))

        self.private_var = tk.BooleanVar(value=bool(repo_data.get("private")))
        SymbolCheckbutton(f, text="私有仓库", variable=self.private_var).pack(anchor="w")
        self.archived_var = tk.BooleanVar(value=bool(repo_data.get("archived")))
        SymbolCheckbutton(f, text="归档（只读）", variable=self.archived_var).pack(anchor="w", pady=(6, 0))
        self.repo_data = repo_data

    def _save(self):
        topics = [t.strip() for t in self.topics_var.get().split(",") if t.strip()]
        self.result = {
            "description": self.desc_var.get().strip(),
            "homepage": self.home_var.get().strip(),
            "private": self.private_var.get(),
            "archived": self.archived_var.get(),
            "topics": topics,
        }
        self.destroy()


class CommentDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.app = _resolve_app(parent)
        self.title("发表评论")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("620x450")
        self.minsize(450, 350)
        colors = getattr(parent, "colors", None) \
                 or getattr(getattr(parent, "app", None), "colors", {}) or {}
        self.colors = colors
        mono = getattr(parent, "mono_font", None) \
               or getattr(getattr(parent, "app", None), "mono_font", "TkFixedFont")
        icon_path = getattr(parent, "icon_path", None) \
                    or getattr(getattr(parent, "app", None), "icon_path", None)
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        bar = ttk.Frame(self, padding=(14, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="发送", style="Accent.TButton",
                   command=self._ok).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._ok())

        f = ttk.Frame(self, padding=(14, 14, 14, 0))
        f.pack(fill="both", expand=True)

        self.text = tk.Text(f, wrap="word", font=(mono, 10), undo=True,
                            relief="solid", bd=1,
                            bg=colors.get("ENTRY_BG", "#fff"),
                            fg=colors.get("FG", "#000"))
        self.text.pack(fill="both", expand=True)

        _register_theme(self, parent)

    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.app.colors if self.app else self.colors
        try:
            self.text.configure(bg=c["ENTRY_BG"], fg=c["FG"])
        except tk.TclError:
            pass

    def _ok(self):
        body = self.text.get("1.0", "end-1c").strip()
        if not body:
            messagebox.showwarning("提示", "内容不能为空", parent=self)
            return
        self.result = body
        self.destroy()


class SettingsDialog(tk.Toplevel):
    def __init__(self, parent, cfg):
        super().__init__(parent)
        self.app = _resolve_app(parent)
        self.title("设置")
        self.result = None
        self.cfg = cfg
        self.transient(parent)
        self.grab_set()
        self.geometry("620x820")
        self.minsize(560, 700)

        ui_font, _mono, _colors, icon_path = _resolve_fonts(parent)
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        bar = ttk.Frame(self, padding=(18, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())

        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)

        # 用当前主题背景色初始化 canvas，避免白底闪
        init_bg = (_colors or {}).get("BG", "#f6f8fa")
        canvas = tk.Canvas(outer, borderwidth=0, highlightthickness=0, bg=init_bg)
        self._scroll_canvas = canvas
        vsb = ttk.Scrollbar(outer, orient="vertical", command=canvas.yview)
        canvas.configure(yscrollcommand=vsb.set)
        canvas.pack(side="left", fill="both", expand=True)
        vsb.pack(side="right", fill="y")

        f = ttk.Frame(canvas, padding=18)
        win_id = canvas.create_window((0, 0), window=f, anchor="nw")

        def _on_frame_config(_e):
            canvas.configure(scrollregion=canvas.bbox("all"))

        def _on_canvas_config(e):
            canvas.itemconfigure(win_id, width=e.width)

        f.bind("<Configure>", _on_frame_config)
        canvas.bind("<Configure>", _on_canvas_config)

        ttk.Label(f, text="HTTP / HTTPS 代理（留空直连）",
                  font=(ui_font, 10, "bold")).pack(anchor="w")
        self.proxy_var = tk.StringVar(value=cfg.proxy)
        row_p = ttk.Frame(f)
        row_p.pack(fill="x", pady=(4, 4))
        ttk.Entry(row_p, textvariable=self.proxy_var).pack(side="left", fill="x", expand=True)
        self.test_btn = ttk.Button(row_p, text="测试", width=8,
                                   command=self._test_proxy)
        self.test_btn.pack(side="left", padx=(6, 0))
        self.proxy_status = ttk.Label(f, text="", style="Hint.TLabel")
        self.proxy_status.pack(anchor="w", pady=(0, 12))

        ttk.Label(f, text="OAuth App Client ID",
                  font=(ui_font, 10, "bold")).pack(anchor="w")
        self.oauth_var = tk.StringVar(value=cfg.oauth_client_id)
        ttk.Entry(f, textvariable=self.oauth_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="主题", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.theme_var = tk.StringVar(value=cfg.theme)
        t_row = ttk.Frame(f)
        t_row.pack(anchor="w", pady=(4, 12))
        for txt, val in [("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark")]:
            ttk.Radiobutton(t_row, text=txt, variable=self.theme_var,
                            value=val).pack(side="left", padx=(0, 12))

        ttk.Label(f, text="界面字号大小", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.font_var = tk.IntVar(value=getattr(cfg, "font_size", 10))
        ttk.Spinbox(f, from_=8, to=16, textvariable=self.font_var, width=10).pack(anchor="w", pady=(4, 12))

        ttk.Label(f, text="通知轮询间隔（秒，0 关闭）",
                  font=(ui_font, 10, "bold")).pack(anchor="w")
        self.poll_var = tk.IntVar(value=cfg.poll_interval)
        ttk.Spinbox(f, from_=0, to=3600, increment=30,
                    textvariable=self.poll_var, width=10).pack(anchor="w", pady=(4, 12))

        ttk.Separator(f, orient="horizontal").pack(fill="x", pady=(6, 10))
        ttk.Label(f, text="自动更新", font=(ui_font, 10, "bold")).pack(anchor="w")
        ttk.Label(f, text="更新源仓库（owner/repo，留空禁用自动检查）",
                  style="Hint.TLabel").pack(anchor="w")
        self.update_repo_var = tk.StringVar(value=cfg.update_repo)
        ttk.Entry(f, textvariable=self.update_repo_var).pack(fill="x", pady=(2, 8))

        row_u = ttk.Frame(f)
        row_u.pack(fill="x", pady=(0, 6))
        ttk.Label(row_u, text="通道：").pack(side="left")
        self.update_channel_var = tk.StringVar(value=cfg.update_channel)
        ttk.Radiobutton(row_u, text="稳定版", variable=self.update_channel_var,
                        value="stable").pack(side="left", padx=(0, 10))
        ttk.Radiobutton(row_u, text="测试版", variable=self.update_channel_var,
                        value="beta").pack(side="left")

        self.auto_check_var = tk.BooleanVar(value=cfg.auto_check_update)
        SymbolCheckbutton(f, text="启动时自动检查更新",
                        variable=self.auto_check_var).pack(anchor="w")

        ttk.Label(f, text=f"当前版本：v{APP_VERSION}",
                  style="Hint.TLabel").pack(anchor="w", pady=(8, 0))

        _register_theme(self, parent)

    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        app = self.app
        if app is None:
            return
        try:
            self._scroll_canvas.configure(bg=app.colors["BG"])
        except tk.TclError:
            pass

    def _test_proxy(self):
        self.test_btn.configure(state="disabled")
        self.proxy_status.configure(text="测试中…", style="Hint.TLabel")
        proxy = self.proxy_var.get().strip()
        app = self.app

        def work():
            import time
            import requests
            start = time.time()
            r = requests.get("https://api.github.com/rate_limit",
                             proxies={"http": proxy, "https": proxy} if proxy else None,
                             timeout=8)
            r.raise_for_status()
            return (time.time() - start) * 1000

        def ok(ms):
            self.test_btn.configure(state="normal")
            self.proxy_status.configure(
                text=f"✅ 连接成功，延迟 {ms:.0f}ms", style="Success.TLabel")

        def err(e):
            self.test_btn.configure(state="normal")
            self.proxy_status.configure(
                text=f"❌ 失败：{e}", style="Danger.TLabel")

        if app is not None:
            app.run_async(work, ok, err)

    def _save(self):
        try:
            poll = int(self.poll_var.get() or 0)
            font_size = int(self.font_var.get() or 10)
        except (tk.TclError, ValueError):
            poll = 0
            font_size = 10
        self.result = {
            "proxy": self.proxy_var.get().strip(),
            "oauth_client_id": self.oauth_var.get().strip(),
            "theme": self.theme_var.get(),
            "poll_interval": poll,
            "font_size": font_size,
            "update_repo": self.update_repo_var.get().strip(),
            "update_channel": self.update_channel_var.get() or "stable",
            "auto_check_update": bool(self.auto_check_var.get()),
        }
        self.destroy()


class CreatePRDialog(tk.Toplevel):
    def __init__(self, parent, branches):
        super().__init__(parent)
        self.app = _resolve_app(parent)
        self.title("新建 Pull Request")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("600x550")
        self.minsize(450, 450)

        ui_font, mono, colors, icon_path = _resolve_fonts(parent)
        self.colors = colors
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        bar = ttk.Frame(self, padding=(18, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="创建", style="Accent.TButton", command=self._save).pack(side="right", padx=(0, 8))

        f = ttk.Frame(self, padding=(18, 14, 18, 0))
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="来源分支 (head)", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.head_var = tk.StringVar()
        ttk.Combobox(f, textvariable=self.head_var, values=branches).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="目标分支 (base)", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.base_var = tk.StringVar()
        ttk.Combobox(f, textvariable=self.base_var, values=branches).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="标题 *", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.title_var = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.title_var)
        e.pack(fill="x", pady=(4, 12))
        e.focus_set()

        ttk.Label(f, text="描述", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.body_text = tk.Text(
            f, wrap="word", height=8, font=(mono, 10), undo=True,
            bg=colors.get("ENTRY_BG", "#fff"), fg=colors.get("FG", "#000"))
        self.body_text.pack(fill="both", expand=True, pady=(4, 12))

        self.draft_var = tk.BooleanVar(value=False)
        SymbolCheckbutton(f, text="作为草稿提交", variable=self.draft_var).pack(anchor="w")

        _register_theme(self, parent)

    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.app.colors if self.app else self.colors
        try:
            self.body_text.configure(bg=c["ENTRY_BG"], fg=c["FG"])
        except tk.TclError:
            pass

    def _save(self):
        t = self.title_var.get().strip()
        h = self.head_var.get().strip()
        b = self.base_var.get().strip()
        if not t or not h or not b:
            messagebox.showwarning("提示", "标题、来源分支、目标分支不能为空", parent=self)
            return
        self.result = {
            "title": t, "head": h, "base": b,
            "body": self.body_text.get("1.0", "end-1c"),
            "draft": self.draft_var.get()
        }
        self.destroy()


class CreateReleaseDialog(tk.Toplevel):
    def __init__(self, parent):
        super().__init__(parent)
        self.app = _resolve_app(parent)
        self.title("新建 Release")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("600x550")
        self.minsize(450, 450)

        ui_font, mono, colors, icon_path = _resolve_fonts(parent)
        self.colors = colors
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        bar = ttk.Frame(self, padding=(18, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="发布", style="Accent.TButton", command=self._save).pack(side="right", padx=(0, 8))

        f = ttk.Frame(self, padding=(18, 14, 18, 0))
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="标签 (Tag) *", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.tag_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.tag_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="标题", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.name_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.name_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="说明", font=(ui_font, 10, "bold")).pack(anchor="w")
        self.body_text = tk.Text(
            f, wrap="word", height=8, font=(mono, 10), undo=True,
            bg=colors.get("ENTRY_BG", "#fff"), fg=colors.get("FG", "#000"))
        self.body_text.pack(fill="both", expand=True, pady=(4, 12))

        row = ttk.Frame(f)
        row.pack(fill="x")
        self.draft_var = tk.BooleanVar(value=False)
        SymbolCheckbutton(row, text="草稿", variable=self.draft_var).pack(side="left")
        self.pre_var = tk.BooleanVar(value=False)
        SymbolCheckbutton(row, text="预发布 (Pre-release)", variable=self.pre_var).pack(side="left", padx=(16, 0))

        _register_theme(self, parent)

    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.app.colors if self.app else self.colors
        try:
            self.body_text.configure(bg=c["ENTRY_BG"], fg=c["FG"])
        except tk.TclError:
            pass

    def _save(self):
        tag = self.tag_var.get().strip()
        if not tag:
            messagebox.showwarning("提示", "标签不能为空", parent=self)
            return
        self.result = {
            "tag_name": tag, "name": self.name_var.get().strip(),
            "body": self.body_text.get("1.0", "end-1c"),
            "draft": self.draft_var.get(), "prerelease": self.pre_var.get()
        }
        self.destroy()


class OAuthDialog(tk.Toplevel):
    """Device Flow 授权对话框"""

    def __init__(self, parent, client_id, proxy=""):
        super().__init__(parent)
        self.app = parent
        self.title("GitHub 授权登录")
        self.token = None
        self._cancel = False
        self._info = None
        self._verification_url = ""
        self._gen = 0
        self.transient(parent)
        self.grab_set()
        self.geometry("520x360")

        ui_font, mono, colors, icon_path = _resolve_fonts(parent)
        self.colors = colors
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass
        self.flow = DeviceFlow(client_id, proxy=proxy)

        f = ttk.Frame(self, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="🔐 通过 GitHub 授权登录",
                  font=(ui_font, 14, "bold")).pack(pady=(0, 10))
        self.hint = ttk.Label(f, text="正在请求授权码…", style="Hint.TLabel",
                              wraplength=460, justify="center")
        self.hint.pack(pady=(0, 14))
        self.code_var = tk.StringVar(value="")
        self.code_label = ttk.Label(f, textvariable=self.code_var,
                                    font=(mono, 22, "bold"))
        self.code_label.pack(pady=(0, 14))
        self.link = ttk.Label(f, text="", foreground=colors.get("ACCENT", "#0969da"),
                              cursor="hand2")
        self.link.pack(pady=(0, 14))
        self.link.bind("<Button-1>", lambda _e: self._open_link())

        self.status = ttk.Label(f, text="", style="Hint.TLabel")
        self.status.pack(pady=(0, 10))

        bar = ttk.Frame(f)
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self._on_cancel).pack(side="right")
        ttk.Button(bar, text="重新生成授权码",
                   command=self._restart).pack(side="right", padx=(0, 8))

        self.protocol("WM_DELETE_WINDOW", self._on_cancel)

        _register_theme(self, parent)
        self.after(100, self._start)

    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.app.colors if self.app else self.colors
        try:
            self.link.configure(foreground=c.get("ACCENT", "#0969da"))
        except tk.TclError:
            pass

    def _safe_call(self, fn):
        try:
            if not self.winfo_exists():
                return
            fn()
        except tk.TclError:
            pass

    def _open_link(self):
        if self._verification_url:
            webbrowser.open(self._verification_url)

    def _start(self):
        gen = self._gen

        def work():
            return self.flow.start()

        def ok(info):
            if self._cancel or gen != self._gen:
                return
            self._info = info
            self._verification_url = info.get("verification_uri", "")
            self._safe_call(lambda: self.code_var.set(info.get("user_code", "")))
            self._safe_call(lambda: self.hint.configure(text="请访问下方链接，输入授权码："))
            self._safe_call(lambda: self.link.configure(text=self._verification_url))
            self._safe_call(lambda: self.status.configure(text="等待浏览器授权…"))
            self._poll_thread(gen)

        def err(e):
            if gen != self._gen:
                return
            self._safe_call(lambda: self.status.configure(
                text=f"启动失败：{e}", style="Danger.TLabel"))

        self.app.run_async(work, ok, err)

    def _poll_thread(self, gen):
        def worker():
            def ui(fn):
                if gen != self._gen or self._cancel:
                    return
                try:
                    self.after(0, fn)
                except tk.TclError:
                    pass

            try:
                tok = self.flow.wait_for_token(
                    self._info,
                    on_tick=lambda s: ui(lambda sec=s: self._safe_call(
                        lambda: self.status.configure(text=f"等待授权… 剩余 {sec}s"))),
                    cancel_flag=lambda: self._cancel or gen != self._gen,
                )
                ui(lambda: self._safe_call(lambda: self._success(tok)))
            except Exception as e:
                err_msg = str(e)
                ui(lambda: self._safe_call(lambda: self._fail(err_msg)))

        threading.Thread(target=worker, daemon=True).start()

    def _success(self, tok):
        self.token = tok
        self._cancel = True
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _fail(self, msg):
        try:
            self.status.configure(text=f"❌ {msg}", style="Danger.TLabel")
        except tk.TclError:
            pass

    def _on_cancel(self):
        self._cancel = True
        self._gen += 1
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _restart(self):
        self._gen += 1
        self._cancel = False
        self._safe_call(lambda: self.code_var.set(""))
        self._safe_call(lambda: self.link.configure(text=""))
        self._safe_call(lambda: self.status.configure(text="", style="Hint.TLabel"))
        self._safe_call(lambda: self.hint.configure(text="正在请求授权码…"))
        self._start()


class UploadProjectDialog(tk.Toplevel):
    """把本地项目上传到 GitHub 仓库"""

    def __init__(self, parent, default_dir=""):
        super().__init__(parent)
        self.app = _resolve_app(parent)
        self.title("上传项目到 GitHub")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("680x680")
        self.minsize(580, 600)

        ui_font, _mono, _colors, icon_path = _resolve_fonts(parent)
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # 底部操作栏（先布局，确保始终可见）
        bar = ttk.Frame(self, padding=(18, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="开始上传", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))

        f = ttk.Frame(self, padding=(18, 14, 18, 0))
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="本地目录 *",
                  font=(ui_font, 10, "bold")).pack(anchor="w")
        row = ttk.Frame(f)
        row.pack(fill="x", pady=(4, 12))
        self.dir_var = tk.StringVar(value=default_dir)
        ttk.Entry(row, textvariable=self.dir_var).pack(
            side="left", fill="x", expand=True)
        ttk.Button(row, text="浏览…", command=self._browse).pack(
            side="left", padx=(6, 0))

        ttk.Label(f, text="仓库名称 *",
                  font=(ui_font, 10, "bold")).pack(anchor="w")
        self.name_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.name_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="描述",
                  font=(ui_font, 10, "bold")).pack(anchor="w")
        self.desc_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.desc_var).pack(fill="x", pady=(4, 12))

        opts = ttk.Frame(f)
        opts.pack(fill="x", pady=(0, 12))
        self.private_var = tk.BooleanVar()
        SymbolCheckbutton(opts, text="私有仓库",
                        variable=self.private_var).pack(side="left")
        self.ignore_var = tk.BooleanVar(value=True)
        SymbolCheckbutton(opts, text="如无 .gitignore 则自动生成通用版本",
                        variable=self.ignore_var).pack(side="left", padx=(16, 0))

        ttk.Label(f, text="分支名",
                  font=(ui_font, 10, "bold")).pack(anchor="w")
        self.branch_var = tk.StringVar(value="main")
        ttk.Entry(f, textvariable=self.branch_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="首次提交信息",
                  font=(ui_font, 10, "bold")).pack(anchor="w")
        self.msg_var = tk.StringVar(value="Initial commit")
        ttk.Entry(f, textvariable=self.msg_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, style="Hint.TLabel", justify="left",
                  text=("· 如果同名仓库已存在，会直接推送到该仓库\n"
                        "· 如果目录还不是 Git 仓库，会自动 git init\n"
                        "· 需要本机安装 Git 且在 PATH 中")).pack(anchor="w")

        if default_dir:
            self._apply_dir_defaults(default_dir)

    def _browse(self):
        d = filedialog.askdirectory(title="选择要上传的本地项目目录")
        if d:
            self.dir_var.set(d)
            self._apply_dir_defaults(d)

    def _apply_dir_defaults(self, d):
        base = os.path.basename(os.path.normpath(d)) or ""
        if base and not self.name_var.get():
            safe = re.sub(r"[^\w.-]", "-", base).strip("-._")
            if safe:
                self.name_var.set(safe[:100])

    def _save(self):
        local = self.dir_var.get().strip()
        if not local or not os.path.isdir(local):
            messagebox.showwarning("提示", "请选择有效的本地目录", parent=self)
            return
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "仓库名不能为空", parent=self)
            return
        if not REPO_NAME_RE.match(name):
            messagebox.showwarning(
                "提示", "仓库名格式非法（字母/数字/._-，最长100字符）", parent=self)
            return
        branch = self.branch_var.get().strip() or "main"
        if not re.match(r"^[\w./-]+$", branch):
            messagebox.showwarning("提示", "分支名格式非法", parent=self)
            return
        msg = self.msg_var.get().strip() or "Initial commit"
        self.result = {
            "local": local,
            "name": name,
            "description": self.desc_var.get().strip(),
            "private": self.private_var.get(),
            "branch": branch,
            "commit_message": msg,
            "add_gitignore": self.ignore_var.get(),
        }
        self.destroy()


class UpdateDialog(tk.Toplevel):
    """发现新版本时的对话框：展示 release notes、下载安装包、一键安装。"""

    def __init__(self, parent, release_info, api, repo):
        super().__init__(parent)
        self.app = getattr(parent, "app", parent) or parent
        self.info = release_info
        self.api = api
        self.repo = repo
        self._downloaded = None

        # 按用户配置的通道挑选安装包
        channel = (getattr(getattr(self.app, "cfg", None), "update_channel", "stable") or "stable")
        self._asset = (
            updater.pick_asset(self.info.assets, channel=channel)
            or updater.pick_asset(self.info.assets, channel="stable")
            or updater.pick_asset(self.info.assets, channel="beta")
        )

        self.title("发现新版本")
        self.geometry("680x600")
        self.minsize(560, 480)
        self.transient(parent)
        self.grab_set()

        ui_font, mono_font, colors, icon_path = _resolve_fonts(parent)
        self.ui_font = ui_font
        self.mono_font = mono_font
        self.colors = colors
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        # 底部按钮栏
        self._bar = ttk.Frame(self, padding=(16, 10))
        self._bar.pack(fill="x", side="bottom")

        self.primary_btn = ttk.Button(
            self._bar,
            text="下载并安装" if self._asset else "浏览器打开",
            style="Accent.TButton",
            command=self._on_primary,
        )
        self.primary_btn.pack(side="left")

        ttk.Button(self._bar, text="浏览器打开",
                   command=self._open_browser).pack(side="left", padx=(6, 0))

        self.skip_btn = ttk.Button(self._bar, text="忽略此版本", command=self._skip)
        self.skip_btn.pack(side="left", padx=(6, 0))

        ttk.Button(self._bar, text="稍后提醒", command=self.destroy).pack(side="right")

        # 主内容区
        f = ttk.Frame(self, padding=(16, 14, 16, 0))
        f.pack(fill="both", expand=True)

        head = ttk.Frame(f)
        head.pack(fill="x", pady=(0, 8))
        ttk.Label(head, text=f"🎉 发现新版本 v{self.info.version}",
                  font=(ui_font, 15, "bold")).pack(anchor="w")
        tag_line = "预发布版本" if self.info.prerelease else "稳定版本"
        ttk.Label(
            head,
            text=(f"当前版本 v{APP_VERSION}    →    最新版本 v{self.info.version}    ·    {tag_line}\n"
                  f"发布时间：{(self.info.published_at or '')[:10] or '—'}"),
            style="Hint.TLabel", justify="left",
        ).pack(anchor="w", pady=(4, 0))

        ttk.Label(f, text="更新说明", font=(ui_font, 10, "bold")).pack(anchor="w", pady=(6, 4))
        notes_wrap = ttk.Frame(f)
        notes_wrap.pack(fill="both", expand=True, pady=(0, 10))
        notes = tk.Text(
            notes_wrap, wrap="word", height=12,
            font=(mono_font, 9),
            bg=colors.get("ENTRY_BG", "#fff"),
            fg=colors.get("FG", "#000"),
            relief="solid", bd=1, padx=8, pady=8,
        )
        self._notes_text = notes
        vs = ttk.Scrollbar(notes_wrap, orient="vertical", command=notes.yview)
        notes.configure(yscrollcommand=vs.set)
        notes.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        notes.insert("1.0", self.info.body or "（无说明）")
        notes.configure(state="disabled")

        asset_info = ttk.Frame(f)
        asset_info.pack(fill="x", pady=(0, 6))
        if self._asset:
            size = _fmt_bytes(self._asset.get("size", 0))
            ttk.Label(asset_info,
                      text=f"📦 推荐文件：{self._asset.get('name', '?')}  ({size})"
                      ).pack(anchor="w")
        else:
            ttk.Label(asset_info,
                      text="⚠️ 该版本没有适配当前平台的可执行文件，可前往浏览器页面下载。",
                      style="Danger.TLabel").pack(anchor="w")

        self.progress = ttk.Progressbar(f, mode="determinate", maximum=100)
        self.speed_lbl = ttk.Label(f, text="", style="Hint.TLabel")

        self.bind("<Escape>", lambda _e: self.destroy())

        _register_theme(self, parent)

    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        c = getattr(self.app, "colors", None) or self.colors
        try:
            self._notes_text.configure(bg=c["ENTRY_BG"], fg=c["FG"])
        except tk.TclError:
            pass

    def _open_browser(self):
        if self.info.html_url:
            webbrowser.open(self.info.html_url)

    def _skip(self):
        try:
            self.app.cfg.skipped_version = self.info.version
            self.app.cfg.save()
            self.app._status(f"已忽略版本 v{self.info.version}")
        except Exception:
            pass
        self.destroy()

    def _on_primary(self):
        if not self._asset:
            self._open_browser()
            return
        if self._downloaded:
            self._install_now(self._downloaded)
            return
        self._start_download()

    def _install_now(self, path):
        try:
            updater.apply_update(path)
            self.app._status("已启动安装程序")
        except Exception as e:
            messagebox.showerror("启动失败", str(e), parent=self)

    def _start_download(self):
        dest = filedialog.askdirectory(title="选择保存目录", parent=self)
        if not dest:
            return
        self.primary_btn.configure(state="disabled", text="下载中…")
        self.progress.configure(value=0)
        if not self.progress.winfo_ismapped():
            try:
                self.progress.pack(fill="x", pady=(4, 0), before=self._bar)
            except tk.TclError:
                self.progress.pack(fill="x", pady=(4, 0))
        if not self.speed_lbl.winfo_ismapped():
            try:
                self.speed_lbl.pack(fill="x", pady=(2, 0), before=self._bar)
            except tk.TclError:
                self.speed_lbl.pack(fill="x", pady=(2, 0))
        self.speed_lbl.configure(text="正在连接…")

        asset = self._asset
        self.app._status(f"正在下载 {asset.get('name')}…")

        def work():
            return self.api.download_asset(
                self.repo, asset, dest,
                on_progress=lambda p, speed=0: self.app.after(
                    0, lambda v=p, s=speed: self._update_progress(v, s)),
            )

        def ok(path):
            if not self.winfo_exists():
                return
            self._downloaded = path
            self._update_progress(1.0, 0)
            self.speed_lbl.configure(text="下载完成")
            self.primary_btn.configure(state="normal", text="立即安装")
            self.app._status(f"下载完成：{path}")
            if messagebox.askyesno(
                    "下载完成",
                    f"安装包已保存到：\n{path}\n\n是否立即启动安装程序？",
                    parent=self):
                self._install_now(path)

        def err(e):
            if not self.winfo_exists():
                return
            self.primary_btn.configure(state="normal",
                                       text="下载并安装" if self._asset else "浏览器打开")
            try:
                self.progress.pack_forget()
                self.speed_lbl.pack_forget()
            except Exception:
                pass
            messagebox.showerror("下载失败", str(e), parent=self)

        self.app.run_async(work, ok, err)

    def _update_progress(self, p, speed=0):
        try:
            if self.winfo_exists():
                self.progress.configure(value=max(0, min(100, p * 100)))
                if speed > 0:
                    self.speed_lbl.configure(
                        text=f"{_fmt_bytes(speed)}/s  ·  已完成 {p * 100:.1f}%")
        except tk.TclError:
            pass


class AssetPickerDialog(tk.Toplevel):
    """当 Release 包含多个文件时，让用户选择需要下载哪些。"""

    def __init__(self, parent, repo, assets):
        super().__init__(parent)
        self.app = _resolve_app(parent)
        self.title("选择要下载的文件")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("680x480")
        self.minsize(520, 360)

        ui_font, _mono, colors, icon_path = _resolve_fonts(parent)
        self.colors = colors
        if icon_path:
            try:
                self.iconbitmap(icon_path)
            except Exception:
                pass

        bar = ttk.Frame(self, padding=(16, 10))
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="下载所选", style="Accent.TButton",
                   command=self._ok).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())

        f = ttk.Frame(self, padding=(16, 14, 16, 0))
        f.pack(fill="both", expand=True)

        ttk.Label(f, text=f"{repo}", font=(ui_font, 11, "bold")).pack(anchor="w")
        ttk.Label(
            f,
            text=f"该 Release 共 {len(assets)} 个文件。按住 Ctrl / Shift 可多选，双击可立即下载。",
            style="Hint.TLabel",
        ).pack(anchor="w", pady=(2, 8))

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)

        self.listbox = tk.Listbox(
            body, selectmode="extended", exportselection=False,
            font=(ui_font, 10),
            bg=colors.get("ENTRY_BG", "#fff"),
            fg=colors.get("FG", "#000"),
            selectbackground=colors.get("ACCENT", "#0969da"),
            selectforeground="white",
            relief="flat", bd=0, highlightthickness=0,
        )
        vs = ttk.Scrollbar(body, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=vs.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.listbox.bind("<Double-1>", lambda _e: self._ok())

        self._assets = list(assets)
        for a in self._assets:
            size = _fmt_bytes(a.get("size", 0))
            self.listbox.insert("end", f"{a.get('name', '?')}    ({size})")

        if self._assets:
            self.listbox.selection_set(0)

        tools = ttk.Frame(f)
        tools.pack(fill="x", pady=(8, 0))
        ttk.Button(tools, text="全选",
                   command=lambda: self.listbox.selection_set(0, "end")).pack(side="left")
        ttk.Button(tools, text="反选", command=self._invert).pack(side="left", padx=(6, 0))

        _register_theme(self, parent)

    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.app.colors if self.app else self.colors
        try:
            self.listbox.configure(
                bg=c["ENTRY_BG"], fg=c["FG"],
                selectbackground=c["ACCENT"], selectforeground="white")
        except tk.TclError:
            pass

    def _invert(self):
        sel = set(self.listbox.curselection())
        self.listbox.selection_clear(0, "end")
        for i in range(self.listbox.size()):
            if i not in sel:
                self.listbox.selection_set(i)

    def _ok(self):
        sel = self.listbox.curselection()
        if not sel:
            messagebox.showinfo("提示", "请选择至少一个文件", parent=self)
            return
        self.result = [self._assets[i] for i in sel]
        self.destroy()
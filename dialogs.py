import tkinter as tk
import threading
import webbrowser
from tkinter import ttk, messagebox
import re

from oauth import DeviceFlow

REPO_NAME_RE = re.compile(r"^[\w.-]{1,100}$")


class IssueDialog(tk.Toplevel):
    def __init__(self, parent, title_text, initial_title="", initial_body="",
                 initial_state="open", is_edit=False, available_labels=None,
                 current_labels=None, assignees=""):
        super().__init__(parent)
        self.title(title_text)
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("760x640")
        self.minsize(560, 460)
        self._labels = available_labels or []
        self._initial_labels = set(current_labels or [])
        mono = getattr(parent, "mono_font", "TkFixedFont")
        colors = getattr(parent, "colors", {})

        try:
            self.iconbitmap(parent.icon_path)
        except Exception:
            pass

        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="标题", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
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
                      font=(parent.ui_font, 10, "bold")).pack(anchor="w")
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

        # 编辑与预览 tab
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
            font=(parent.ui_font, 10), state="disabled",
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

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(16, 0))
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._save())

    def _render_preview(self):
        txt = self.body_text.get("1.0", "end-1c")
        self.preview_text.configure(state="normal")
        self.preview_text.delete("1.0", "end")
        self.preview_text.tag_configure("b", font=(
        self.ui_font if hasattr(self, 'ui_font') else "TkDefaultFont", 10, "bold"))
        self.preview_text.tag_configure("code", font=("Consolas", 10), background="#f0f0f0")

        # 极简 Markdown 渲染
        lines = txt.split("\n")
        in_code = False
        for line in lines:
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                self.preview_text.insert("end", line + "\n", "code")
            else:
                # 简易加粗替换
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
        self.title("新建仓库")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("540x400")
        self.resizable(False, False)
        try:
            self.iconbitmap(parent.icon_path)
        except Exception:
            pass
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="仓库名称 *", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.name_var = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.name_var)
        e.pack(fill="x", pady=(4, 4))
        e.focus_set()
        ttk.Label(f, text="字母、数字、.、-、_，最长 100 字符",
                  style="Hint.TLabel").pack(anchor="w")
        ttk.Label(f, text="描述", font=(parent.ui_font, 10, "bold")).pack(anchor="w", pady=(14, 0))
        self.desc_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.desc_var).pack(fill="x", pady=(4, 12))
        self.private_var = tk.BooleanVar()
        self.init_var = tk.BooleanVar(value=True)
        ttk.Checkbutton(f, text="私有仓库", variable=self.private_var).pack(anchor="w")
        ttk.Checkbutton(f, text="自动初始化 README",
                        variable=self.init_var).pack(anchor="w", pady=(6, 0))
        bar = ttk.Frame(f)
        bar.pack(fill="x", side="bottom", pady=(18, 0))
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="创建", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))

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
        self.title(f"编辑仓库 — {repo_data['full_name']}")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("560x440")
        try:
            self.iconbitmap(parent.icon_path)
        except Exception:
            pass
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="描述", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.desc_var = tk.StringVar(value=repo_data.get("description") or "")
        ttk.Entry(f, textvariable=self.desc_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="主页", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.home_var = tk.StringVar(value=repo_data.get("homepage") or "")
        ttk.Entry(f, textvariable=self.home_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="Topics（逗号分隔）",
                  font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.topics_var = tk.StringVar(
            value=", ".join(repo_data.get("topics") or []))
        ttk.Entry(f, textvariable=self.topics_var).pack(fill="x", pady=(4, 12))

        self.private_var = tk.BooleanVar(value=bool(repo_data.get("private")))
        ttk.Checkbutton(f, text="私有仓库", variable=self.private_var).pack(anchor="w")
        self.archived_var = tk.BooleanVar(value=bool(repo_data.get("archived")))
        ttk.Checkbutton(f, text="归档（只读）", variable=self.archived_var).pack(anchor="w", pady=(6, 0))

        bar = ttk.Frame(f)
        bar.pack(fill="x", side="bottom", pady=(18, 0))
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))
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
        self.title("发表评论")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("620x400")
        colors = getattr(parent, "colors", {})
        try:
            self.iconbitmap(parent.icon_path)
        except Exception:
            pass
        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        mono = getattr(parent, "mono_font", "TkFixedFont")
        self.text = tk.Text(f, wrap="word", font=(mono, 10), undo=True,
                            relief="solid", bd=1,
                            bg=colors.get("ENTRY_BG", "#fff"),
                            fg=colors.get("FG", "#000"))
        self.text.pack(fill="both", expand=True)
        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="发送", style="Accent.TButton",
                   command=self._ok).pack(side="right", padx=(0, 8))
        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Control-Return>", lambda _e: self._ok())

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
        self.title("设置")
        self.result = None
        self.app = parent
        self.cfg = cfg
        self.transient(parent)
        self.grab_set()
        self.geometry("600x600")

        try:
            self.iconbitmap(parent.icon_path)
        except Exception:
            pass

        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="HTTP / HTTPS 代理（留空直连）",
                  font=(parent.ui_font, 10, "bold")).pack(anchor="w")
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
                  font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.oauth_var = tk.StringVar(value=cfg.oauth_client_id)
        ttk.Entry(f, textvariable=self.oauth_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="主题", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.theme_var = tk.StringVar(value=cfg.theme)
        t_row = ttk.Frame(f)
        t_row.pack(anchor="w", pady=(4, 12))
        for txt, val in [("跟随系统", "auto"), ("浅色", "light"), ("深色", "dark")]:
            ttk.Radiobutton(t_row, text=txt, variable=self.theme_var,
                            value=val).pack(side="left", padx=(0, 12))

        # 字号
        ttk.Label(f, text="界面字号大小", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.font_var = tk.IntVar(value=getattr(cfg, "font_size", 10))
        ttk.Spinbox(f, from_=8, to=16, textvariable=self.font_var, width=10).pack(anchor="w", pady=(4, 12))

        # 轮询
        ttk.Label(f, text="通知轮询间隔（秒，0 关闭）",
                  font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.poll_var = tk.IntVar(value=cfg.poll_interval)
        ttk.Spinbox(f, from_=0, to=3600, increment=30,
                    textvariable=self.poll_var, width=10).pack(anchor="w", pady=(4, 12))

        bar = ttk.Frame(f)
        bar.pack(fill="x", side="bottom", pady=(14, 0))
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))

    def _test_proxy(self):
        self.test_btn.configure(state="disabled")
        self.proxy_status.configure(text="测试中…", style="Hint.TLabel")
        proxy = self.proxy_var.get().strip()

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

        self.app.run_async(work, ok, err)

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
        }
        self.destroy()


class CreatePRDialog(tk.Toplevel):
    def __init__(self, parent, branches):
        super().__init__(parent)
        self.title("新建 Pull Request")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("600x520")
        try:
            self.iconbitmap(parent.icon_path)
        except Exception:
            pass
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="来源分支 (head)", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.head_var = tk.StringVar()
        ttk.Combobox(f, textvariable=self.head_var, values=branches).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="目标分支 (base)", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.base_var = tk.StringVar()
        ttk.Combobox(f, textvariable=self.base_var, values=branches).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="标题 *", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.title_var = tk.StringVar()
        e = ttk.Entry(f, textvariable=self.title_var)
        e.pack(fill="x", pady=(4, 12))
        e.focus_set()

        ttk.Label(f, text="描述", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        mono = getattr(parent, "mono_font", "TkFixedFont")
        self.body_text = tk.Text(f, wrap="word", height=8, font=(mono, 10), undo=True)
        self.body_text.pack(fill="both", expand=True, pady=(4, 12))

        self.draft_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(f, text="作为草稿提交", variable=self.draft_var).pack(anchor="w")

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(16, 0))
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="创建", style="Accent.TButton", command=self._save).pack(side="right", padx=(0, 8))

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
        self.title("新建 Release")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("600x520")
        try:
            self.iconbitmap(parent.icon_path)
        except Exception:
            pass
        f = ttk.Frame(self, padding=18)
        f.pack(fill="both", expand=True)

        ttk.Label(f, text="标签 (Tag) *", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.tag_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.tag_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="标题", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        self.name_var = tk.StringVar()
        ttk.Entry(f, textvariable=self.name_var).pack(fill="x", pady=(4, 12))

        ttk.Label(f, text="说明", font=(parent.ui_font, 10, "bold")).pack(anchor="w")
        mono = getattr(parent, "mono_font", "TkFixedFont")
        self.body_text = tk.Text(f, wrap="word", height=8, font=(mono, 10), undo=True)
        self.body_text.pack(fill="both", expand=True, pady=(4, 12))

        row = ttk.Frame(f)
        row.pack(fill="x")
        self.draft_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="草稿", variable=self.draft_var).pack(side="left")
        self.pre_var = tk.BooleanVar(value=False)
        ttk.Checkbutton(row, text="预发布 (Pre-release)", variable=self.pre_var).pack(side="left", padx=(16, 0))

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(16, 0))
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="发布", style="Accent.TButton", command=self._save).pack(side="right", padx=(0, 8))

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
        self.transient(parent)
        self.grab_set()
        self.geometry("520x360")
        try:
            self.iconbitmap(parent.icon_path)
        except Exception:
            pass
        self.flow = DeviceFlow(client_id, proxy=proxy)

        f = ttk.Frame(self, padding=20)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="🔐 通过 GitHub 授权登录",
                  font=(parent.ui_font, 14, "bold")).pack(pady=(0, 10))
        self.hint = ttk.Label(f, text="正在请求授权码…", style="Hint.TLabel",
                              wraplength=460, justify="center")
        self.hint.pack(pady=(0, 14))
        self.code_var = tk.StringVar(value="")
        self.code_label = ttk.Label(f, textvariable=self.code_var,
                                    font=(parent.mono_font, 22, "bold"))
        self.code_label.pack(pady=(0, 14))
        self.link = ttk.Label(f, text="", foreground=parent.colors.get("ACCENT", "#0969da"),
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
        self.after(100, self._start)

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
        def work():
            return self.flow.start()

        def ok(info):
            if self._cancel:
                return
            self._info = info
            self._verification_url = info.get("verification_uri", "")
            self._safe_call(lambda: self.code_var.set(info.get("user_code", "")))
            self._safe_call(lambda: self.hint.configure(text="请访问下方链接，输入授权码："))
            self._safe_call(lambda: self.link.configure(text=self._verification_url))
            self._safe_call(lambda: self.status.configure(text="等待浏览器授权…"))
            self._poll_thread()

        def err(e):
            self._safe_call(lambda: self.status.configure(
                text=f"启动失败：{e}", style="Danger.TLabel"))

        self.app.run_async(work, ok, err)

    def _poll_thread(self):
        def worker():
            def ui(fn):
                try:
                    self.after(0, fn)
                except tk.TclError:
                    pass

            try:
                tok = self.flow.wait_for_token(
                    self._info,
                    on_tick=lambda s: ui(lambda sec=s: self._safe_call(
                        lambda: self.status.configure(text=f"等待授权… 剩余 {sec}s"))),
                    cancel_flag=lambda: self._cancel,
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
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _restart(self):
        self._cancel = False
        self._safe_call(lambda: self.code_var.set(""))
        self._safe_call(lambda: self.link.configure(text=""))
        self._start()
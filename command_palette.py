# command_palette.py
import tkinter as tk
from tkinter import ttk


class CommandPalette(tk.Toplevel):
    """命令面板（Ctrl+K）：快速执行命令 / 切换标签 / 打开仓库"""

    def __init__(self, app, repo_cache):
        super().__init__(app)
        self.app = app
        self.repo_cache = repo_cache or {}
        self.title("命令面板")
        self.geometry("640x420")
        self.transient(app)
        try:
            self.iconbitmap(app.icon_path)
        except Exception:
            pass

        colors = getattr(app, "colors", {})

        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)

        self.query_var = tk.StringVar()
        entry = ttk.Entry(f, textvariable=self.query_var,
                          font=(app.ui_font, 12))
        entry.pack(fill="x", pady=(0, 8))
        entry.focus_set()
        entry.bind("<KeyRelease>", self._on_type)
        entry.bind("<Return>", lambda _e: self._execute())
        entry.bind("<Down>", lambda _e: self._move(1))
        entry.bind("<Up>", lambda _e: self._move(-1))
        entry.bind("<Escape>", lambda _e: self.destroy())

        wrap = ttk.Frame(f)
        wrap.pack(fill="both", expand=True)
        self.listbox = tk.Listbox(
            wrap, font=(app.ui_font, 11), activestyle="none",
            bg=colors.get("ENTRY_BG", "#fff"),
            fg=colors.get("FG", "#000"),
            selectbackground=colors.get("ACCENT", "#0969da"),
            selectforeground="white",
            relief="flat", bd=0, highlightthickness=0,
        )
        vs = ttk.Scrollbar(wrap, orient="vertical", command=self.listbox.yview)
        self.listbox.configure(yscrollcommand=vs.set)
        self.listbox.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.listbox.bind("<Double-1>", lambda _e: self._execute())

        self._items = []
        self._build_items()
        self._refresh()

        self.grab_set()

    # ---- 构建候选条目 ----
    def _build_items(self):
        items = []
        # 常用命令
        items.append(("🔄 刷新当前页", self.app._refresh_current))
        items.append(("🔍 搜索", self.app._focus_search))
        items.append(("➕ 新建仓库", self.app.create_repo))
        items.append(("🚀 上传项目", self.app.upload_project))
        items.append(("📝 新建 Issue", self.app.new_issue))
        items.append(("⚙️ 打开设置", self.app._open_settings))
        items.append(("🌓 切换主题", self.app.toggle_theme))
        items.append(("👤 切换账号", self.app._switch_account))
        items.append(("📥 下载队列", self.app._show_download_queue))
        items.append(("⌨️ 快捷键", self.app._show_shortcuts))
        items.append(("🚪 退出登录", self.app.logout))
        items.append(("❌ 退出程序", self.app._quit))

        # 跳转到标签页
        if hasattr(self.app, "nb"):
            for idx in range(self.app.nb.index("end")):
                tab_text = self.app.nb.tab(idx, "text")
                items.append((f"📑 切到 {tab_text}",
                              lambda i=idx: self.app.nb.select(i)))

        # 最近打开的仓库（来自 repo_cache）
        for repo in list(self.repo_cache.keys())[:50]:
            items.append((f"📦 {repo}",
                          lambda r=repo: self.app._open_repo_detail(r)))

        self._items = items

    def _refresh(self):
        q = self.query_var.get().strip().lower()
        self.listbox.delete(0, "end")
        for label, _cb in self._items:
            if not q or q in label.lower():
                self.listbox.insert("end", label)
        if self.listbox.size() > 0:
            self.listbox.selection_clear(0, "end")
            self.listbox.selection_set(0)
            self.listbox.activate(0)

    def _on_type(self, _e=None):
        self._refresh()

    def _move(self, delta):
        if self.listbox.size() == 0:
            return
        cur = self.listbox.curselection()
        idx = (cur[0] if cur else 0) + delta
        idx = max(0, min(self.listbox.size() - 1, idx))
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(idx)
        self.listbox.activate(idx)
        self.listbox.see(idx)
        return "break"

    def _execute(self):
        cur = self.listbox.curselection()
        if not cur:
            return
        label = self.listbox.get(cur[0])
        for lab, cb in self._items:
            if lab == label:
                try:
                    self.destroy()
                except tk.TclError:
                    pass
                try:
                    cb()
                except Exception:
                    pass
                return
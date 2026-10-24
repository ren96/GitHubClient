import tkinter as tk
from tkinter import ttk


class CommandPalette(tk.Toplevel):
    """Ctrl+K 命令面板：命令 + 收藏夹 + 最近访问 + 仓库名 模糊匹配"""

    def __init__(self, app, repo_cache: dict):
        super().__init__(app)
        self.app = app
        self.title("")
        self.geometry("620x460")
        self.overrideredirect(True)
        self.transient(app)

        try:
            self.grab_set()
            self._build_items(repo_cache)
            self._filtered = list(self._items)
            self._sel = 0
            self._build_ui()
            self._place_near_app(app)
        except Exception:
            try:
                self.grab_release()
            except Exception:
                pass
            try:
                self.destroy()
            except Exception:
                pass
            raise

    # ---------- 构建 ----------
    def _build_ui(self):
        colors = self.app.colors
        wrap = ttk.Frame(self, padding=8)
        wrap.pack(fill="both", expand=True)

        self.entry = ttk.Entry(wrap, font=(self.app.ui_font, 12))
        self.entry.pack(fill="x", pady=(0, 8))
        self.entry.bind("<KeyRelease>", self._on_key)
        self.entry.bind("<Down>", lambda _e: self._move(1))
        self.entry.bind("<Up>", lambda _e: self._move(-1))
        self.entry.bind("<Return>", lambda _e: self._run())
        self.entry.focus_set()

        self.listbox = tk.Listbox(
            wrap, font=(self.app.ui_font, 11), exportselection=False,
            activestyle="none",
            bg=colors.get("ENTRY_BG", "#fff"), fg=colors.get("FG", "#000"),
            selectbackground=colors.get("ACCENT", "#0969da"),
            selectforeground="white",
            relief="flat", bd=0)
        self.listbox.pack(fill="both", expand=True)
        self.listbox.bind("<<ListboxSelect>>", lambda _e: self._sync_sel())
        self.listbox.bind("<Double-Button-1>", lambda _e: self._run())

        ttk.Label(wrap, text="↑↓ 选择    Enter 执行    Esc 关闭    点击外部关闭",
                  style="Hint.TLabel").pack(anchor="w", pady=(6, 0))

        self.bind("<Escape>", lambda _e: self.destroy())
        self.bind("<Button-1>", self._on_global_click)

        self._refresh_list()

    def _place_near_app(self, app):
        try:
            self.geometry(f"+{app.winfo_x() + 200}+{app.winfo_y() + 160}")
        except Exception:
            pass
        try:
            self.lift()
            self.focus_force()
            self.entry.focus_set()
        except Exception:
            pass

    def _on_global_click(self, e):
        wx, wy = self.winfo_rootx(), self.winfo_rooty()
        ww, wh = self.winfo_width(), self.winfo_height()
        if not (wx <= e.x_root < wx + ww and wy <= e.y_root < wy + wh):
            self.destroy()

    def _build_items(self, repo_cache):
        self._items = []
        self._items += [
            ("🔄 刷新当前页", lambda: self.app._refresh_current()),
            ("➕ 新建仓库", self.app.create_repo),
            ("➕ 新建 Issue", self.app.new_issue),
            ("🔍 搜索", self.app._focus_search),
            ("🌓 切换主题", self.app.toggle_theme),
            ("⚙️ 设置", self.app._open_settings),
            ("👤 切换账号", self.app._switch_account),
            ("⌨️ 快捷键", self.app._show_shortcuts),
            ("📥 下载队列", self.app._show_download_queue),
        ]

        # 收藏夹
        favorites = getattr(self.app.cfg, "favorites", [])
        for f in favorites:
            repo = f.get("repo")
            note = f.get("note")
            lbl = f"⭐ {repo}" + (f" ({note})" if note else "")
            self._items.append((lbl, lambda r=repo: self.app._open_repo_detail(r)))

        # 最近访问
        for repo in getattr(self.app.cfg, "recent_repos", []):
            if self.app.cfg.is_favorite(repo):
                continue
            self._items.append((f"🕒 {repo}", lambda r=repo: self.app._open_repo_detail(r)))

        # 内存中的仓库缓存
        for repo in sorted(repo_cache.keys()):
            if repo in getattr(self.app.cfg, "recent_repos", []):
                continue
            self._items.append(
                (f"📁 {repo}", lambda r=repo: self.app._open_repo_detail(r)))

    # ---------- 评分 / 过滤 ----------
    def _score(self, q, s):
        q = q.lower()
        s = s.lower()
        if not q:
            return 1
        idx = s.find(q)
        if idx >= 0:
            return max(1, 100 - idx)
        i = 0
        for ch in q:
            i = s.find(ch, i)
            if i < 0:
                return 0
            i += 1
        return 10

    def _on_key(self, event):
        if event.keysym in ("Up", "Down", "Return", "Escape"):
            return
        q = self.entry.get()
        scored = [(self._score(q, label), label, fn)
                  for label, fn in self._items]
        scored = [x for x in scored if x[0] > 0]
        scored.sort(key=lambda x: -x[0])
        self._filtered = [(label, fn) for _, label, fn in scored]
        self._sel = 0
        self._refresh_list()

    def _refresh_list(self):
        self.listbox.delete(0, "end")
        for label, _fn in self._filtered[:200]:
            self.listbox.insert("end", label)
        if self._filtered:
            self.listbox.selection_set(0)

    def _move(self, delta):
        if not self._filtered:
            return
        self._sel = (self._sel + delta) % len(self._filtered)
        self.listbox.selection_clear(0, "end")
        self.listbox.selection_set(self._sel)
        self.listbox.see(self._sel)

    def _sync_sel(self):
        sel = self.listbox.curselection()
        if sel:
            self._sel = sel[0]

    def _run(self):
        if not self._filtered:
            return
        idx = self._sel
        if idx < 0 or idx >= len(self._filtered):
            idx = 0
        _label, fn = self._filtered[idx]
        self.destroy()
        try:
            fn()
        except Exception:
            import logging
            logging.exception("命令执行失败")
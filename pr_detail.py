import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from utils import _fmt_time


class PRDetailWindow(tk.Toplevel):
    def __init__(self, app, repo, number):
        super().__init__(app)
        self.app = app
        self.repo = repo
        self.number = number
        self.title(f"{repo} #{number}")
        self.geometry("1000x720")
        self.transient(app)
        try:
            self.iconbitmap(app.icon_path)
        except Exception:
            pass

        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        self.head = ttk.Label(top, text="加载中…",
                              font=(app.ui_font, 13, "bold"))
        self.head.pack(side="left")
        ttk.Button(top, text="🌐 浏览器",
                   command=lambda: webbrowser.open(
                       f"https://github.com/{repo}/pull/{number}")
                   ).pack(side="right")

        nb = ttk.Notebook(self)
        nb.pack(fill="both", expand=True, padx=10, pady=(0, 6))

        self._build_overview(nb)
        self._build_files(nb)
        self._build_diff(nb)

        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="✅ 批准", command=lambda: self._review("APPROVE")
                   ).pack(side="left")
        ttk.Button(bar, text="❌ 请求修改",
                   command=lambda: self._review("REQUEST_CHANGES")
                   ).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="💬 评论", command=lambda: self._review("COMMENT")
                   ).pack(side="left", padx=(6, 0))

        # 合并下拉菜单
        self.merge_btn = ttk.Menubutton(bar, text="🔀 合并", style="Accent.TButton")
        m_menu = tk.Menu(self.merge_btn, tearoff=False)
        m_menu.add_command(label="Create a merge commit", command=lambda: self._merge("merge"))
        m_menu.add_command(label="Squash and merge", command=lambda: self._merge("squash"))
        m_menu.add_command(label="Rebase and merge", command=lambda: self._merge("rebase"))
        self.merge_btn["menu"] = m_menu
        self.merge_btn.pack(side="left", padx=(6, 0))

        ttk.Button(bar, text="✖️ 关闭", command=self._close).pack(side="left", padx=(6, 0))

        try:
            app.register_theme_listener(self, self._apply_theme)
        except Exception:
            pass

        self.reload()

    def _apply_theme(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        c = self.app.colors
        try:
            self.txt.configure(bg=c["ENTRY_BG"], fg=c["FG"])
            self.diff_txt.configure(bg=c["ENTRY_BG"], fg=c["FG"])
            self.app._tag_tree(self.files_tree)
        except tk.TclError:
            pass

    def _build_overview(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="📋 概览")
        self.txt = tk.Text(tab, wrap="word", font=(self.app.ui_font, 10),
                           bg=self.app.colors["ENTRY_BG"], fg=self.app.colors["FG"])
        self.txt.pack(fill="both", expand=True)

    def _build_files(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="📂 文件变更")
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)
        self.files_tree = ttk.Treeview(
            body, columns=("path", "status", "add", "del"), show="headings")
        for c, h, w in [("path", "路径", 460), ("status", "状态", 100),
                        ("add", "+", 80), ("del", "-", 80)]:
            self.files_tree.heading(c, text=h)
            self.files_tree.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(body, orient="vertical", command=self.files_tree.yview)
        self.files_tree.configure(yscrollcommand=vs.set)
        self.files_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.app._tag_tree(self.files_tree)

    def _build_diff(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="🧾 Diff")
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True)
        mono = self.app.mono_font
        self.diff_txt = tk.Text(
            body, wrap="none", font=(mono, 9),
            bg=self.app.colors["ENTRY_BG"], fg=self.app.colors["FG"])
        vs = ttk.Scrollbar(body, orient="vertical", command=self.diff_txt.yview)
        hs = ttk.Scrollbar(body, orient="horizontal", command=self.diff_txt.xview)
        self.diff_txt.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
        self.diff_txt.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        hs.pack(side="bottom", fill="x")
        self.diff_txt.tag_configure("add", foreground="#1a7f37")
        self.diff_txt.tag_configure("del", foreground="#cf222e")
        self.diff_txt.tag_configure("hunk", foreground="#0969da")

    def reload(self):
        def ok(pr):
            if not self.winfo_exists():
                return
            self.pr = pr
            self.head.configure(text=f"#{self.number}  {pr['title']}")
            body = (f"作者：{pr['user']['login']}\n"
                    f"状态：{'打开' if pr['state'] == 'open' else '已关闭'}\n"
                    f"来源：{pr['head']['ref']}  →  目标：{pr['base']['ref']}\n"
                    f"创建：{_fmt_time(pr['created_at'])}\n"
                    f"更新：{_fmt_time(pr['updated_at'])}\n\n"
                    f"{pr.get('body') or '（无描述）'}")
            self.txt.configure(state="normal")
            self.txt.delete("1.0", "end")
            self.txt.insert("1.0", body)
            self.txt.configure(state="disabled")

        self.app.run_async(lambda: self.app.api.get_pull(self.repo, self.number), ok)

        def ok_files(items):
            if not self.winfo_exists():
                return
            self.files_tree.delete(*self.files_tree.get_children())
            for i, f in enumerate(items):
                self.files_tree.insert("", "end", values=(
                    f["filename"], f["status"],
                    f.get("additions", 0), f.get("deletions", 0),
                ), tags=("odd",) if i % 2 else ("even",))

        self.app.run_async(
            lambda: self.app.api.list_pull_files(self.repo, self.number), ok_files)

        def ok_diff(text):
            try:
                if not self.winfo_exists():
                    return
                self.diff_txt.configure(state="normal")
                self.diff_txt.delete("1.0", "end")
                for line in (text or "").splitlines():
                    if line.startswith("@@"):
                        self.diff_txt.insert("end", line + "\n", "hunk")
                    elif line.startswith("+") and not line.startswith("+++"):
                        self.diff_txt.insert("end", line + "\n", "add")
                    elif line.startswith("-") and not line.startswith("---"):
                        self.diff_txt.insert("end", line + "\n", "del")
                    else:
                        self.diff_txt.insert("end", line + "\n")
                self.diff_txt.configure(state="disabled")
            except tk.TclError:
                pass

        self.app.run_async(
            lambda: self.app.api.get_pull_diff(self.repo, self.number), ok_diff)

    def _review(self, event):
        from dialogs import CommentDialog
        dlg = CommentDialog(self)
        self.wait_window(dlg)
        if not dlg.result and event != "APPROVE":
            return

        def ok(_):
            if not self.winfo_exists():
                return
            self.app._status(f"已提交 review: {event}")

        self.app.run_async(
            lambda: self.app.api.create_pull_review(
                self.repo, self.number, event, dlg.result or ""), ok)

    def _merge(self, method):
        if not messagebox.askyesno("合并", f"确定使用 {method} 方式合并 PR #{self.number}？", parent=self):
            return

        def ok(res):
            if not self.winfo_exists():
                return
            self.app._status(f"合并结果：{res.get('merged')}")
            self.reload()

        self.app.run_async(
            lambda: self.app.api.merge_pull(self.repo, self.number, method=method), ok)

    def _close(self):
        if not messagebox.askyesno("关闭", f"确定关闭 PR #{self.number}？", parent=self):
            return

        def ok(_):
            if not self.winfo_exists():
                return
            self.app._status("已关闭")
            self.reload()

        self.app.run_async(
            lambda: self.app.api.close_pull(self.repo, self.number), ok)
import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from utils import _fmt_time
from dialogs import CommentDialog


class IssueDetailWindow(tk.Toplevel):
    def __init__(self, app, repo, number):
        super().__init__(app)
        self.app = app
        self.repo = repo
        self.number = number
        self.title(f"{repo} #{number}")
        self.geometry("900x680")
        self.transient(app)

        # 让子对话框（CommentDialog / IssueDialog）能继承字体 / 颜色 / 图标
        self.ui_font = app.ui_font
        self.mono_font = app.mono_font
        self.colors = app.colors
        self.icon_path = getattr(app, "icon_path", "")

        try:
            self.iconbitmap(app.icon_path)
        except Exception:
            pass

        colors = app.colors
        top = ttk.Frame(self, padding=12)
        top.pack(fill="x")
        self.head = ttk.Label(top, text="加载中…",
                              font=(app.ui_font, 13, "bold"))
        self.head.pack(side="left")
        self.state_lbl = ttk.Label(top, text="")
        self.state_lbl.pack(side="left", padx=10)

        ttk.Button(top, text="🔗 复制链接",
                   command=self._copy_link).pack(side="right", padx=(6, 0))
        ttk.Button(top, text="🌐 浏览器打开",
                   command=lambda: webbrowser.open(
                       f"https://github.com/{repo}/issues/{number}")
                   ).pack(side="right")

        pw = ttk.PanedWindow(self, orient="horizontal")
        pw.pack(fill="both", expand=True, padx=10, pady=(0, 10))

        left = ttk.Frame(pw)
        pw.add(left, weight=3)
        self.txt = tk.Text(left, wrap="word", font=(app.ui_font, 10),
                           bg=colors["ENTRY_BG"], fg=colors["FG"], padx=10, pady=10)
        vs = ttk.Scrollbar(left, orient="vertical", command=self.txt.yview)
        self.txt.configure(yscrollcommand=vs.set)
        self.txt.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")

        right = ttk.Frame(pw, padding=(10, 0))
        pw.add(right, weight=1)
        self.meta = ttk.Label(right, text="", justify="left", style="Hint.TLabel")
        self.meta.pack(anchor="w", fill="x")

        bar = ttk.Frame(self, padding=10)
        bar.pack(fill="x", side="bottom")
        ttk.Button(bar, text="💬 发表评论", style="Accent.TButton",
                   command=self._comment).pack(side="left")
        ttk.Button(bar, text="✏️ 编辑", command=self._edit).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="🗑️ 永久删除", style="Danger.TButton",
                   command=self._delete).pack(side="left", padx=(6, 0))
        ttk.Button(bar, text="🔄 刷新", command=self.reload).pack(side="right")

        self.issue = None

        # 注册主题监听（app 若不可用则忽略）
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
        self.colors = c
        try:
            self.txt.configure(bg=c["ENTRY_BG"], fg=c["FG"])
        except tk.TclError:
            pass

    def _copy_link(self):
        self.app.clipboard_clear()
        self.app.clipboard_append(f"https://github.com/{self.repo}/issues/{self.number}")
        self.app._status("已复制链接")

    def reload(self):
        def ok(issue):
            if not self.winfo_exists():
                return
            self.issue = issue
            self.head.configure(text=f"#{self.number}  {issue['title']}")
            self.state_lbl.configure(
                text="🟢 open" if issue["state"] == "open" else "🔴 closed")
            labels = ", ".join(l["name"] for l in issue.get("labels", []))
            self.meta.configure(
                text=(f"👤 {issue['user']['login']}\n"
                      f"创建：{_fmt_time(issue['created_at'])}\n"
                      f"更新：{_fmt_time(issue['updated_at'])}\n"
                      f"标签：{labels or '—'}\n"
                      f"评论：{issue['comments']}"))
            self._load_comments()

        self.app.run_async(lambda: self.app.api.get_issue(self.repo, self.number), ok)

    def _load_comments(self):
        def ok(items):
            try:
                if not self.winfo_exists():
                    return
                self.txt.configure(state="normal")
                self.txt.delete("1.0", "end")

                # 简单 Markdown Tag
                self.txt.tag_configure("b", font=(self.app.ui_font, 10, "bold"))
                self.txt.tag_configure("code", font=(self.app.mono_font, 9),
                                       background="#f0f0f0" if self.app.theme_name == "light" else "#202020")
                self.txt.tag_configure("h", font=(self.app.ui_font, 12, "bold"), spacing1=10, spacing3=5)

                self.txt.insert("end", "【正文】\n", "b")
                self._insert_md(self.issue.get("body") or "（无）")
                self.txt.insert("end", "\n" + "─" * 60 + "\n\n")

                if not items:
                    self.txt.insert("end", "（暂无评论）")
                else:
                    for c in items:
                        self.txt.insert(
                            "end",
                            f"👤 {c['user']['login']}  ·  {_fmt_time(c['created_at'])}\n", "b")
                        self._insert_md(c.get("body") or "")
                        self.txt.insert("end", "─" * 60 + "\n\n")
                self.txt.configure(state="disabled")
            except tk.TclError:
                pass

        self.app.run_async(
            lambda: self.app.api.list_comments(self.repo, self.number), ok)

    def _insert_md(self, txt):
        import re
        lines = txt.split("\n")
        in_code = False
        for line in lines:
            if line.startswith("```"):
                in_code = not in_code
                continue
            if in_code:
                self.txt.insert("end", line + "\n", "code")
            elif line.startswith("#"):
                self.txt.insert("end", line.lstrip("#").strip() + "\n", "h")
            else:
                parts = re.split(r"(\*\*.*?\*\*|`.*?`)", line)
                for p in parts:
                    if p.startswith("**") and p.endswith("**"):
                        self.txt.insert("end", p[2:-2], "b")
                    elif p.startswith("`") and p.endswith("`"):
                        self.txt.insert("end", p[1:-1], "code")
                    else:
                        self.txt.insert("end", p)
                self.txt.insert("end", "\n")

    def _comment(self):
        dlg = CommentDialog(self)
        self.wait_window(dlg)
        if not dlg.result:
            return

        def ok(_):
            if not self.winfo_exists():
                return
            self.app._status("评论已发送")
            self.reload()

        self.app.run_async(
            lambda: self.app.api.create_comment(self.repo, self.number, dlg.result), ok)

    def _edit(self):
        if not self.issue:
            return
        from dialogs import IssueDialog
        labels = self.app._labels_cache.get(self.repo, [])

        def do_show(available):
            current_labels = [l["name"] for l in self.issue.get("labels", [])]
            assignees = ",".join(a["login"] for a in (self.issue.get("assignees") or []))
            dlg = IssueDialog(
                self, f"编辑 Issue #{self.number}",
                initial_title=self.issue["title"],
                initial_body=self.issue.get("body") or "",
                initial_state=self.issue["state"], is_edit=True,
                available_labels=available, current_labels=current_labels,
                assignees=assignees)
            self.wait_window(dlg)
            if not dlg.result:
                return
            # 始终传 labels / assignees，允许清空
            fields = {
                "title": dlg.result["title"],
                "body": dlg.result["body"],
                "state": dlg.result["state"],
                "labels": dlg.result["labels"],
                "assignees": dlg.result["assignees"],
            }

            def done(_):
                if not self.winfo_exists():
                    return
                self.app._status(f"已更新 #{self.number}")
                self.reload()

            self.app.run_async(
                lambda: self.app.api.update_issue(self.repo, self.number, **fields), done)

        if labels:
            do_show(labels)
        else:
            self.app.run_async(
                lambda: self.app.api.list_labels(self.repo),
                lambda ls: do_show(ls or []))

    def _delete(self):
        if not self.issue:
            return
        if not messagebox.askyesno("⚠️ 永久删除",
                                   f"确定永久删除 Issue #{self.number}？不可恢复。",
                                   parent=self):
            return
        node_id = self.issue.get("node_id")

        def done(_):
            self.app._status(f"已删除 #{self.number}")
            self.app._reload_issues()
            try:
                self.destroy()
            except tk.TclError:
                pass

        self.app.run_async(lambda: self.app.api.delete_issue(node_id), done)
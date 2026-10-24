import logging
import os
import tkinter as tk
import webbrowser
from tkinter import ttk, messagebox, filedialog
from utils import _fmt_time, _rel_time, md_fix_relative_images, reveal_in_folder
from dialogs import EditRepoDialog, CreatePRDialog, CreateReleaseDialog

try:
    import markdown as md_lib

    MARKDOWN_OK = True
except Exception:
    md_lib = None
    MARKDOWN_OK = False

try:
    from tkhtmlview import HTMLLabel

    HTML_OK = True
except Exception:
    HTMLLabel = None
    HTML_OK = False


class RepoDetailWindow(tk.Toplevel):
    def __init__(self, app, repo_full, repo_data):
        super().__init__(app)
        self.app = app
        self.repo = repo_full
        self.data = repo_data
        self.colors = app.colors
        # 让子对话框（EditRepoDialog / CreatePRDialog / CreateReleaseDialog）能继承这些属性
        self.ui_font = app.ui_font
        self.mono_font = app.mono_font
        self.icon_path = getattr(app, "icon_path", "")
        self.title(f"{repo_full} — 详情")
        self.geometry("1000x740")
        self.transient(app)
        try:
            self.iconbitmap(app.icon_path)
        except Exception:
            pass
        self._build_header()
        self.nb = ttk.Notebook(self)
        self.nb.pack(fill="both", expand=True, padx=12, pady=12)
        self._build_overview(self.nb)
        self._build_readme(self.nb)
        self._build_files(self.nb)
        self._build_branches(self.nb)
        self._build_commits(self.nb)
        self._build_releases(self.nb)
        self._build_actions(self.nb)

    def _alive(self):
        try:
            return bool(self.winfo_exists())
        except Exception:
            return False

    def _build_header(self):
        bar = ttk.Frame(self, padding=(12, 10))
        bar.pack(fill="x")
        ttk.Label(bar, text=self.repo, font=(self.app.ui_font, 13, "bold")).pack(side="left")

        ttk.Button(bar, text="🔗 网页",
                   command=lambda: webbrowser.open(self.data["html_url"])
                   ).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="📦 发 Release", command=self._create_release).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="🔀 发 PR", command=self._create_pr).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="✏️ 编辑", command=self._edit_repo).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="🍴 Fork", command=self._fork).pack(side="right", padx=(4, 0))
        ttk.Button(bar, text="👁 Watch", command=self._watch).pack(side="right", padx=(4, 0))

        self.star_btn = ttk.Button(bar, text="⭐ Star", command=self._toggle_star)
        self.star_btn.pack(side="right", padx=(4, 0))
        ttk.Separator(self, orient="horizontal").pack(fill="x")
        self._refresh_star_state()

    def _edit_repo(self):
        dlg = EditRepoDialog(self.app, self.data)
        self.app.wait_window(dlg)
        if not dlg.result:
            return
        fields = dlg.result
        topics = fields.pop("topics", None)

        def ok(data):
            # 让本地缓存里的 topics 也反映最新值
            if topics is not None:
                data["topics"] = topics
            self.data = data
            self.app._repo_cache[self.repo] = data
            if topics is not None:
                self.app.run_async(lambda: self.app.api.set_topics(self.repo, topics),
                                   lambda _: self.app._status("仓库与 Topics 已更新"))
            else:
                self.app._status("仓库已更新")

        self.app.run_async(lambda: self.app.api.update_repo(self.repo, **fields), ok)

    def _refresh_star_state(self):
        def done(starred):
            if self._alive():
                self.star_btn.configure(text="⭐ 已 Star" if starred else "⭐ Star")

        self.app.run_async(lambda: self.app.api.is_starred(self.repo), done)

    def _toggle_star(self):
        def toggle():
            if self.app.api.is_starred(self.repo):
                self.app.api.unstar(self.repo)
                return False
            self.app.api.star(self.repo)
            return True

        self.app.run_async(toggle, lambda _: self._refresh_star_state())

    def _watch(self):
        self.app.run_async(lambda: self.app.api.watch(self.repo),
                           lambda _: self.app._status("已 Watch"))

    def _fork(self):
        def ok(res):
            if self._alive():
                messagebox.showinfo("Fork 成功", f"Fork 到 {res.get('full_name', '?')}", parent=self)

        self.app.run_async(lambda: self.app.api.fork(self.repo), ok)

    def _create_pr(self):
        def get_branches():
            return self.app.api.list_branches(self.repo)

        def show(branches):
            if not self._alive():
                return
            names = [b["name"] for b in branches]
            if not names:
                messagebox.showinfo("提示", "该仓库暂无分支", parent=self)
                return
            dlg = CreatePRDialog(self, names)
            self.app.wait_window(dlg)
            if not dlg.result:
                return

            def done(pr):
                self.app._status(f"PR 已创建：#{pr['number']}")
                webbrowser.open(pr["html_url"])

            self.app.run_async(lambda: self.app.api.create_pull(self.repo, **dlg.result), done)

        self.app.run_async(get_branches, show)

    def _create_release(self):
        dlg = CreateReleaseDialog(self)
        self.app.wait_window(dlg)
        if not dlg.result:
            return

        def done(rel):
            self.app._status(f"Release 已发布：{rel['tag_name']}")
            self._load_releases()

        self.app.run_async(lambda: self.app.api.create_release(self.repo, **dlg.result), done)

    def _build_overview(self, nb):
        tab = ttk.Frame(nb, padding=12)
        nb.add(tab, text="📋 概览")

        pw = ttk.PanedWindow(tab, orient="horizontal")
        pw.pack(fill="both", expand=True)

        left = ttk.Frame(pw)
        pw.add(left, weight=2)
        d = self.data
        info = (
            f"📦 {d['full_name']}\n"
            f"📝 {d.get('description') or '—'}\n"
            f"💻 {d.get('language') or '—'}\n"
            f"⭐ {d['stargazers_count']}    🍴 {d['forks_count']}    "
            f"❗ 未关闭 Issue：{d['open_issues_count']}\n"
            f"🌿 默认分支：{d.get('default_branch')}\n"
            f"🔒 可见性：{'私有' if d['private'] else '公开'}\n"
            f"📜 许可证：{(d.get('license') or {}).get('spdx_id') or '无'}\n"
            f"🕒 更新：{_rel_time(d['updated_at'])} ({_fmt_time(d['updated_at'])})\n"
            f"🔗 {d['html_url']}\n"
        )
        topics = d.get("topics") or []
        if topics:
            info += "🏷 Topics：" + "  ".join(f"#{t}" for t in topics) + "\n"

        txt = tk.Text(left, wrap="word", font=(self.app.ui_font, 11),
                      relief="flat", bg=self.colors["ENTRY_BG"],
                      fg=self.colors["FG"], padx=16, pady=14)
        txt.insert("1.0", info)
        txt.configure(state="disabled")
        txt.pack(fill="both", expand=True)

        right = ttk.Frame(pw, padding=(10, 0))
        pw.add(right, weight=1)
        ttk.Label(right, text="👥 Contributors", font=(self.app.ui_font, 10, "bold")).pack(anchor="w", pady=(0, 6))
        self.contrib_tree = ttk.Treeview(right, columns=("name", "commits"), show="headings", height=8)
        self.contrib_tree.heading("name", text="用户")
        self.contrib_tree.heading("commits", text="提交数")
        self.contrib_tree.column("name", width=120)
        self.contrib_tree.column("commits", width=60, anchor="e")
        self.contrib_tree.pack(fill="both", expand=True)
        self.app._tag_tree(self.contrib_tree)

        def ok_c(items):
            if not self._alive(): return
            self.contrib_tree.delete(*self.contrib_tree.get_children())
            for i, u in enumerate(items):
                self.contrib_tree.insert("", "end", values=(u["login"], u["contributions"]),
                                         tags=("odd",) if i % 2 else ("even",))

        self.app.run_async(lambda: self.app.api.list_contributors(self.repo), ok_c)

    def _build_readme(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="📖 README")
        toolbar = ttk.Frame(tab)
        toolbar.pack(fill="x")
        ttk.Button(toolbar, text="🔄 加载", command=self._load_readme).pack(side="left")

        wrap = ttk.Frame(tab)
        wrap.pack(fill="both", expand=True, pady=(8, 0))
        self._readme_wrap = wrap
        content = tk.Text(
            wrap, wrap="word", font=(self.app.ui_font, 10), relief="solid", bd=1,
            bg=self.colors["ENTRY_BG"], fg=self.colors["FG"])
        vs = ttk.Scrollbar(wrap, orient="vertical", command=content.yview)
        content.configure(yscrollcommand=vs.set)
        content.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self._readme_content = content
        self._readme_scroll = vs
        self._readme_raw = ""
        self._readme_html = None
        self._readme_html_mode = False

        if HTML_OK and MARKDOWN_OK:
            ttk.Button(tab, text="🔀 切换原始/渲染",
                       command=self._toggle_readme_view).pack(anchor="w", pady=(6, 0))
        self._load_readme()

    def _toggle_readme_view(self):
        if not (HTML_OK and MARKDOWN_OK):
            return
        self._readme_html_mode = not self._readme_html_mode
        if self._readme_html_mode:
            if self._readme_html is None:
                self._readme_html = HTMLLabel(self._readme_wrap)
            self._readme_content.pack_forget()
            self._readme_scroll.pack_forget()
            self._readme_html.pack(fill="both", expand=True)
            self._render_readme_html()
        else:
            self._readme_html.pack_forget()
            self._readme_content.pack(side="left", fill="both", expand=True)
            self._readme_scroll.pack(side="right", fill="y")

    def _render_readme_html(self):
        if not (HTML_OK and MARKDOWN_OK and self._readme_html is not None):
            return
        try:
            html = md_lib.markdown(self._readme_raw, extensions=["fenced_code", "tables"])
            ref = self.data.get("default_branch", "main")
            html = md_fix_relative_images(html, self.repo, ref)
            self._readme_html.set_html(f"<html><body>{html}</body></html>")
        except Exception:
            logging.exception("README 渲染失败")

    def _load_readme(self):
        def ok(text):
            if not self._alive():
                return
            self._readme_raw = text or "（无 README）"
            c = self._readme_content
            c.configure(state="normal")
            c.delete("1.0", "end")
            c.insert("1.0", self._readme_raw)
            c.configure(state="disabled")
            if self._readme_html_mode:
                self._render_readme_html()

        self.app.run_async(lambda: self.app.api.get_readme(self.repo), ok)

    def _build_files(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="📂 文件")
        top = ttk.Frame(tab)
        top.pack(fill="x")
        ttk.Label(top, text="分支：").pack(side="left")
        self.ref_var = tk.StringVar(value=self.data.get("default_branch", "main"))
        self.ref_combo = ttk.Combobox(top, textvariable=self.ref_var, width=30)
        self.ref_combo.pack(side="left", padx=(4, 6))
        ttk.Button(top, text="加载", command=self._load_tree).pack(side="left")
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.tree_view = ttk.Treeview(body, columns=("type", "path"), show="headings")
        self.tree_view.heading("type", text="类型")
        self.tree_view.heading("path", text="路径")
        self.tree_view.column("type", width=90, anchor="w")
        self.tree_view.column("path", width=720, anchor="w")
        vs = ttk.Scrollbar(body, orient="vertical", command=self.tree_view.yview)
        self.tree_view.configure(yscrollcommand=vs.set)
        self.tree_view.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.tree_view.bind("<Double-1>", self._open_file)
        self.app._tag_tree(self.tree_view)

        def fill_refs(branches):
            if self._alive():
                self.ref_combo["values"] = [b["name"] for b in branches]

        self.app.run_async(lambda: self.app.api.list_branches(self.repo), fill_refs)
        self._load_tree()

    def _load_tree(self):
        ref = self.ref_var.get().strip() or self.data.get("default_branch")

        def ok(tree):
            if not self._alive():
                return
            self.tree_view.delete(*self.tree_view.get_children())
            if not tree or not isinstance(tree, dict):
                return
            for i, it in enumerate(tree.get("tree", [])):
                self.tree_view.insert("", "end", iid=it["path"],
                                      values=(it["type"], it["path"]),
                                      tags=("odd",) if i % 2 else ("even",))

        self.app.run_async(lambda: self.app.api.get_tree(self.repo, ref), ok)

    def _open_file(self, _e):
        sel = self.tree_view.selection()
        if not sel: return
        path = sel[0]
        vals = self.tree_view.item(sel[0], "values")
        if not vals or vals[0] != "blob": return
        ref = self.ref_var.get().strip() or self.data.get("default_branch")

        def ok(text):
            if not self._alive(): return
            win = tk.Toplevel(self)
            win.title(path)
            win.geometry("900x680")
            try:
                win.iconbitmap(self.app.icon_path)
            except Exception:
                pass
            mono = self.app.mono_font
            txt = tk.Text(win, wrap="none", font=(mono, 10),
                          bg=self.colors["ENTRY_BG"], fg=self.colors["FG"])
            vs = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
            hs = ttk.Scrollbar(win, orient="horizontal", command=txt.xview)
            txt.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
            txt.pack(side="left", fill="both", expand=True)
            vs.pack(side="right", fill="y")
            hs.pack(side="bottom", fill="x")
            txt.insert("1.0", text)
            txt.configure(state="disabled")

        self.app.run_async(lambda: self.app.api.get_file_content(self.repo, path, ref), ok)

    def _build_branches(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="🌿 分支")
        ttk.Button(tab, text="🔄 刷新", command=self._load_branches).pack(anchor="w")
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.branches_tree = ttk.Treeview(body, columns=("name", "sha"), show="headings")
        self.branches_tree.heading("name", text="分支")
        self.branches_tree.heading("sha", text="SHA")
        self.branches_tree.column("name", width=400)
        self.branches_tree.column("sha", width=260)
        vs = ttk.Scrollbar(body, orient="vertical", command=self.branches_tree.yview)
        self.branches_tree.configure(yscrollcommand=vs.set)
        self.branches_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self._load_branches()

    def _load_branches(self):
        def ok(items):
            if not self._alive(): return
            self.branches_tree.delete(*self.branches_tree.get_children())
            for b in items:
                self.branches_tree.insert("", "end", values=(b["name"], b["commit"]["sha"][:12]))

        self.app.run_async(lambda: self.app.api.list_branches(self.repo), ok)

    def _build_commits(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="🕒 提交")
        ttk.Button(tab, text="🔄 刷新", command=self._load_commits).pack(anchor="w")
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.commits_tree = ttk.Treeview(body, columns=("sha", "author", "date", "msg"), show="headings")
        for c, h, w in [("sha", "SHA", 120), ("author", "作者", 180), ("date", "时间", 170), ("msg", "说明", 520)]:
            self.commits_tree.heading(c, text=h)
            self.commits_tree.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(body, orient="vertical", command=self.commits_tree.yview)
        self.commits_tree.configure(yscrollcommand=vs.set)
        self.commits_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.commits_tree.bind("<Double-1>", self._open_commit_diff)
        self._load_commits()

    def _load_commits(self):
        def ok(items):
            if not self._alive(): return
            self.commits_tree.delete(*self.commits_tree.get_children())
            for c in items:
                first = (c["commit"]["message"] or "").split("\n")[0]
                self.commits_tree.insert("", "end", iid=c["sha"], values=(
                    c["sha"][:10], c["commit"]["author"]["name"],
                    _fmt_time(c["commit"]["author"]["date"]), first,
                ))

        self.app.run_async(lambda: self.app.api.list_commits(self.repo), ok)

    def _open_commit_diff(self, _e):
        sel = self.commits_tree.selection()
        if not sel: return
        sha = sel[0]

        def ok(text):
            if not self._alive(): return
            win = tk.Toplevel(self)
            win.title(f"Diff: {sha[:7]}")
            win.geometry("900x680")
            mono = self.app.mono_font
            txt = tk.Text(win, wrap="none", font=(mono, 9),
                          bg=self.colors["ENTRY_BG"], fg=self.colors["FG"])
            vs = ttk.Scrollbar(win, orient="vertical", command=txt.yview)
            hs = ttk.Scrollbar(win, orient="horizontal", command=txt.xview)
            txt.configure(yscrollcommand=vs.set, xscrollcommand=hs.set)
            txt.pack(side="left", fill="both", expand=True)
            vs.pack(side="right", fill="y")
            hs.pack(side="bottom", fill="x")
            txt.tag_configure("add", foreground="#1a7f37")
            txt.tag_configure("del", foreground="#cf222e")
            txt.tag_configure("hunk", foreground="#0969da")
            for line in (text or "").splitlines():
                if line.startswith("@@"):
                    txt.insert("end", line + "\n", "hunk")
                elif line.startswith("+") and not line.startswith("+++"):
                    txt.insert("end", line + "\n", "add")
                elif line.startswith("-") and not line.startswith("---"):
                    txt.insert("end", line + "\n", "del")
                else:
                    txt.insert("end", line + "\n")
            txt.configure(state="disabled")

        self.app.run_async(lambda: self.app.api.get_commit_diff(self.repo, sha), ok)

    def _build_releases(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="📦 Release")
        ttk.Button(tab, text="🔄 刷新", command=self._load_releases).pack(anchor="w")
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.rel_tree = ttk.Treeview(body, columns=("tag", "name", "at"), show="headings")
        for c, h, w in [("tag", "标签", 170), ("name", "名称", 440), ("at", "发布", 190)]:
            self.rel_tree.heading(c, text=h)
            self.rel_tree.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(body, orient="vertical", command=self.rel_tree.yview)
        self.rel_tree.configure(yscrollcommand=vs.set)
        self.rel_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.rel_tree.bind("<Double-1>", self._open_release)
        self._releases = {}
        self._load_releases()

    def _load_releases(self):
        def ok(items):
            if not self._alive(): return
            self._releases.clear()
            self.rel_tree.delete(*self.rel_tree.get_children())
            for r in items:
                self._releases[r["tag_name"]] = r
                self.rel_tree.insert("", "end", iid=r["tag_name"], values=(
                    r["tag_name"], r["name"] or "—", _fmt_time(r.get("published_at") or "")))

        self.app.run_async(lambda: self.app.api.list_releases(self.repo), ok)

    def _open_release(self, _e):
        sel = self.rel_tree.selection()
        if not sel: return
        r = self._releases.get(sel[0])
        if not r: return
        win = tk.Toplevel(self)
        win.title(f"Release {r['tag_name']}")
        win.geometry("700x500")
        try:
            win.iconbitmap(self.app.icon_path)
        except Exception:
            pass
        bar = ttk.Frame(win, padding=10)
        bar.pack(fill="x", side="bottom")
        assets = r.get("assets") or []
        if assets:
            ttk.Button(bar, text="⬇ 下载全部", style="Accent.TButton",
                       command=lambda: self._download_all(r)).pack(side="left", padx=(0, 10))
            for a in assets:
                label = a['name'] if len(a['name']) <= 20 else a['name'][:18] + "…"
                ttk.Button(bar, text=f"⬇ {label}",
                           command=lambda ast=a: self._download_one(ast)).pack(side="left", padx=2)
        txt = tk.Text(win, wrap="word", font=(self.app.ui_font, 10),
                      bg=self.colors["ENTRY_BG"], fg=self.colors["FG"])
        txt.pack(fill="both", expand=True, padx=10, pady=10)
        txt.insert("1.0", r.get("body") or "（无说明）")
        txt.configure(state="disabled")

    def _download_one(self, asset):
        dest = filedialog.askdirectory(title="选择保存目录", initialdir=self.app._initial_dir(), parent=self)
        if not dest: return
        self.app._enqueue_download(self.repo, asset, dest)
        self.app._status(f"已加入下载队列：{asset['name']}")

    def _download_all(self, release):
        assets = release.get("assets") or []
        if not assets: return
        dest = filedialog.askdirectory(title="选择保存目录", initialdir=self.app._initial_dir(), parent=self)
        if not dest: return
        for a in assets:
            self.app._enqueue_download(self.repo, a, dest)
        self.app._status(f"已加入下载队列：{len(assets)} 个文件")

    def _build_actions(self, nb):
        tab = ttk.Frame(nb, padding=10)
        nb.add(tab, text="⚙️ Actions")
        ttk.Button(tab, text="🔄 刷新", command=self._load_actions).pack(anchor="w")
        body = ttk.Frame(tab)
        body.pack(fill="both", expand=True, pady=(8, 0))
        self.act_tree = ttk.Treeview(body, columns=("name", "status", "at"), show="headings")
        for c, h, w in [("name", "工作流", 380), ("status", "状态", 160), ("at", "时间", 220)]:
            self.act_tree.heading(c, text=h)
            self.act_tree.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(body, orient="vertical", command=self.act_tree.yview)
        self.act_tree.configure(yscrollcommand=vs.set)
        self.act_tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self.act_tree.bind("<Double-1>", self._download_action_log)
        self._load_actions()

    def _load_actions(self):
        def ok(data):
            if not self._alive(): return
            runs = (data or {}).get("workflow_runs", [])
            self.act_tree.delete(*self.act_tree.get_children())
            for r in runs:
                st = r.get("conclusion") or r.get("status") or "?"
                marker = {"success": "✅", "failure": "❌", "in_progress": "🟡", "queued": "⏳"}.get(st, "•")
                self.act_tree.insert("", "end", iid=str(r["id"]), values=(
                    r.get("name") or r.get("display_title") or "—",
                    f"{marker} {st}",
                    _fmt_time(r.get("updated_at") or "")))

        self.app.run_async(lambda: self.app.api.list_action_runs(self.repo), ok)

    def _download_action_log(self, _e):
        sel = self.act_tree.selection()
        if not sel: return
        run_id = sel[0]
        dest = filedialog.askdirectory(title="选择日志保存目录", initialdir=self.app._initial_dir(), parent=self)
        if not dest: return

        self.app._status("正在下载日志...")

        def ok(path):
            self.app._status("日志下载完成")
            reveal_in_folder(path)

        self.app.run_async(lambda: self.app.api.download_action_logs(self.repo, run_id, dest), ok)
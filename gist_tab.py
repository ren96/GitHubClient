import tkinter as tk
from tkinter import ttk, messagebox
import webbrowser
from utils import _rel_time


class GistTab(ttk.Frame):
    def __init__(self, parent, app):
        super().__init__(parent, padding=14)
        self.app = app
        self._gists = {}

        sbar = ttk.Frame(self)
        sbar.pack(fill="x", pady=(0, 8))
        ttk.Button(sbar, text="🔄 刷新", command=self.load).pack(side="left")
        ttk.Button(sbar, text="➕ 新建 Gist", style="Accent.TButton",
                   command=self.create).pack(side="left", padx=(6, 0))
        ttk.Button(sbar, text="📋 从剪贴板新建",
                   command=self.create_from_clipboard).pack(side="left", padx=(6, 0))
        ttk.Button(sbar, text="🗑 删除", command=self.delete).pack(side="right")
        ttk.Button(sbar, text="✏️ 编辑", command=self.edit).pack(side="right", padx=(0, 6))

        # 增加传入 name 参数 "gist_tree"
        self.tree = app._make_tree(
            self, "gist_tree",
            cols=("desc", "files", "public", "updated"),
            heads=("描述", "文件数", "公开", "更新"),
            widths=(500, 90, 90, 180))
        self.tree.bind("<Double-1>", self._open_gist)
        self.tree.bind("<Button-3>", self._context_menu)

    def load(self):
        def ok(items):
            self._gists.clear()
            self.tree.delete(*self.tree.get_children())
            for i, g in enumerate(items):
                self._gists[g["id"]] = g
                self.tree.insert("", "end", iid=g["id"], values=(
                    (g.get("description") or "（无描述）")[:80],
                    len(g.get("files") or {}),
                    "🌐 公开" if g.get("public") else "🔒 私密",
                    _rel_time(g["updated_at"]),
                ), tags=("odd",) if i % 2 else ("even",))
            self.app._status(f"已加载 {len(items)} 个 Gist")

        self.app.run_async(lambda: self.app.api.list_gists(), ok)

    def _open_gist(self, _e):
        sel = self.tree.selection()
        if not sel:
            return
        g = self._gists.get(sel[0])
        if not g:
            return
        webbrowser.open(g["html_url"])

    def _context_menu(self, e):
        row = self.tree.identify_row(e.y)
        if not row:
            return
        self.tree.selection_set(row)
        g = self._gists.get(row)
        if not g:
            return
        menu = tk.Menu(self, tearoff=0)
        menu.add_command(label="在浏览器打开", command=lambda: webbrowser.open(g["html_url"]))

        def copy_raw():
            files = g.get("files") or {}
            if not files: return
            first = list(files.values())[0]
            raw_url = first.get("raw_url", "")
            if raw_url:
                self.app.clipboard_clear()
                self.app.clipboard_append(raw_url)
                self.app._status("已复制 Raw 链接")

        menu.add_command(label="复制 Raw 链接", command=copy_raw)
        menu.add_separator()
        menu.add_command(label="编辑", command=self.edit)
        menu.add_command(label="删除", command=self.delete)
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def create(self):
        dlg = GistDialog(self.app)
        self.app.wait_window(dlg)
        if not dlg.result:
            return

        def ok(g):
            self.app._status(f"Gist 已创建：{g['html_url']}")
            self.load()

        self.app.run_async(
            lambda: self.app.api.create_gist(
                dlg.result["description"], dlg.result["files"], dlg.result["public"]),
            ok)

    def edit(self):
        sel = self.tree.selection()
        if not sel: return
        gid = sel[0]
        g = self._gists.get(gid)
        if not g: return

        dlg = GistDialog(self.app, gist_data=g)
        self.app.wait_window(dlg)
        if not dlg.result:
            return

        def ok(_g):
            self.app._status(f"Gist 已更新")
            self.load()

        self.app.run_async(
            lambda: self.app.api.update_gist(
                gid, dlg.result["files"], dlg.result["description"]),
            ok)

    def create_from_clipboard(self):
        try:
            text = self.app.clipboard_get()
        except Exception:
            messagebox.showinfo("提示", "剪贴板为空")
            return
        if not text.strip():
            messagebox.showinfo("提示", "剪贴板为空")
            return

        def ok(g):
            self.app._status(f"已创建 Gist：{g['html_url']}")
            self.load()

        self.app.run_async(
            lambda: self.app.api.create_gist(
                "从剪贴板创建", {"snippet.txt": {"content": text}}, public=False),
            ok)

    def delete(self):
        sel = self.tree.selection()
        if not sel:
            return
        gid = sel[0]
        if not messagebox.askyesno("确认", "确定删除该 Gist？"):
            return

        def ok(_):
            self.app._status("Gist 已删除")
            self.load()

        self.app.run_async(lambda: self.app.api.delete_gist(gid), ok)


class GistDialog(tk.Toplevel):
    def __init__(self, parent, gist_data=None):
        super().__init__(parent)
        self.title("编辑 Gist" if gist_data else "新建 Gist")
        self.result = None
        self.transient(parent)
        self.grab_set()
        self.geometry("680x520")
        colors = parent.colors
        try:
            self.iconbitmap(parent.icon_path)
        except Exception:
            pass

        f = ttk.Frame(self, padding=14)
        f.pack(fill="both", expand=True)
        ttk.Label(f, text="描述").pack(anchor="w")
        self.desc_var = tk.StringVar(value=(gist_data.get("description") or "") if gist_data else "")
        ttk.Entry(f, textvariable=self.desc_var).pack(fill="x", pady=(2, 8))

        self.name_var = tk.StringVar(value="snippet.txt")
        if not gist_data:
            ttk.Label(f, text="文件名").pack(anchor="w")
            ttk.Entry(f, textvariable=self.name_var).pack(fill="x", pady=(2, 8))
        else:
            files = gist_data.get("files") or {}
            if files:
                self.name_var.set(list(files.keys())[0])

        ttk.Label(f, text="内容").pack(anchor="w")
        self.text = tk.Text(f, font=(parent.mono_font, 10), undo=True,
                            bg=colors["ENTRY_BG"], fg=colors["FG"])
        self.text.pack(fill="both", expand=True, pady=(2, 8))

        if gist_data:
            files = gist_data.get("files") or {}
            if files:
                first = list(files.values())[0]
                self.text.insert("1.0", first.get("content") or "")

        self.public_var = tk.BooleanVar(value=bool(gist_data.get("public")) if gist_data else False)
        ttk.Checkbutton(f, text="公开", variable=self.public_var).pack(anchor="w")

        bar = ttk.Frame(f)
        bar.pack(fill="x", pady=(10, 0))
        ttk.Button(bar, text="取消", command=self.destroy).pack(side="right")
        ttk.Button(bar, text="保存", style="Accent.TButton",
                   command=self._save).pack(side="right", padx=(0, 8))

    def _save(self):
        name = self.name_var.get().strip()
        if not name:
            messagebox.showwarning("提示", "文件名不能为空", parent=self)
            return
        content = self.text.get("1.0", "end-1c")
        if not content.strip():
            messagebox.showwarning("提示", "内容不能为空", parent=self)
            return
        self.result = {
            "description": self.desc_var.get().strip(),
            "files": {name: {"content": content}},
            "public": self.public_var.get(),
        }
        self.destroy()
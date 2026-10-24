import os
import sys
import logging
import threading
import re
import tkinter as tk
import tkinter.font as tkfont
from tkinter import ttk, messagebox, simpledialog, filedialog
import webbrowser
from typing import Optional

from utils import (
    _fmt_time, _rel_time, _fmt_bytes, RateLimitError, get_base_dir, detect_system_theme,
    open_path_in_os, open_in_vscode, open_terminal, notify_desktop
)
from config import ConfigStore, Cache, KEYRING_OK
from api import GitHubAPI
from dialogs import (IssueDialog, CreateRepoDialog, CommentDialog,
                     SettingsDialog, OAuthDialog, UploadProjectDialog)
from repo_detail import RepoDetailWindow
from issue_detail import IssueDetailWindow
from pr_detail import PRDetailWindow
from gist_tab import GistTab
from command_palette import CommandPalette
from download_queue import DownloadQueueWindow, DownloadTask

REPO_RE = re.compile(r"^[\w.-]+/[\w.-]+$")

_DEFAULT_GITIGNORE = """\
# System
.DS_Store
Thumbs.db
desktop.ini

# Python
__pycache__/
*.py[cod]
*.egg-info/
.venv/
venv/
env/
.pytest_cache/
.mypy_cache/
.coverage
htmlcov/

# Node
node_modules/
npm-debug.log*
yarn-error.log*

# IDE
.idea/
.vscode/

# Env
.env
.env.local

# Build
dist/
build/
*.log
"""


class GitHubApp(tk.Tk):
    def __init__(self):
        super().__init__()
        self.title("GitHub 客户端")
        self.minsize(1000, 700)

        self._setup_icon()
        self._setup_exception_handler()

        self.api: Optional[GitHubAPI] = None
        self.current_user: Optional[str] = None
        self.current_repo = ""
        self._scopes = ""
        self.repo_var = tk.StringVar(value="（未选择）")
        self.issue_state = tk.StringVar(value="open")
        self.pull_state = tk.StringVar(value="open")
        self.repo_sort = tk.StringVar(value="updated")
        self.repo_visibility = tk.StringVar(value="all")
        self.search_mode = tk.StringVar(value="repos")
        self.star_page = 0

        self.issue_nodes: dict[int, str] = {}
        self._repo_cache: dict[str, dict] = {}
        self._labels_cache: dict[str, list] = {}
        self._status_after = None
        self._repo_page = 0
        self._issue_page = 0
        self._pull_page = 0
        self._debounce_after = None
        self._search_after = None

        # 请求代次
        self._gen_repos = 0
        self._gen_issues = 0
        self._gen_pulls = 0
        self._gen_notifs = 0
        self._gen_star = 0

        # 通知
        self._last_unread = 0
        self._poll_after = None
        self._dl_window: Optional[DownloadQueueWindow] = None

        self._shortcuts_win = None
        self._cmd_palette = None

        self.cfg = ConfigStore()
        self.cache = Cache()

        # 几何恢复与启动最大化优化
        try:
            if self.cfg.geometry == "zoomed":
                self.state("zoomed")
            elif self.cfg.geometry:
                self.geometry(self.cfg.geometry)
            else:
                self.state("zoomed")
        except Exception:
            try:
                self.state("zoomed")
            except Exception:
                self.geometry("1240x820")

        self._setup_theme(self._resolve_theme(self.cfg.theme))
        self._build_login()
        self._build_main()
        self._bind_shortcuts()

        if self.cfg.last_tab:
            try:
                self.nb.select(self.cfg.last_tab)
            except Exception:
                pass

    def _setup_icon(self):
        base_dir = get_base_dir()
        self.icon_path = os.path.join(base_dir, "tubiao", "tubiao.ico")
        if not os.path.exists(self.icon_path):
            logging.warning(f"找不到图标文件: {self.icon_path}")
            return

        # ① 尝试用 iconphoto 设置高 DPI 图标
        try:
            from PIL import Image, ImageTk
            ico = Image.open(self.icon_path)
            photos = []
            resample = getattr(Image, "Resampling", Image)
            if getattr(ico, "ico", None) is not None:
                sizes = ico.ico.sizes()
                for s in (16, 32, 24, 48, 64, 128, 256):
                    nearest = min(sizes, key=lambda x: abs(x[0] - s) + abs(x[1] - s))
                    im = ico.ico.getimage(nearest).convert("RGBA")
                    if im.size != (s, s):
                        im = im.resize((s, s), resample.LANCZOS)
                    photos.append(ImageTk.PhotoImage(im))
            else:
                im = ico.convert("RGBA")
                for s in (16, 32, 48, 64, 128, 256):
                    photos.append(ImageTk.PhotoImage(im.resize((s, s), resample.LANCZOS)))

            self._icon_photos = photos
            self.iconphoto(True, *photos)
        except Exception as e:
            logging.warning(f"iconphoto 加载失败: {e}")

        # ② Windows 必须显式设置主窗口图标，否则依然会显示 Tk 默认图标
        if sys.platform == "win32":
            try:
                self.iconbitmap(self.icon_path)              # 修复：显式给主窗口设置
                self.iconbitmap(default=self.icon_path)      # 让 Toplevel 子窗口继承
            except Exception as e:
                logging.warning(f"iconbitmap 加载失败: {e}")

    def _setup_exception_handler(self):
        def handler(exc, val, tb):
            logging.exception("Tk 回调异常", exc_info=(exc, val, tb))
            try:
                messagebox.showerror("错误", str(val))
            except Exception:
                pass
        self.report_callback_exception = handler

    def _resolve_theme(self, name: str) -> str:
        if name == "auto":
            return detect_system_theme()
        return name if name in ("light", "dark") else "light"

    def _setup_theme(self, theme_name):
        if not hasattr(self, "_font_families"):
            self._font_families = set(tkfont.families(self))
        families = self._font_families
        self.ui_font = next((f for f in [
            "Microsoft YaHei UI", "PingFang SC", "Noto Sans CJK SC",
            "WenQuanYi Micro Hei", "Helvetica", "Arial"] if f in families), "TkDefaultFont")
        self.mono_font = next((f for f in [
            "Consolas", "Menlo", "DejaVu Sans Mono", "Courier New"] if f in families), "TkFixedFont")
        self.theme_name = theme_name
        self.font_size = getattr(self.cfg, "font_size", 10)

        if theme_name == "dark":
            BG, FG, ENTRY_BG, HINT = "#0d1117", "#e6edf3", "#161b22", "#8b949e"
            ACCENT, DANGER = "#2f81f7", "#f85149"
            TREE_BG, TREE_ODD, TREE_FG = "#0d1117", "#161b22", "#e6edf3"
            CARD_BORDER, HEADER_BG = "#30363d", "#161b22"
        else:
            BG, FG, ENTRY_BG, HINT = "#f6f8fa", "#1f2328", "#ffffff", "#57606a"
            ACCENT, DANGER = "#0969da", "#cf222e"
            TREE_BG, TREE_ODD, TREE_FG = "#ffffff", "#f6f8fa", "#1f2328"
            CARD_BORDER, HEADER_BG = "#d0d7de", "#ffffff"

        self.colors = {
            "BG": BG, "FG": FG, "ACCENT": ACCENT, "DANGER": DANGER,
            "HINT": HINT, "TREE_BG": TREE_BG, "TREE_ODD": TREE_ODD,
            "TREE_FG": TREE_FG, "ENTRY_BG": ENTRY_BG,
            "CARD_BORDER": CARD_BORDER, "HEADER_BG": HEADER_BG,
        }
        self.configure(bg=BG)

        style = ttk.Style(self)
        if "clam" in style.theme_names(): style.theme_use("clam")
        style.configure(".", background=BG, foreground=FG, font=(self.ui_font, self.font_size))
        style.configure("TFrame", background=BG)
        style.configure("Header.TFrame", background=HEADER_BG)
        style.configure("Status.TFrame", background=BG)
        style.configure("Card.TFrame", background=ENTRY_BG, relief="solid", borderwidth=1)
        style.configure("TLabel", background=BG, foreground=FG, font=(self.ui_font, self.font_size))
        style.configure("Header.TLabel", background=HEADER_BG, foreground=FG)
        style.configure("Hint.TLabel", foreground=HINT)
        style.configure("Danger.TLabel", foreground=DANGER)
        style.configure("Success.TLabel", foreground="#1a7f37")
        style.configure("Title.TLabel", font=(self.ui_font, self.font_size + 14, "bold"))
        style.configure("Subtitle.TLabel", font=(self.ui_font, self.font_size), foreground=HINT)
        style.configure("TButton", padding=(12, 6), font=(self.ui_font, self.font_size))
        style.configure("Accent.TButton", foreground="white", background=ACCENT)
        style.map("Accent.TButton", background=[("active", ACCENT), ("disabled", HINT)])
        style.configure("Danger.TButton", foreground="white", background=DANGER)
        style.map("Danger.TButton", background=[("active", DANGER), ("disabled", HINT)])
        style.configure("Treeview", rowheight=int(self.font_size * 2.8), background=TREE_BG,
                        fieldbackground=TREE_BG, foreground=TREE_FG, borderwidth=0, font=(self.ui_font, self.font_size))
        style.configure("Treeview.Heading", font=(self.ui_font, self.font_size - 1, "bold"), padding=(8, 6))
        style.map("Treeview", background=[("selected", ACCENT)], foreground=[("selected", "white")])
        style.configure("TNotebook", background=BG, borderwidth=0, tabmargins=(2, 4, 2, 0))
        style.configure("TNotebook.Tab", padding=(18, 9), font=(self.ui_font, self.font_size), background=BG,
                        borderwidth=0)
        style.map("TNotebook.Tab", background=[("selected", ENTRY_BG), ("active", BG)],
                  foreground=[("selected", ACCENT), ("active", FG)])
        style.configure("TEntry", padding=6, font=(self.ui_font, self.font_size))
        style.configure("TCombobox", padding=5, font=(self.ui_font, self.font_size))
        style.configure("TProgressbar", thickness=8)
        style.configure("TCheckbutton", background=BG, font=(self.ui_font, self.font_size))
        style.configure("TRadiobutton", background=BG, font=(self.ui_font, self.font_size))
        style.configure("TSeparator", background=CARD_BORDER)

        self._refresh_login_colors()

    def _refresh_login_colors(self):
        try:
            border = getattr(self, "_login_border", None)
            if border is not None and border.winfo_exists():
                border.configure(bg=self.colors["CARD_BORDER"])
            accent = getattr(self, "_login_accent", None)
            if accent is not None and accent.winfo_exists():
                accent.configure(bg=self.colors["ACCENT"])
        except Exception:
            pass

    def _iter_trees(self, widget):
        for w in widget.winfo_children():
            if isinstance(w, ttk.Treeview): yield w
            yield from self._iter_trees(w)

    @staticmethod
    def _tag_tree(tree):
        try:
            top = tree.winfo_toplevel()
            app = getattr(top, "app", None)
            colors = getattr(app, "colors", None) or getattr(top, "colors", None)
            if not colors: return
            tree.tag_configure("odd", background=colors["TREE_ODD"])
            tree.tag_configure("even", background=colors["TREE_BG"])
            tree.tag_configure("closed", foreground="#8c959f")
            tree.tag_configure("error", foreground=colors["DANGER"])
            tree.tag_configure("loading", foreground=colors["HINT"])
        except Exception:
            pass

    def toggle_theme(self):
        modes = ["auto", "light", "dark"]
        cur = self.cfg.theme if self.cfg.theme in modes else "auto"
        nxt = modes[(modes.index(cur) + 1) % 3]
        self.cfg.theme = nxt
        self.cfg.save()
        self._setup_theme(self._resolve_theme(nxt))
        for tree in self._iter_trees(self):
            self._tag_tree(tree)
        if hasattr(self, "theme_btn"):
            self.theme_btn.configure(text={"auto": "🌓", "light": "🌙", "dark": "☀️"}[nxt])
        self._status(f"主题：{nxt}")

    def run_async(self, fn, on_ok, on_err=None):
        def worker():
            try:
                result = fn()
            except Exception as e:
                logging.exception("异步任务出错")
                self.after(0, lambda err=e: (on_err or self._err)(err))
            else:
                self.after(0, lambda res=result: on_ok(res))

        threading.Thread(target=worker, daemon=True).start()

    def _busy_do(self, buttons, work, on_ok, on_err=None):
        for b in buttons:
            try:
                b.configure(state="disabled")
            except Exception:
                pass

        def done(res):
            for b in buttons:
                try:
                    b.configure(state="normal")
                except Exception:
                    pass
            on_ok(res)

        def fail(e):
            for b in buttons:
                try:
                    b.configure(state="normal")
                except Exception:
                    pass
            (on_err or self._err)(e)

        self.run_async(work, done, fail)

    def _err(self, e):
        msg = str(e)
        if isinstance(e, RateLimitError): msg += "\n\n请稍后再试，或换一个网络环境。"
        messagebox.showerror("出错了", msg)

    @staticmethod
    def _selected(tree):
        sel = tree.selection()
        return sel[0] if sel else None

    @staticmethod
    def _extract_repo(iid):
        return iid.split(":", 1)[0] if ":" in iid else iid

    def _status(self, msg, timeout=4000):
        if not hasattr(self, "status_label"): return
        try:
            self.status_label.configure(text=msg)
        except Exception:
            return
        if self._status_after:
            try:
                self.after_cancel(self._status_after)
            except Exception:
                pass
        self._status_after = self.after(timeout, lambda: self.status_label.configure(text="就绪"))

    def _make_tree(self, parent, name, cols, heads, widths, height=16):
        saved_w = getattr(self.cfg, "col_widths", {}).get(name, widths)
        if len(saved_w) != len(widths): saved_w = widths

        wrap = ttk.Frame(parent)
        wrap.pack(fill="both", expand=True)
        tree = ttk.Treeview(wrap, columns=cols, show="headings", height=height)

        def sort_tree(col):
            items = [(tree.set(k, col), k) for k in tree.get_children('')]

            def _key(v):
                s = str(v[0]).lower()
                try:
                    return (0, float(re.sub(r'[^\d.-]', '', s) or 0))
                except:
                    return (1, s)

            desc = getattr(tree, "_sort_desc", {}).get(col, False)
            items.sort(key=_key, reverse=desc)
            if not hasattr(tree, "_sort_desc"): tree._sort_desc = {}
            tree._sort_desc[col] = not desc

            for i, (_, k) in enumerate(items):
                tree.move(k, '', i)
                tags = [t for t in tree.item(k, "tags") if t not in ("odd", "even")]
                tags.append("odd" if i % 2 else "even")
                tree.item(k, tags=tags)

        for i, (c, h, w) in enumerate(zip(cols, heads, saved_w)):
            tree.heading(c, text=h, command=lambda cc=c: sort_tree(cc))
            tree.column(c, width=w, anchor="w", stretch=(i == len(cols) - 1))

        def on_release(e):
            new_w = [tree.column(c, "width") for c in cols]
            if not hasattr(self.cfg, "col_widths"): self.cfg.col_widths = {}
            self.cfg.col_widths[name] = new_w
            self.cfg.save()

        tree.bind("<ButtonRelease-1>", on_release, add="+")

        vs = ttk.Scrollbar(wrap, orient="vertical", command=tree.yview)
        tree.configure(yscrollcommand=vs.set)
        tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        self._tag_tree(tree)
        return tree

    def _tree_set_state(self, tree, kind, msg="", retry=None):
        for iid in tree.get_children():
            if str(iid).startswith("__state__"): tree.delete(iid)
        icon = {"loading": "⏳ ", "empty": "📭 ", "error": "❌ "}.get(kind, "")
        cols = tree["columns"]
        vals = [icon + msg] + [""] * (len(cols) - 1)
        tree.insert("", "end", iid="__state__", values=vals, tags=(kind,))
        if kind == "error" and retry:
            tree.bind("<Double-1>", lambda _e: retry(), add="+")

    def _bind_shortcuts(self):
        self.bind_all("<Control-f>", lambda _e: self._focus_search())
        self.bind_all("<Control-k>", lambda _e: self._command_palette())
        self.bind_all("<Control-n>", lambda _e: self.new_issue())
        self.bind_all("<Control-s>", lambda _e: self.toggle_theme())
        self.bind_all("<Control-p>", lambda _e: self._open_settings())
        self.bind_all("<Control-q>", lambda _e: self._quit())
        self.bind_all("<F5>", lambda _e: self._refresh_current())
        self.bind_all("<F1>", lambda _e: self._show_shortcuts())
        self.bind_all("<Delete>", self._delete_selected)

    def _focus_in_app(self) -> bool:
        try:
            w = self.focus_displayof()
            if w is None: return True
            return w.winfo_toplevel() is self
        except Exception:
            return True

    def _show_shortcuts(self):
        if not self._focus_in_app(): return
        win = getattr(self, "_shortcuts_win", None)
        if win is not None:
            try:
                if win.winfo_exists():
                    win.deiconify()
                    win.lift()
                    win.focus_set()
                    return
            except tk.TclError:
                pass
        win = tk.Toplevel(self)
        self._shortcuts_win = win
        win.title("快捷键")
        win.geometry("460x460")
        win.transient(self)
        try:
            win.iconbitmap(self.icon_path)
        except Exception:
            pass
        txt = tk.Text(win, wrap="word", font=(self.ui_font, 11),
                      bg=self.colors["ENTRY_BG"], fg=self.colors["FG"], padx=16, pady=14)
        txt.pack(fill="both", expand=True)
        txt.insert("1.0",
                   "Ctrl+F    搜索\nCtrl+K    命令面板\nCtrl+N    新建 Issue\n"
                   "Ctrl+S    切换主题\nCtrl+P    设置\nCtrl+Q    退出\n"
                   "F5        刷新当前页\nF1        显示本面板\n"
                   "Delete    删除选中 Issue\n双击仓库  查看详情\n")
        txt.configure(state="disabled")
        ttk.Button(win, text="关闭", command=win.destroy).pack(fill="x")
        win.bind("<Escape>", lambda _e: win.destroy())
        win.lift()
        win.focus_set()

    def _command_palette(self):
        if not self._focus_in_app(): return
        existing = getattr(self, "_cmd_palette", None)
        if existing is not None:
            try:
                if existing.winfo_exists():
                    existing.lift()
                    existing.focus_force()
                    return
            except tk.TclError:
                pass
        try:
            self._cmd_palette = CommandPalette(self, self._repo_cache)
        except Exception:
            logging.exception("命令面板失败")
            self._cmd_palette = None

    def _quit(self):
        try:
            self.deiconify(); self.lift()
        except Exception:
            pass
        if messagebox.askyesno("退出", "确定退出？", parent=self): self.destroy()

    def _focus_search(self):
        if not self._focus_in_app(): return
        try:
            self.nb.select(self.search_tab)
            self.search_entry.focus_set()
        except Exception:
            pass

    def _refresh_current(self):
        if not self._focus_in_app(): return
        try:
            idx = self.nb.index(self.nb.select())
        except Exception:
            idx = 0
        if idx == 0:
            self.load_repos(reset=True)
        elif idx == 2:
            self.load_issues()
        elif idx == 3:
            self.load_pulls()
        elif idx == 4:
            self.load_notifications()

    def _delete_selected(self, _e):
        focused = self.focus_get()
        if focused is None: return
        try:
            if not self.issue_tree.winfo_exists(): return
            w = focused
            while w is not None:
                if w == self.issue_tree:
                    self.delete_issue()
                    return
                w = getattr(w, "master", None)
        except Exception:
            pass

    # ---------- 设置 / 账号 ----------
    def _open_settings(self):
        if not self._focus_in_app(): return
        try:
            self.deiconify(); self.lift()
        except Exception:
            pass
        dlg = SettingsDialog(self, self.cfg)
        self.wait_window(dlg)
        if dlg.result is None: return
        r = dlg.result
        self.cfg.proxy = r["proxy"]
        self.cfg.oauth_client_id = r["oauth_client_id"]
        self.cfg.theme = r["theme"]
        self.cfg.poll_interval = r["poll_interval"]
        self.cfg.font_size = r.get("font_size", 10)
        self.cfg.save()
        if self.api:
            self.api.s.proxies = ({"http": self.cfg.proxy, "https": self.cfg.proxy} if self.cfg.proxy else {})
        self._setup_theme(self._resolve_theme(self.cfg.theme))
        for tree in self._iter_trees(self):
            self._tag_tree(tree)
        self._status("设置已保存")
        self._schedule_poll()

    def _switch_account(self):
        if not self.cfg.profiles:
            messagebox.showinfo("提示", "还没有保存的账号")
            return
        name = simpledialog.askstring("切换账号", f"已保存账号：\n{', '.join(self.cfg.profiles)}\n\n输入要切换到的账号：",
                                      parent=self)
        if not name or name not in self.cfg.profiles: return
        tok = self.cfg.get_token(name)
        if not tok:
            messagebox.showerror("错误", "该账号没有本地 Token")
            return
        self._login_with(tok, remember=True)

    def _fetch_scopes_async(self):
        api = self.api
        if api is None: return

        def work(): return api.s.get("https://api.github.com/user", timeout=10).headers.get("X-OAuth-Scopes", "") or ""

        def ok(scopes): self._scopes = scopes; self._update_status_user()

        def err(_e): self._scopes = ""; self._update_status_user()

        self.run_async(work, ok, err)

    # ---------- 登录 ----------
    def _build_login(self):
        outer = ttk.Frame(self)
        outer.pack(fill="both", expand=True)
        self.login_frame = outer

        center = ttk.Frame(outer)
        center.place(relx=0.5, rely=0.46, anchor="center")

        # 修复：如果本地有 tubiao/logo.png 则加载高清图，否则回退到 Emoji
        logo_path = os.path.join(get_base_dir(), "tubiao", "logo.png")
        if os.path.exists(logo_path):
            try:
                from PIL import Image, ImageTk
                img = Image.open(logo_path).convert("RGBA")
                resample = getattr(Image, "Resampling", Image)
                img = img.resize((96, 96), resample.LANCZOS)
                self._login_logo = ImageTk.PhotoImage(img)
                tk.Label(center, image=self._login_logo, bg=self.colors["BG"]).pack()
            except Exception as e:
                logging.warning(f"登录 logo 加载失败: {e}")
                ttk.Label(center, text="🐙", font=(self.ui_font, 64)).pack()
        else:
            ttk.Label(center, text="🐙", font=(self.ui_font, 64)).pack()

        ttk.Label(center, text="GitHub 桌面客户端", style="Title.TLabel").pack(pady=(8, 4))
        ttk.Label(center, text="使用 Personal Access Token 或 OAuth Device Flow 登录", style="Subtitle.TLabel").pack(
            pady=(0, 22))

        border = tk.Frame(center, bg=self.colors["CARD_BORDER"])
        border.pack()
        self._login_border = border
        accent = tk.Frame(border, bg=self.colors["ACCENT"], height=3)
        accent.pack(fill="x")
        self._login_accent = accent
        inner = ttk.Frame(border, padding=(36, 28))
        inner.pack(fill="both", expand=True, padx=1, pady=(0, 1))

        ttk.Label(inner, text="账号", style="Hint.TLabel", font=(self.ui_font, 9, "bold")).pack(anchor="w")
        row = ttk.Frame(inner)
        row.pack(fill="x", pady=(6, 14))
        self.profile_var = tk.StringVar(value=self.cfg.current or "")
        self.profile_combo = ttk.Combobox(row, textvariable=self.profile_var, values=self.cfg.profiles, width=34)
        self.profile_combo.pack(side="left", fill="x", expand=True)
        self.profile_combo.bind("<<ComboboxSelected>>", self._on_profile_change)
        ttk.Button(row, text="删除该账号", command=self._remove_profile).pack(side="left", padx=(6, 0))

        ttk.Label(inner, text="Personal Access Token", font=(self.ui_font, 9, "bold")).pack(anchor="w")
        self.token_entry = ttk.Entry(inner, width=52, show="•")
        self.token_entry.pack(fill="x", pady=(6, 10))
        self.token_entry.bind("<Return>", lambda _e: self.do_login())

        env = os.getenv("GITHUB_TOKEN")
        if env: self.token_entry.insert(0, env)

        self.remember_var = tk.BooleanVar(value=self.cfg.remember)
        ttk.Checkbutton(inner, text="记住登录（保存 Token 到系统密钥环）", variable=self.remember_var).pack(anchor="w")

        btns = ttk.Frame(inner)
        btns.pack(fill="x", pady=(20, 0))
        ttk.Button(btns, text="登 录", style="Accent.TButton", command=self.do_login).pack(side="left", expand=True,
                                                                                           fill="x")
        ttk.Button(btns, text="🔐 OAuth 登录", command=self.do_oauth_login).pack(side="left", expand=True, fill="x",
                                                                                padx=(10, 0))

        aux = ttk.Frame(inner)
        aux.pack(fill="x", pady=(12, 0))
        ttk.Button(aux, text="生成 Token", command=lambda: webbrowser.open("https://github.com/settings/tokens")).pack(
            side="left")
        ttk.Button(aux, text="⚙ 设置", command=self._open_settings).pack(side="right")

        self.status = ttk.Label(center, text="", style="Danger.TLabel")
        self.status.pack(pady=(14, 0))

        hint = ("🔐 Token 保存在系统密钥环。" if KEYRING_OK else f"🔐 Token 保存在（600 权限）：\n{self.cfg.path}")
        ttk.Label(center, text=hint, style="Hint.TLabel", justify="center", wraplength=560).pack(pady=(6, 0))

        if self.cfg.current:
            tok = self.cfg.get_token(self.cfg.current)
            if tok:
                self.token_entry.delete(0, "end")
                self.token_entry.insert(0, tok)

    def _on_profile_change(self, _e=None):
        name = self.profile_var.get().strip()
        if not name: return
        tok = self.cfg.get_token(name)
        if tok:
            self.token_entry.delete(0, "end")
            self.token_entry.insert(0, tok)

    def _remove_profile(self):
        name = self.profile_var.get().strip()
        if not name: return
        if not messagebox.askyesno("确认", f"删除账号 {name} 的本地凭据？"): return
        self.cfg.remove_profile(name)
        self.profile_combo["values"] = self.cfg.profiles
        self.profile_var.set(self.cfg.current or "")
        self.token_entry.delete(0, "end")
        self.status.configure(text="已删除", style="Success.TLabel")

    def do_login(self):
        token = self.token_entry.get().strip()
        if not token:
            self.status.configure(text="请输入 Token", style="Danger.TLabel")
            return
        self._login_with(token, self.remember_var.get())

    def do_oauth_login(self):
        cid = self.cfg.oauth_client_id.strip()
        if not cid:
            messagebox.showinfo("提示", "请先在设置中填入 OAuth App 的 Client ID")
            return
        dlg = OAuthDialog(self, cid, proxy=self.cfg.proxy)
        self.wait_window(dlg)
        if not dlg.token: return
        self.token_entry.delete(0, "end")
        self.token_entry.insert(0, dlg.token)
        self._login_with(dlg.token, True)

    def _login_with(self, token, remember):
        self.status.configure(text="正在验证…", style="Hint.TLabel")
        api = GitHubAPI(token, proxy=self.cfg.proxy, cache=self.cache)

        def ok(user):
            self.api = api
            self.current_user = user["login"]
            self.cfg.current = self.current_user
            self.cfg.remember = remember
            if self.current_user not in self.cfg.profiles: self.cfg.profiles.append(self.current_user)
            if remember: self.cfg.save_token(self.current_user, token)
            self.cfg.save()
            self._labels_cache.clear()
            self._repo_cache.clear()

            self.login_frame.pack_forget()
            self.main_frame.pack(fill="both", expand=True)

            public_count = user.get("public_repos", 0)
            private_count = user.get("total_private_repos") or 0
            self.user_label.configure(
                text=f"👤 @{user['login']}  ·  公开 {public_count}  ·  私有 {private_count}  ·  关注者 {user['followers']}")
            self._update_status_user()
            self._fetch_scopes_async()
            self._status("已登录")
            self._refresh_repo_switch()
            self.load_repos(reset=True)
            self._schedule_poll()

        def err(e):
            msg = str(e)
            if "401" in msg:
                self.cfg.remove_profile(self.profile_var.get().strip())
                msg = "Token 无效或已过期"
            self.status.configure(text=f"登录失败：{msg}", style="Danger.TLabel")

        self.run_async(api.me, ok, err)

    def _update_status_user(self):
        try:
            repo = self.current_repo or "（未选择）"
            user = self.current_user or "未登录"
            s = f"@{user}  ·  {repo}"
            if self._scopes: s += f"  ·  scopes: {self._scopes[:40]}"
            self.status_right.configure(text=s)
        except Exception:
            pass

    def logout(self):
        if messagebox.askyesno("退出登录", "同时清除已保存的 Token？"):
            if self.current_user:
                self.cfg.remove_profile(self.current_user)
                self.profile_combo["values"] = self.cfg.profiles
        self.api = None
        self.current_user = None
        self.current_repo = ""
        self._scopes = ""
        self.repo_var.set("（未选择）")
        self._repo_cache.clear()
        self._labels_cache.clear()
        self.issue_nodes.clear()
        self.main_frame.pack_forget()
        self.login_frame.pack(fill="both", expand=True)
        self.status.configure(text="", style="Danger.TLabel")
        if self._poll_after:
            try:
                self.after_cancel(self._poll_after)
            except Exception:
                pass

    # ---------- 主界面 ----------
    def _build_main(self):
        mf = ttk.Frame(self)
        self.main_frame = mf

        bar = ttk.Frame(mf, style="Status.TFrame")
        bar.pack(fill="x", side="bottom")
        ttk.Separator(bar, orient="horizontal").pack(fill="x")
        status_row = ttk.Frame(bar, padding=(14, 8))
        status_row.pack(fill="x")
        self.status_label = ttk.Label(status_row, text="就绪", style="Hint.TLabel")
        self.status_label.pack(side="left")
        self.status_right = ttk.Label(status_row, text="", style="Hint.TLabel")
        self.status_right.pack(side="right", padx=(0, 14))

        header = ttk.Frame(mf, padding=(18, 14), style="Header.TFrame")
        header.pack(fill="x")
        self.user_label = ttk.Label(header, style="Header.TLabel", font=(self.ui_font, 10, "bold"))
        self.user_label.pack(side="left")

        self.switch_var = tk.StringVar()
        self.repo_switch_combo = ttk.Combobox(header, textvariable=self.switch_var, width=24)
        self.repo_switch_combo.pack(side="left", padx=(16, 0))
        self.repo_switch_combo.bind("<<ComboboxSelected>>", self._on_switch_repo)

        theme_label = {"auto": "🌓", "light": "🌙", "dark": "☀️"}.get(self.cfg.theme, "🌓")
        self.theme_btn = ttk.Button(header, text=theme_label, width=3, command=self.toggle_theme)
        self.theme_btn.pack(side="right", padx=(4, 0))
        ttk.Button(header, text="⌨️", command=self._show_shortcuts).pack(side="right", padx=(4, 0))
        ttk.Button(header, text="👤 切换账号", command=self._switch_account).pack(side="right", padx=(4, 0))
        ttk.Button(header, text="⚙️ 设置", command=self._open_settings).pack(side="right", padx=(4, 0))
        ttk.Button(header, text="退出登录", command=self.logout).pack(side="right", padx=(4, 0))
        ttk.Button(header, text="🔄 刷新", command=self._refresh_current).pack(side="right", padx=(4, 0))
        ttk.Separator(mf, orient="horizontal").pack(fill="x")

        self.nb = ttk.Notebook(mf)
        self.nb.pack(fill="both", expand=True, padx=14, pady=(10, 10))
        self.nb.bind("<<NotebookTabChanged>>",
                     lambda _e: setattr(self.cfg, 'last_tab', self.nb.index(self.nb.select())))

        self._build_repo_tab(self.nb)
        self._build_search_tab(self.nb)
        self._build_issue_tab(self.nb)
        self._build_pull_tab(self.nb)
        self._build_notify_tab(self.nb)
        self._build_star_tab(self.nb)
        self.gist_tab = GistTab(self.nb, self)
        self.nb.add(self.gist_tab, text="📝 Gists")

    def _refresh_repo_switch(self):
        vals = list(self.cfg.recent_repos)
        vals.reverse()
        if self.cfg.favorites:
            favs = [f["repo"] for f in self.cfg.favorites]
            vals = favs + [v for v in vals if v not in favs]
        self.repo_switch_combo["values"] = vals

    def _on_switch_repo(self, _):
        repo = self.switch_var.get().strip()
        if not repo: return
        self.current_repo = repo
        self.repo_var.set(repo)
        self._update_status_user()
        self.cfg.add_recent_repo(repo)
        self._refresh_repo_switch()
        self.nb.select(2)
        self.load_issues()
        self.load_pulls()

    def _build_repo_tab(self, nb):
        tab = ttk.Frame(nb, padding=14)
        self.repo_tab = tab
        nb.add(tab, text="📁 我的仓库")

        sbar = ttk.Frame(tab)
        sbar.pack(fill="x", pady=(0, 10))
        ttk.Label(sbar, text="排序：").pack(side="left")
        sort_combo = ttk.Combobox(sbar, textvariable=self.repo_sort, width=10,
                                  values=("updated", "pushed", "created", "full_name"))
        sort_combo.pack(side="left")
        sort_combo.bind("<<ComboboxSelected>>", lambda _e: self.load_repos(reset=True))

        ttk.Label(sbar, text="可见性：").pack(side="left", padx=(14, 0))
        for txt, val in [("全部", "all"), ("公开", "public"), ("私有", "private")]:
            ttk.Radiobutton(sbar, text=txt, variable=self.repo_visibility, value=val,
                            command=lambda: self.load_repos(reset=True)).pack(side="left", padx=(4, 0))

        ttk.Button(sbar, text="➕ 新建仓库", style="Accent.TButton", command=self.create_repo).pack(side="right")
        ttk.Button(sbar, text="🗑️ 删除仓库", style="Danger.TButton", command=self.delete_repo).pack(side="right",
                                                                                                    padx=(0, 6))
        ttk.Button(sbar, text="🚀 上传项目", command=self.upload_project).pack(side="right", padx=(0, 6))

        self.repo_filter_var = tk.StringVar()
        fbar = ttk.Frame(tab)
        fbar.pack(fill="x", pady=(0, 8))
        ttk.Label(fbar, text="筛选（本地）：").pack(side="left")
        ttk.Entry(fbar, textvariable=self.repo_filter_var, width=40).pack(side="left", padx=(6, 0))
        self.repo_filter_var.trace_add("write", lambda *_: self._apply_repo_filter())

        self.repo_tree = self._make_tree(
            tab, "repo_tree", cols=("name", "visibility", "stars", "lang", "updated", "local"),
            heads=("仓库", "可见性", "星标", "语言", "更新时间", "本地"),
            widths=(360, 90, 70, 120, 170, 80))
        self.repo_tree.bind("<<TreeviewSelect>>", self._on_repo_select)
        self.repo_tree.bind("<Double-1>", lambda _e: self._show_detail_for(self.repo_tree))
        self.repo_tree.bind("<Button-3>", self._repo_context_menu)
        self.repo_tree.bind("<Button-2>", self._repo_context_menu)

        row1 = ttk.Frame(tab)
        row1.pack(fill="x", pady=(12, 0))
        self.zip_btn = ttk.Button(row1, text="⬇️ 下载 ZIP", command=self._zip_for_repo_tab)
        self.zip_btn.pack(side="left")
        self.clone_btn = ttk.Button(row1, text="📦 git clone", command=self._clone_for_repo_tab)
        self.clone_btn.pack(side="left", padx=(6, 0))
        self.pull_btn = ttk.Button(row1, text="🔄 git pull", command=self._pull_for_repo_tab)
        self.pull_btn.pack(side="left", padx=(6, 0))
        self.detail_btn = ttk.Button(row1, text="🔍 详情", command=lambda: self._show_detail_for(self.repo_tree))
        self.detail_btn.pack(side="left", padx=(6, 0))
        self.asset_btn = ttk.Button(row1, text="📥 安装包", command=self._download_installer_for_repo_tab)
        self.asset_btn.pack(side="left", padx=(6, 0))
        ttk.Button(row1, text="📥 队列", command=self._show_download_queue).pack(side="right", padx=(0, 6))
        ttk.Button(row1, text="⬇️ 下一页", command=lambda: self.load_repos(reset=False)).pack(side="right")

        self.progress = ttk.Progressbar(tab, mode="determinate", maximum=100)

    def _apply_repo_filter(self):
        q = self.repo_filter_var.get().strip().lower()
        if not hasattr(self, "repo_tree"): return
        for iid in self.repo_tree.get_children():
            if str(iid).startswith("__state__"): continue
            vals = self.repo_tree.item(iid, "values")
            if not vals: continue
            if not q or q in vals[0].lower():
                self.repo_tree.reattach(iid, "", "end")
            else:
                self.repo_tree.detach(iid)

    def _repo_context_menu(self, e):
        tree = self.repo_tree
        row = tree.identify_row(e.y)
        if not row or str(row).startswith("__state__"): return
        tree.selection_set(row)
        repo = row
        local = self._local_repo_path(repo)
        menu = tk.Menu(self, tearoff=0)

        is_fav = self.cfg.is_favorite(repo)
        menu.add_command(label="⭐ 取消收藏" if is_fav else "⭐ 收藏此仓库",
                         command=lambda: self._toggle_fav(repo))
        is_mute = repo in self.cfg.muted_repos
        menu.add_command(label="🔔 取消静音" if is_mute else "🔕 静音通知",
                         command=lambda: self._toggle_mute(repo))
        menu.add_separator()

        menu.add_command(label="复制 HTTPS 地址", command=lambda: self._copy(f"https://github.com/{repo}.git"))
        menu.add_command(label="复制 SSH 地址", command=lambda: self._copy(f"git@github.com:{repo}.git"))
        menu.add_command(label="复制仓库名", command=lambda: self._copy(repo))
        menu.add_separator()
        menu.add_command(label="在浏览器打开", command=lambda: webbrowser.open(f"https://github.com/{repo}"))
        menu.add_command(label="查看详情", command=lambda: self._show_detail_for(tree))
        menu.add_command(label="下载最新安装包", command=lambda: self._download_latest_release(repo))
        menu.add_separator()
        if local:
            menu.add_command(label="📁 在资源管理器中打开", command=lambda: self._open_local("explorer", local))
            menu.add_command(label="🧑‍💻 用 VS Code 打开", command=lambda: self._open_local("vscode", local))
            menu.add_command(label="⌨️ 在终端中打开", command=lambda: self._open_local("terminal", local))
            menu.add_separator()
            menu.add_command(label="🔄 git pull", command=lambda: self._pull_path(local))
        else:
            menu.add_command(label="📦 git clone 到本地", command=lambda: self._clone_for_repo_tab())
        try:
            menu.tk_popup(e.x_root, e.y_root)
        finally:
            menu.grab_release()

    def _toggle_fav(self, repo):
        if self.cfg.is_favorite(repo):
            self.cfg.remove_favorite(repo)
            self._status(f"已取消收藏 {repo}")
        else:
            self.cfg.add_favorite(repo)
            self._status(f"已收藏 {repo}")
        self._refresh_repo_switch()

    def _toggle_mute(self, repo):
        self.cfg.toggle_mute(repo)
        self._status(f"已{'取消静音' if repo not in self.cfg.muted_repos else '静音'} {repo}")

    def _open_local(self, how, path):
        try:
            if how == "explorer":
                open_path_in_os(path)
            elif how == "vscode":
                open_in_vscode(path)
            else:
                open_terminal(path)
            self._status(f"已打开：{path}")
        except Exception as e:
            messagebox.showerror("错误", str(e))

    def _pull_path(self, path):
        def ok(out):
            self._status("git pull 完成")
            messagebox.showinfo("完成", out[-1500:] or "无输出")

        self.run_async(lambda: self.api.pull_repo(path), ok)

    def _copy(self, text):
        try:
            self.clipboard_clear()
            self.clipboard_append(text)
            self._status(f"已复制：{text}", 2000)
        except Exception:
            pass

    def _show_download_queue(self):
        if self._dl_window is None or not self._dl_window.winfo_exists():
            self._dl_window = DownloadQueueWindow(self)
        else:
            self._dl_window.lift()

    def _enqueue_download(self, repo, asset, dest):
        self._show_download_queue()
        task = DownloadTask(asset.get("name") or "?", repo, asset, dest)
        self._dl_window.add(task)

    def _local_repo_path(self, repo):
        base = self.cfg.last_dir
        if not base or not os.path.isdir(base): return None
        for name in (repo.split("/")[-1], repo.replace("/", "-")):
            p = os.path.join(base, name)
            if os.path.isdir(os.path.join(p, ".git")): return p
        return None

    def load_repos(self, reset=False):
        if not self.api: return
        if reset:
            self._repo_page = 1
            self.repo_tree.delete(*self.repo_tree.get_children())
            self._tree_set_state(self.repo_tree, "loading", "加载中…")
        else:
            self._repo_page += 1
        page = self._repo_page
        sort = self.repo_sort.get()
        vis = self.repo_visibility.get()
        self._gen_repos += 1
        gen = self._gen_repos

        cache_key = f"repos:{self.current_user}:{sort}:{vis}:{page}"

        def ok(repos):
            if gen != self._gen_repos: return
            self.cache.set(cache_key, repos)
            self._render_repos(repos, page)

        def err(e):
            if gen != self._gen_repos: return
            msg = str(e)
            if "网络" in msg or "Connection" in msg:
                cached = self.cache.get(cache_key, max_age=86400)
                if cached:
                    self._render_repos(cached, page)
                    self._status("离线模式：加载缓存")
                    return
            self._tree_set_state(self.repo_tree, "error", f"加载失败，双击重试", retry=lambda: self.load_repos(reset))
            self._err(e)

        self.run_async(lambda: self.api.my_repos(page=page, sort=sort, visibility=vis), ok, err)

    def _render_repos(self, repos, page):
        for iid in self.repo_tree.get_children():
            if str(iid).startswith("__state__"): self.repo_tree.delete(iid)

        if not repos:
            if page == 1:
                self._tree_set_state(self.repo_tree, "empty", "暂无仓库")
            else:
                self._status("没有更多了")
            return

        for i, r in enumerate(repos):
            iid = r["full_name"]
            tags = ("odd",) if (i + (page - 1) * 50) % 2 else ("even",)
            if not self.repo_tree.exists(iid):
                vis_str = "🔒 私有" if r["private"] else "🌐 公开"
                local = "📁" if self._local_repo_path(r["full_name"]) else "—"
                self.repo_tree.insert("", "end", iid=iid, values=(
                    r["full_name"], vis_str, r["stargazers_count"],
                    r.get("language") or "—",
                    _rel_time(r["updated_at"]), local), tags=tags)
        self._status(f"已加载第 {page} 页（{len(repos)} 个）")

    def _on_repo_select(self, _event):
        repo = self._selected(self.repo_tree)
        if not repo or str(repo).startswith("__state__"): return
        self.current_repo = repo
        self.repo_var.set(repo)
        self._update_status_user()
        self.cfg.add_recent_repo(repo)
        self._refresh_repo_switch()
        if self._debounce_after:
            try:
                self.after_cancel(self._debounce_after)
            except Exception:
                pass
        self._debounce_after = self.after(300, self.load_issues)

    def create_repo(self):
        dlg = CreateRepoDialog(self)
        self.wait_window(dlg)
        if not dlg.result: return
        d = dlg.result

        def ok(repo):
            self._status(f"已创建 {repo['full_name']}")
            self.repo_visibility.set("all")
            self.after(800, lambda: self.load_repos(reset=True))
            messagebox.showinfo("完成", f"已创建 {repo['full_name']}")

        self.run_async(lambda: self.api.create_repo(**d), ok)

    def delete_repo(self):
        repo = self._selected(self.repo_tree)
        if not repo or str(repo).startswith("__state__"):
            messagebox.showinfo("提示", "先选中一个仓库")
            return
        owner = repo.split("/", 1)[0]
        if owner != (self.current_user or ""):
            messagebox.showwarning("注意", "该仓库可能不属于你个人，请确认权限。")
        if not messagebox.askyesno("⚠️ 危险操作", f"确定删除 {repo}？不可撤销。", icon="warning"): return
        confirm = simpledialog.askstring("最终确认", f"输入仓库全名确认删除：\n{repo}", parent=self)
        if confirm != repo:
            messagebox.showinfo("已取消", "名称不匹配")
            return

        def ok(_):
            self._status(f"已删除 {repo}")
            self._repo_cache.pop(repo, None)
            if self.current_repo == repo:
                self.current_repo = ""
                self.repo_var.set("（未选择）")
                self.issue_tree.delete(*self.issue_tree.get_children())
                self._update_status_user()
            self.after(800, lambda: self.load_repos(reset=True))

        self.run_async(lambda: self.api.delete_repo(repo), ok)

    def upload_project(self):
        """把本地目录上传到 GitHub 仓库"""
        if not self._focus_in_app():
            return
        if not self.api:
            messagebox.showinfo("提示", "请先登录")
            return

        default_dir = self.cfg.last_dir or ""
        dlg = UploadProjectDialog(self, default_dir=default_dir)
        self.wait_window(dlg)
        if not dlg.result:
            return
        r = dlg.result
        full = f"{self.current_user}/{r['name']}"
        if not messagebox.askyesno(
                "确认上传",
                f"本地目录：\n{r['local']}\n\n"
                f"将推送到：\n{full}\n"
                f"分支：{r['branch']}（{'私有' if r['private'] else '公开'}）\n\n继续？",
                parent=self):
            return

        # 可选：自动生成 .gitignore
        if r["add_gitignore"]:
            gi = os.path.join(r["local"], ".gitignore")
            if not os.path.exists(gi):
                try:
                    with open(gi, "w", encoding="utf-8") as fp:
                        fp.write(_DEFAULT_GITIGNORE)
                except OSError as e:
                    logging.warning(f"写入 .gitignore 失败：{e}")

        def work():
            # 仓库不存在则创建（auto_init=False 避免空仓库冲突）
            exists = False
            try:
                self.api.get_repo(full)
                exists = True
            except RuntimeError:
                exists = False
            if not exists:
                self.api.create_repo(
                    r["name"], description=r["description"],
                    private=r["private"], auto_init=False)
            return self.api.init_and_push_local(
                r["local"], full,
                branch=r["branch"],
                commit_message=r["commit_message"],
                user=self.current_user,
                on_progress=lambda p, line: self.after(
                    0, lambda: self._status(line, 8000)),
            )

        def ok(url):
            self._status(f"已上传：{full}")
            self.cfg.add_recent_repo(full)
            self._refresh_repo_switch()
            self.after(600, lambda: self.load_repos(reset=True))
            messagebox.showinfo(
                "上传完成",
                f"已推送到：\n{full}\n\n{url}\n\n"
                f"可在浏览器打开仓库查看。",
                parent=self)

        def err(e):
            self._status("上传失败")
            self._err(e)

        self._status("正在上传项目…")
        self.run_async(work, ok, err)

    # ---------- 搜索 ----------
    def _build_search_tab(self, nb):
        tab = ttk.Frame(nb, padding=14)
        self.search_tab = tab
        nb.add(tab, text="🔍 搜索")

        sbar = ttk.Frame(tab)
        sbar.pack(fill="x", pady=(0, 10))
        ttk.Label(sbar, text="模式：").pack(side="left")
        for txt, val in [("仓库", "repos"), ("代码", "code"), ("趋势", "trending")]:
            ttk.Radiobutton(sbar, text=txt, variable=self.search_mode, value=val, command=self._on_search_typing).pack(
                side="left", padx=(0, 6))

        self.search_entry = ttk.Entry(sbar, width=48)
        self.search_entry.pack(side="left", padx=(6, 6))
        self.search_entry.bind("<Return>", lambda _e: self.do_search())
        self.search_entry.bind("<KeyRelease>", self._on_search_typing)

        self.search_btn = ttk.Button(sbar, text="搜索", style="Accent.TButton", command=self.do_search)
        self.search_btn.pack(side="left")
        ttk.Button(sbar, text="清空", command=self.clear_search).pack(side="left", padx=(6, 0))
        self.search_status = ttk.Label(sbar, text="", style="Hint.TLabel")
        self.search_status.pack(side="left", padx=12)

        self.search_tree = self._make_tree(
            tab, "search_tree", cols=("name", "stars", "lang", "desc"),
            heads=("仓库", "星标", "语言", "描述"), widths=(320, 80, 130, 560))
        self.search_tree.bind("<Double-1>", lambda _e: self._show_detail_for(self.search_tree))

        row1 = ttk.Frame(tab)
        row1.pack(fill="x", pady=(12, 0))
        self.search_zip_btn = ttk.Button(row1, text="⬇️ ZIP", command=self._zip_for_search_tab)
        self.search_zip_btn.pack(side="left")
        self.search_clone_btn = ttk.Button(row1, text="📦 clone", command=self._clone_for_search_tab)
        self.search_clone_btn.pack(side="left", padx=(6, 0))
        self.search_detail_btn = ttk.Button(row1, text="🔍 详情",
                                            command=lambda: self._show_detail_for(self.search_tree))
        self.search_detail_btn.pack(side="left", padx=(6, 0))
        self.search_asset_btn = ttk.Button(row1, text="📥 安装包", command=self._download_installer_for_search_tab)
        self.search_asset_btn.pack(side="left", padx=(6, 0))
        self.search_progress = ttk.Progressbar(tab, mode="determinate", maximum=100)

    def _on_search_typing(self, event=None):
        if event and event.keysym in ("Up", "Down", "Return", "Escape"): return
        if self.search_mode.get() != "repos": return
        if self._search_after:
            try:
                self.after_cancel(self._search_after)
            except Exception:
                pass
        self._search_after = self.after(500, self.do_search)

    def do_search(self):
        q = self.search_entry.get().strip()
        mode = self.search_mode.get()

        if mode != "repos" and not q:
            if self.cfg.search_history:
                self.search_entry["values"] = self.cfg.search_history[::-1]
            return
        if q: self.cfg.add_search_history(q)
        self.search_entry["values"] = self.cfg.search_history[::-1]

        if mode == "trending":
            self.search_btn.configure(state="disabled")
            self.search_status.configure(text="加载趋势…")
            self._tree_set_state(self.search_tree, "loading", "加载中…")

            def ok(items):
                self._fill_search_results(items)
                self.search_btn.configure(state="normal")
                self.search_status.configure(text=f"{len(items)} 个趋势仓库")

            def err(e):
                self.search_btn.configure(state="normal")
                self._tree_set_state(self.search_tree, "error", "加载失败")
                self._err(e)

            self.run_async(lambda: self.api.trending_repos(), ok, err)
            return
        if not q: return

        self.search_btn.configure(state="disabled")
        self.search_status.configure(text="查询中…")
        self._tree_set_state(self.search_tree, "loading", "查询中…")

        if mode == "code":
            def ok(res):
                items, total = res
                self.search_tree.delete(*self.search_tree.get_children())
                if not items: self._tree_set_state(self.search_tree, "empty", "无代码结果")
                for i, it in enumerate(items):
                    repo_full = it["repository"]["full_name"]
                    self.search_tree.insert("", "end", iid=f"{repo_full}:{it['path']}",
                                            values=(f"{repo_full}/{it['path']}", "—", "—", "—"),
                                            tags=("odd",) if i % 2 else ("even",))
                self.search_btn.configure(state="normal")
                self.search_status.configure(text=f"代码 {total} 个")

            def err(e):
                self.search_btn.configure(state="normal")
                self._tree_set_state(self.search_tree, "error", "查询失败")
                self._err(e)

            self.run_async(lambda: self.api.search_code(q), ok, err)
            return

        if REPO_RE.match(q):
            def ok(repo):
                self._fill_search_results([repo])
                self.search_btn.configure(state="normal")
                self.search_status.configure(text=f"定位到 {repo['full_name']}")

            def err(e):
                self.search_btn.configure(state="normal")
                self._tree_set_state(self.search_tree, "empty", "未找到该仓库")
                self._err(e)

            self.run_async(lambda: self.api.get_repo(q), ok, err)
            return

        def ok(res):
            items, total = res
            self._fill_search_results(items)
            self.search_btn.configure(state="normal")
            self.search_status.configure(text=f"共 {total} 个，显示前 {len(items)}")

        def err(e):
            self.search_btn.configure(state="normal")
            self._tree_set_state(self.search_tree, "error", "查询失败")
            self._err(e)

        self.run_async(lambda: self.api.search_repos(q), ok, err)

    def _fill_search_results(self, items):
        self.search_tree.delete(*self.search_tree.get_children())
        if not items:
            self._tree_set_state(self.search_tree, "empty", "无结果")
            return
        for i, r in enumerate(items):
            desc = (r.get("description") or "—").replace("\n", " ")
            if len(desc) > 72: desc = desc[:72] + "…"
            self.search_tree.insert("", "end", iid=r["full_name"],
                                    values=(r["full_name"], r["stargazers_count"], r.get("language") or "—", desc),
                                    tags=("odd",) if i % 2 else ("even",))
            self._repo_cache[r["full_name"]] = r

    def clear_search(self):
        self.search_entry.delete(0, "end")
        self.search_tree.delete(*self.search_tree.get_children())
        self.search_status.configure(text="")

    # ---------- Issue ----------
    def _build_issue_tab(self, nb):
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="📝 Issues")

        head = ttk.Frame(tab)
        head.pack(fill="x", pady=(0, 6))
        ttk.Label(head, text="当前仓库：", style="Hint.TLabel").pack(side="left")
        ttk.Label(head, textvariable=self.repo_var, font=(self.ui_font, 10, "bold")).pack(side="left")

        sbar = ttk.Frame(tab)
        sbar.pack(fill="x", pady=(0, 6))
        ttk.Label(sbar, text="状态：").pack(side="left")
        for txt, val in [("打开", "open"), ("关闭", "closed"), ("全部", "all")]:
            ttk.Radiobutton(sbar, text=txt, variable=self.issue_state, value=val, command=self._reload_issues).pack(
                side="left", padx=(0, 8))

        ttk.Label(sbar, text="指派者：").pack(side="left", padx=(10, 0))
        self.issue_assignee_var = tk.StringVar()
        ttk.Entry(sbar, textvariable=self.issue_assignee_var, width=12).pack(side="left")
        self.issue_assignee_var.trace_add("write", lambda *_: self._reload_issues())

        ttk.Button(sbar, text="⬇️ 下一页", command=lambda: self.load_issues(next_page=True)).pack(side="right")

        fbar = ttk.Frame(tab)
        fbar.pack(fill="x", pady=(0, 8))
        ttk.Label(fbar, text="本地筛选：").pack(side="left")
        self.issue_filter_var = tk.StringVar()
        ttk.Entry(fbar, textvariable=self.issue_filter_var, width=40).pack(side="left", padx=(6, 0))
        self.issue_filter_var.trace_add("write", lambda *_: self._apply_issue_filter())

        self.issue_tree = self._make_tree(
            tab, "issue_tree", cols=("number", "title", "state", "user", "labels", "comments", "updated"),
            heads=("#", "标题", "状态", "作者", "标签", "评论", "更新"), widths=(60, 400, 100, 140, 200, 60, 160))
        self.issue_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_issue_buttons_state())
        self.issue_tree.bind("<Double-1>", lambda _e: self._open_issue_detail())

        tools = ttk.Frame(tab)
        tools.pack(fill="x", pady=(12, 0))
        self.issue_new_btn = ttk.Button(tools, text="➕ 新建", style="Accent.TButton", command=self.new_issue)
        self.issue_new_btn.pack(side="left")
        self.issue_detail_btn = ttk.Button(tools, text="🔍 详情", state="disabled", command=self._open_issue_detail)
        self.issue_detail_btn.pack(side="left", padx=(6, 0))
        self.issue_edit_btn = ttk.Button(tools, text="✏️ 编辑", state="disabled", command=self.edit_issue)
        self.issue_edit_btn.pack(side="left", padx=(6, 0))
        self.issue_toggle_btn = ttk.Button(tools, text="🔒 关闭", state="disabled", command=self.toggle_issue)
        self.issue_toggle_btn.pack(side="left", padx=(6, 0))
        self.issue_comment_btn = ttk.Button(tools, text="💬 评论", state="disabled", command=self.comment_issue)
        self.issue_comment_btn.pack(side="left", padx=(6, 0))
        self.issue_delete_btn = ttk.Button(tools, text="🗑️ 删除", style="Danger.TButton", state="disabled",
                                           command=self.delete_issue)
        self.issue_delete_btn.pack(side="left", padx=(6, 0))
        ttk.Button(tools, text="🔄 刷新", command=self._reload_issues).pack(side="right")

    def _apply_issue_filter(self):
        q = self.issue_filter_var.get().strip().lower() if hasattr(self, "issue_filter_var") else ""
        if not hasattr(self, "issue_tree"): return
        for iid in self.issue_tree.get_children():
            if str(iid).startswith("__state__"): continue
            vals = self.issue_tree.item(iid, "values")
            if not vals: continue
            text = " ".join(str(v).lower() for v in vals)
            if not q or q in text:
                self.issue_tree.reattach(iid, "", "end")
            else:
                self.issue_tree.detach(iid)

    def _open_issue_detail(self):
        sel = self.issue_tree.selection()
        if not sel or not self.current_repo: return
        IssueDetailWindow(self, self.current_repo, int(sel[0]))

    def _reload_issues(self):
        self._issue_page = 0
        self.load_issues()

    def load_issues(self, next_page=False):
        self._debounce_after = None
        if not self.current_repo: return
        repo = self.current_repo
        state = self.issue_state.get()
        assignee = self.issue_assignee_var.get().strip()

        if next_page:
            self._issue_page += 1
        else:
            self._issue_page = 1
            self.issue_tree.delete(*self.issue_tree.get_children())
            self._tree_set_state(self.issue_tree, "loading", "加载中…")

        page = self._issue_page
        self._gen_issues += 1
        gen = self._gen_issues

        cache_key = f"issues:{self.current_user}:{repo}:{state}:{assignee}:{page}"

        def ok(items):
            if gen != self._gen_issues: return
            self.cache.set(cache_key, items)
            self._render_issues(items, repo, page)

        def err(e):
            if gen != self._gen_issues: return
            msg = str(e)
            if "网络" in msg or "Connection" in msg:
                cached = self.cache.get(cache_key, max_age=86400)
                if cached:
                    self._render_issues(cached, repo, page)
                    self._status("离线模式：加载缓存")
                    return
            self._tree_set_state(self.issue_tree, "error", "加载失败，双击重试", retry=self._reload_issues)
            self._err(e)

        self.run_async(lambda: self.api.list_issues(repo, state=state, page=page, assignee=assignee or None), ok, err)

    def _render_issues(self, items, repo, page):
        for iid in self.issue_tree.get_children():
            if str(iid).startswith("__state__"): self.issue_tree.delete(iid)

        shown = 0
        base = len(self.issue_tree.get_children())
        for it in items:
            if "pull_request" in it: continue
            self.issue_nodes[it["number"]] = it["node_id"]
            tags = ["odd" if (base + shown) % 2 else "even"]
            if it["state"] == "closed": tags.append("closed")
            labels = ",".join(l["name"] for l in it.get("labels", []))
            iid = str(it["number"])
            if self.issue_tree.exists(iid): self.issue_tree.delete(iid)
            self.issue_tree.insert("", "end", iid=iid, values=(
                it["number"], it["title"], "🟢 open" if it["state"] == "open" else "🔴 closed",
                it["user"]["login"], labels, it["comments"], _rel_time(it["updated_at"])), tags=tuple(tags))
            shown += 1

        if shown == 0 and page == 1:
            self._tree_set_state(self.issue_tree, "empty", "无 Issue")
        else:
            self._status(f"{repo}：第 {page} 页（{shown} 条）")
        self._update_issue_buttons_state()

    def _update_issue_buttons_state(self):
        sel = self.issue_tree.selection()
        has = bool(sel) and not str(sel[0]).startswith("__state__")
        state = "normal" if has else "disabled"
        for b in (self.issue_edit_btn, self.issue_toggle_btn, self.issue_comment_btn, self.issue_delete_btn,
                  self.issue_detail_btn):
            b.configure(state=state)
        if has:
            vals = self.issue_tree.item(sel[0], "values")
            st = vals[2] if len(vals) > 2 else ""
            self.issue_toggle_btn.configure(text="🔓 重新打开" if "closed" in st else "🔒 关闭")

    def _fetch_labels_async(self, repo, callback):
        cached = self._labels_cache.get(repo)
        if cached is not None:
            callback(cached)
            return

        def ok(labels):
            self._labels_cache[repo] = labels
            callback(labels)

        def err(_e):
            self._labels_cache[repo] = []
            callback([])

        self.run_async(lambda: self.api.list_labels(repo), ok, err)

    def new_issue(self):
        if not self._focus_in_app(): return
        if not self.current_repo:
            messagebox.showinfo("提示", "先在「我的仓库」中选中一个仓库")
            return
        repo = self.current_repo

        def open_dialog(labels):
            dlg = IssueDialog(self, "新建 Issue", available_labels=labels)
            self.wait_window(dlg)
            if not dlg.result: return
            d = dlg.result

            def ok(issue):
                self._status(f"已创建 #{issue['number']}")
                self._reload_issues()

            self._busy_do([self.issue_new_btn],
                          lambda: self.api.create_issue(repo, d["title"], d["body"], labels=d["labels"],
                                                        assignees=d["assignees"]), ok)

        self._fetch_labels_async(repo, open_dialog)

    def edit_issue(self):
        sel = self.issue_tree.selection()
        if not sel or str(sel[0]).startswith("__state__"): return
        self._open_issue_detail_edit(int(sel[0]))

    def _open_issue_detail_edit(self, number):
        w = IssueDetailWindow(self, self.current_repo, number)
        w.after(500, w._edit)

    def toggle_issue(self):
        sel = self.issue_tree.selection()
        if not sel or str(sel[0]).startswith("__state__"): return
        number = int(sel[0])
        vals = self.issue_tree.item(sel[0], "values")
        is_closed = "closed" in (vals[2] if len(vals) > 2 else "")
        new_state = "open" if is_closed else "closed"
        action = "重新打开" if new_state == "open" else "关闭"
        if not messagebox.askyesno("确认", f"{action} #{number}？"): return

        def done(_):
            self._status(f"已{action} #{number}")
            self._reload_issues()

        self._busy_do([self.issue_toggle_btn],
                      lambda: self.api.update_issue(self.current_repo, number, state=new_state), done)

    def comment_issue(self):
        sel = self.issue_tree.selection()
        if not sel or str(sel[0]).startswith("__state__"): return
        number = int(sel[0])
        dlg = CommentDialog(self)
        self.wait_window(dlg)
        if not dlg.result: return

        def ok(_):
            self._status("评论已发送")

        self.run_async(lambda: self.api.create_comment(self.current_repo, number, dlg.result), ok)

    def delete_issue(self):
        sel = self.issue_tree.selection()
        if not sel or str(sel[0]).startswith("__state__"): return
        number = int(sel[0])
        node_id = self.issue_nodes.get(number)
        if not node_id:
            messagebox.showerror("错误", "缺少 node_id，请刷新")
            return
        if not messagebox.askyesno("⚠️ 永久删除", f"永久删除 #{number}？不可恢复。", icon="warning"): return

        def done(_):
            self._status(f"已删除 #{number}")
            self._reload_issues()

        self._busy_do([self.issue_delete_btn], lambda: self.api.delete_issue(node_id), done)

    # ---------- Pull ----------
    def _build_pull_tab(self, nb):
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="🔀 PR")

        sbar = ttk.Frame(tab)
        sbar.pack(fill="x", pady=(0, 6))
        ttk.Label(sbar, text="状态：").pack(side="left")
        for txt, val in [("打开", "open"), ("关闭", "closed"), ("全部", "all")]:
            ttk.Radiobutton(sbar, text=txt, variable=self.pull_state, value=val, command=self._reload_pulls).pack(
                side="left", padx=(0, 8))
        ttk.Button(sbar, text="⬇️ 下一页", command=lambda: self.load_pulls(next_page=True)).pack(side="right")

        fbar = ttk.Frame(tab)
        fbar.pack(fill="x", pady=(0, 8))
        ttk.Label(fbar, text="本地筛选：").pack(side="left")
        self.pull_filter_var = tk.StringVar()
        ttk.Entry(fbar, textvariable=self.pull_filter_var, width=40).pack(side="left", padx=(6, 0))
        self.pull_filter_var.trace_add("write", lambda *_: self._apply_pull_filter())

        self.pull_tree = self._make_tree(
            tab, "pull_tree", cols=("number", "title", "state", "user", "head", "base"),
            heads=("#", "标题", "状态", "作者", "来源", "目标"), widths=(60, 420, 110, 150, 170, 170))
        self.pull_tree.bind("<<TreeviewSelect>>", lambda _e: self._update_pull_buttons_state())
        self.pull_tree.bind("<Double-1>", lambda _e: self._open_pr_detail())

        tools = ttk.Frame(tab)
        tools.pack(fill="x", pady=(12, 0))
        self.pr_detail_btn = ttk.Button(tools, text="🔍 详情", state="disabled", command=self._open_pr_detail)
        self.pr_detail_btn.pack(side="left")
        self.pull_merge_btn = ttk.Button(tools, text="🔀 合并", state="disabled", style="Accent.TButton",
                                         command=self.merge_pull)
        self.pull_merge_btn.pack(side="left", padx=(6, 0))
        self.pull_close_btn = ttk.Button(tools, text="✖️ 关闭", state="disabled", command=self.close_pull)
        self.pull_close_btn.pack(side="left", padx=(6, 0))
        ttk.Button(tools, text="🔄 刷新", command=self._reload_pulls).pack(side="right")

    def _apply_pull_filter(self):
        q = self.pull_filter_var.get().strip().lower() if hasattr(self, "pull_filter_var") else ""
        if not hasattr(self, "pull_tree"): return
        for iid in self.pull_tree.get_children():
            if str(iid).startswith("__state__"): continue
            vals = self.pull_tree.item(iid, "values")
            if not vals: continue
            text = " ".join(str(v).lower() for v in vals)
            if not q or q in text:
                self.pull_tree.reattach(iid, "", "end")
            else:
                self.pull_tree.detach(iid)

    def _open_pr_detail(self):
        sel = self.pull_tree.selection()
        if not sel or not self.current_repo or str(sel[0]).startswith("__state__"): return
        PRDetailWindow(self, self.current_repo, int(sel[0]))

    def _reload_pulls(self):
        self._pull_page = 0
        self.load_pulls()

    def load_pulls(self, next_page=False):
        if not self.current_repo: return
        repo = self.current_repo
        state = self.pull_state.get()
        if next_page:
            self._pull_page += 1
        else:
            self._pull_page = 1
            self.pull_tree.delete(*self.pull_tree.get_children())
            self._tree_set_state(self.pull_tree, "loading", "加载中…")
        page = self._pull_page
        self._gen_pulls += 1
        gen = self._gen_pulls

        cache_key = f"pulls:{self.current_user}:{repo}:{state}:{page}"

        def ok(items):
            if gen != self._gen_pulls: return
            self.cache.set(cache_key, items)
            self._render_pulls(items, page)

        def err(e):
            if gen != self._gen_pulls: return
            msg = str(e)
            if "网络" in msg or "Connection" in msg:
                cached = self.cache.get(cache_key, max_age=86400)
                if cached:
                    self._render_pulls(cached, page)
                    self._status("离线模式：加载缓存")
                    return
            self._tree_set_state(self.pull_tree, "error", "加载失败，双击重试", retry=self._reload_pulls)
            self._err(e)

        self.run_async(lambda: self.api.list_pulls(repo, state=state, page=page), ok, err)

    def _render_pulls(self, items, page):
        for iid in self.pull_tree.get_children():
            if str(iid).startswith("__state__"): self.pull_tree.delete(iid)

        if not items and page == 1:
            self._tree_set_state(self.pull_tree, "empty", "无 PR")
            return

        base = len(self.pull_tree.get_children())
        for i, p in enumerate(items):
            tags = ("odd",) if (base + i) % 2 else ("even",)
            self.pull_tree.insert("", "end", iid=str(p["number"]), values=(
                p["number"], p["title"], "🟢 open" if p["state"] == "open" else "🔴 closed",
                p["user"]["login"], p["head"]["ref"], p["base"]["ref"],
            ), tags=tags)
        self._update_pull_buttons_state()
        self._status(f"已加载第 {page} 页 PR")

    def _update_pull_buttons_state(self):
        sel = self.pull_tree.selection()
        has = bool(sel) and not str(sel[0]).startswith("__state__")
        st = "normal" if has else "disabled"
        self.pull_merge_btn.configure(state=st)
        self.pull_close_btn.configure(state=st)
        self.pr_detail_btn.configure(state=st)

    def merge_pull(self):
        sel = self.pull_tree.selection()
        if not sel or str(sel[0]).startswith("__state__"): return
        number = int(sel[0])
        if not messagebox.askyesno("合并 PR", f"确定合并 #{number}？"): return

        def done(res):
            self._status(f"合并结果：{res.get('merged')}")
            self._reload_pulls()

        self.run_async(lambda: self.api.merge_pull(self.current_repo, number), done)

    def close_pull(self):
        sel = self.pull_tree.selection()
        if not sel or str(sel[0]).startswith("__state__"): return
        number = int(sel[0])
        if not messagebox.askyesno("关闭 PR", f"确定关闭 #{number}？"): return

        def done(_):
            self._status(f"已关闭 #{number}")
            self._reload_pulls()

        self.run_async(lambda: self.api.close_pull(self.current_repo, number), done)

    # ---------- Notifications ----------
    def _build_notify_tab(self, nb):
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="🔔 通知")

        sbar = ttk.Frame(tab)
        sbar.pack(fill="x", pady=(0, 8))
        self.notify_all = tk.BooleanVar(value=False)
        ttk.Checkbutton(sbar, text="包含已读", variable=self.notify_all, command=self.load_notifications).pack(
            side="left")
        ttk.Button(sbar, text="🔄 刷新", command=self.load_notifications).pack(side="left", padx=(10, 0))
        ttk.Button(sbar, text="标记已读", command=self.mark_notify_read).pack(side="right")

        self.notify_tree = self._make_tree(
            tab, "notify_tree", cols=("repo", "reason", "title", "type", "updated"),
            heads=("仓库", "原因", "标题", "类型", "时间"), widths=(300, 140, 420, 120, 170))
        self.notify_tree.bind("<Double-1>", self.open_notification)
        self._notif_map = {}

    def load_notifications(self):
        self._gen_notifs += 1
        gen = self._gen_notifs
        self._tree_set_state(self.notify_tree, "loading", "加载中…")

        def ok(items):
            if gen != self._gen_notifs: return
            for iid in self.notify_tree.get_children():
                if str(iid).startswith("__state__"): self.notify_tree.delete(iid)
            self._notif_map.clear()
            self.notify_tree.delete(*self.notify_tree.get_children())

            if not items: self._tree_set_state(self.notify_tree, "empty", "无未读通知")

            for i, n in enumerate(items):
                nid = str(n["id"])
                self._notif_map[nid] = n
                unread = n.get("unread") is not False
                prefix = "● " if unread else ""
                self.notify_tree.insert("", "end", iid=nid, values=(
                    n["repository"]["full_name"], n.get("reason", ""),
                    prefix + n["subject"]["title"], n["subject"].get("type", ""),
                    _rel_time(n["updated_at"])), tags=("odd",) if i % 2 else ("even",))
            self._status(f"通知 {len(items)} 条")

        self.run_async(lambda: self.api.list_notifications(all_=self.notify_all.get()), ok)

    def mark_notify_read(self):
        sel = self.notify_tree.selection()
        if not sel or str(sel[0]).startswith("__state__"): return
        nid = sel[0]

        def done(_):
            self._status("已标记已读")
            self.load_notifications()

        self.run_async(lambda: self.api.mark_notification_read(nid), done)

    def open_notification(self, _e):
        sel = self.notify_tree.selection()
        if not sel or str(sel[0]).startswith("__state__"): return
        n = self._notif_map.get(sel[0])
        if not n: return
        url = (n["subject"].get("url") or "").replace("api.github.com/repos", "github.com").replace("/pulls/", "/pull/")
        if url: webbrowser.open(url)

    # ---------- Starred ----------
    def _build_star_tab(self, nb):
        tab = ttk.Frame(nb, padding=14)
        nb.add(tab, text="⭐ Starred")
        sbar = ttk.Frame(tab)
        sbar.pack(fill="x", pady=(0, 8))
        ttk.Button(sbar, text="🔄 加载 Starred", command=self.load_starred).pack(side="left")
        ttk.Button(sbar, text="⬇️ 下一页", command=lambda: self.load_starred(next_page=True)).pack(side="right")
        self.star_tree = self._make_tree(
            tab, "star_tree", cols=("name", "stars", "lang", "desc"),
            heads=("仓库", "星标", "语言", "描述"), widths=(340, 80, 130, 560))
        self.star_tree.bind("<Double-1>", lambda _e: self._show_detail_for(self.star_tree))
        ttk.Button(tab, text="❌ 取消 Star", command=self.unstar_selected).pack(anchor="w", pady=(10, 0))

    def load_starred(self, next_page=False):
        if not self.api: return
        if next_page:
            self.star_page += 1
        else:
            self.star_page = 1
            self.star_tree.delete(*self.star_tree.get_children())
            self._tree_set_state(self.star_tree, "loading", "加载中…")
        page = self.star_page
        self._gen_star += 1
        gen = self._gen_star

        def ok(items):
            if gen != self._gen_star: return
            for iid in self.star_tree.get_children():
                if str(iid).startswith("__state__"): self.star_tree.delete(iid)

            if not items and page == 1:
                self._tree_set_state(self.star_tree, "empty", "暂无 Starred 仓库")
                return

            for i, r in enumerate(items):
                desc = (r.get("description") or "—").replace("\n", " ")[:72]
                if not self.star_tree.exists(r["full_name"]):
                    self.star_tree.insert("", "end", iid=r["full_name"],
                                          values=(
                                              r["full_name"], r["stargazers_count"], r.get("language") or "—", desc),
                                          tags=("odd",) if i % 2 else ("even",))
            self._status(f"已加载第 {page} 页 starred")

        self.run_async(lambda: self.api.list_starred(page=page), ok)

    def unstar_selected(self):
        sel = self.star_tree.selection()
        if not sel or str(sel[0]).startswith("__state__"): return
        repo = sel[0]

        def done(_):
            self._status(f"已取消 Star：{repo}")
            try:
                self.star_tree.delete(repo)
            except Exception:
                pass

        self.run_async(lambda: self.api.unstar(repo), done)

    # ---------- 详情 / 下载 ----------
    def _show_detail_for(self, tree):
        iid = self._selected(tree)
        if not iid or str(iid).startswith("__state__"):
            messagebox.showinfo("提示", "先在列表中选中一个仓库")
            return
        repo = self._extract_repo(iid)
        if not REPO_RE.match(repo):
            messagebox.showinfo("提示", "请选择一个仓库")
            return
        self.cfg.add_recent_repo(repo)
        self._refresh_repo_switch()
        cached = self._repo_cache.get(repo)
        if cached and "owner" in cached:
            RepoDetailWindow(self, repo, cached)
            return

        def ok(data):
            self._repo_cache[repo] = data
            RepoDetailWindow(self, repo, data)

        self.run_async(lambda: self.api.get_repo(repo), ok)

    def _open_repo_detail(self, repo):
        self.cfg.add_recent_repo(repo)
        self._refresh_repo_switch()
        cached = self._repo_cache.get(repo)
        if cached and "owner" in cached:
            RepoDetailWindow(self, repo, cached)
            return

        def ok(data):
            self._repo_cache[repo] = data
            RepoDetailWindow(self, repo, data)

        self.run_async(lambda: self.api.get_repo(repo), ok)

    def _initial_dir(self):
        d = self.cfg.last_dir
        return d if d and os.path.isdir(d) else os.path.expanduser("~")

    def _remember_dir(self, dest):
        self.cfg.last_dir = dest
        self.cfg.save()

    def _zip_for_repo_tab(self):
        self._run_zip(self.repo_tree, self.progress, [self.zip_btn, self.clone_btn, self.pull_btn, self.detail_btn])

    def _zip_for_search_tab(self):
        self._run_zip(self.search_tree, self.search_progress,
                      [self.search_zip_btn, self.search_clone_btn, self.search_detail_btn])

    def _clone_for_repo_tab(self):
        self._run_clone(self.repo_tree, self.progress, [self.zip_btn, self.clone_btn, self.pull_btn, self.detail_btn])

    def _clone_for_search_tab(self):
        self._run_clone(self.search_tree, self.search_progress,
                        [self.search_zip_btn, self.search_clone_btn, self.search_detail_btn])

    def _pull_for_repo_tab(self):
        iid = self._selected(self.repo_tree)
        if not iid or str(iid).startswith("__state__"):
            messagebox.showinfo("提示", "先选中一个仓库")
            return
        repo = self._extract_repo(iid)
        local = self._local_repo_path(repo)
        if not local:
            if messagebox.askyesno("未找到本地仓库", "未在下载目录找到 .git。\n是否 clone？"):
                self._clone_for_repo_tab()
            return

        def ok(out):
            self._status(f"git pull 完成：{local}")
            messagebox.showinfo("完成", f"{local}\n\n{out[-1500:]}")

        self.run_async(lambda: self.api.pull_repo(local), ok)

    def _run_zip(self, tree, progress, buttons):
        iid = self._selected(tree)
        if not iid or str(iid).startswith("__state__"):
            messagebox.showinfo("提示", "先选中一个仓库")
            return
        repo = self._extract_repo(iid)
        dest = filedialog.askdirectory(title="选择保存目录", initialdir=self._initial_dir())
        if not dest: return
        progress.stop()
        progress.configure(mode="determinate", value=0)
        if not progress.winfo_ismapped(): progress.pack(fill="x", pady=(12, 0))
        self._busy_do(buttons,
                      lambda: self.api.download_zip(repo, dest, on_progress=lambda p: self.after(0, lambda
                          v=p: progress.configure(value=v * 100))),
                      lambda path: self._dl_done(path, progress, dest),
                      lambda e: self._dl_fail(e, progress))

    def _run_clone(self, tree, progress, buttons):
        iid = self._selected(tree)
        if not iid or str(iid).startswith("__state__"):
            messagebox.showinfo("提示", "先选中一个仓库")
            return
        repo = self._extract_repo(iid)
        dest = filedialog.askdirectory(title="选择克隆目录", initialdir=self._initial_dir())
        if not dest: return
        progress.stop()
        progress.configure(mode="determinate", value=0)
        if not progress.winfo_ismapped(): progress.pack(fill="x", pady=(12, 0))

        def on_progress(p, line):
            self.after(0, lambda: progress.configure(value=p * 100))

        self._busy_do(buttons,
                      lambda: self.api.clone_repo(repo, dest, on_progress=on_progress),
                      lambda path: self._dl_done(path, progress, dest),
                      lambda e: self._dl_fail(e, progress))

    def _dl_done(self, path, progress, dest):
        progress.stop()
        progress.configure(mode="determinate", value=0)
        progress.pack_forget()
        self._remember_dir(dest)
        self._status(f"已保存到 {path}")
        messagebox.showinfo("完成", f"已保存：\n{path}")

    def _dl_fail(self, e, progress):
        progress.stop()
        progress.configure(mode="determinate", value=0)
        progress.pack_forget()
        self._err(e)

    def _download_installer_for_repo_tab(self):
        iid = self._selected(self.repo_tree)
        if not iid or str(iid).startswith("__state__"):
            messagebox.showinfo("提示", "先选中一个仓库")
            return
        self._download_latest_release(self._extract_repo(iid))

    def _download_installer_for_search_tab(self):
        iid = self._selected(self.search_tree)
        if not iid or str(iid).startswith("__state__"):
            messagebox.showinfo("提示", "先选中一个仓库")
            return
        self._download_latest_release(self._extract_repo(iid))

    def _download_latest_release(self, repo):
        def got(rel):
            assets = rel.get("assets") or []
            if not assets:
                messagebox.showinfo("提示", f"{repo} 最新 Release 无安装包")
                return
            dest = filedialog.askdirectory(title="选择保存目录", initialdir=self._initial_dir())
            if not dest: return
            for a in assets: self._enqueue_download(repo, a, dest)
            self._status(f"{repo}：{len(assets)} 个文件已加入下载队列")

        def err(e):
            messagebox.showinfo("提示", f"{repo} 无可用 Release：{e}")

        self.run_async(lambda: self.api.get_latest_release(repo), got, err)

    # ---------- 通知轮询 ----------
    def _schedule_poll(self):
        if self._poll_after:
            try:
                self.after_cancel(self._poll_after)
            except Exception:
                pass
            self._poll_after = None
        interval = max(0, int(self.cfg.poll_interval or 0))
        if interval <= 0 or not self.api: return
        self._poll_after = self.after(interval * 1000, self._poll_notifications)

    def _poll_notifications(self):
        self._poll_after = None
        if not self.api: return

        def ok(items):
            items = [n for n in items if n["repository"]["full_name"] not in self.cfg.muted_repos]
            unread = sum(1 for n in items if n.get("unread") is not False)
            self._update_tray_badge(unread)
            if unread > self._last_unread:
                notify_desktop("GitHub 客户端", f"收到 {unread} 条未读通知")
            self._last_unread = unread
            self._schedule_poll()

        def err(_e):
            self._schedule_poll()

        self.run_async(lambda: self.api.list_notifications(), ok, err)

    def _update_tray_badge(self, unread):
        icon = getattr(self, "_tray_icon", None)
        if icon is None: return
        try:
            icon.title = (f"GitHub 客户端 · {unread} 条未读" if unread else "GitHub 客户端")
        except Exception:
            pass
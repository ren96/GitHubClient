import queue
import threading
import time
import tkinter as tk
from tkinter import ttk
from utils import reveal_in_folder, _fmt_bytes


class DownloadTask:
    def __init__(self, name, repo, asset, dest, progress_cb=None):
        self.name = name
        self.repo = repo
        self.asset = asset
        self.dest = dest
        self.progress = 0.0
        self.status = "等待中"  # 等待中 / 下载中 / 暂停 / 失败 / 完成
        self.error = ""
        self.path = ""
        self.size = asset.get("size", 0)
        self.progress_cb = progress_cb


class DownloadQueueWindow(tk.Toplevel):
    """独立下载队列窗口，支持暂停、继续、重试"""

    def __init__(self, app):
        super().__init__(app)
        self.app = app
        self.title("下载队列")
        self.geometry("760x480")
        self.transient(app)
        try:
            self.iconbitmap(app.icon_path)
        except Exception:
            pass

        self.tasks: list[DownloadTask] = []
        self._lock = threading.Lock()
        self._stop = False
        self._paused = False
        self._refresh_q: "queue.Queue[None]" = queue.Queue()

        f = ttk.Frame(self, padding=12)
        f.pack(fill="both", expand=True)
        top = ttk.Frame(f)
        top.pack(fill="x", pady=(0, 8))

        self.btn_pause = ttk.Button(top, text="⏸ 暂停全部", command=self._toggle_pause)
        self.btn_pause.pack(side="left")
        ttk.Button(top, text="🔄 重试全部失败", command=self._retry_failed).pack(side="left", padx=(6, 0))
        ttk.Button(top, text="🗑 清空已完成", command=self._clear_done).pack(side="left", padx=(6, 0))

        body = ttk.Frame(f)
        body.pack(fill="both", expand=True)
        self.tree = ttk.Treeview(
            body, columns=("name", "size", "status", "progress", "error"),
            show="headings")
        for c, h, w in [("name", "文件名", 260), ("size", "大小", 80),
                        ("status", "状态", 100), ("progress", "进度", 100), ("error", "错误", 160)]:
            self.tree.heading(c, text=h)
            self.tree.column(c, width=w, anchor="w")
        vs = ttk.Scrollbar(body, orient="vertical", command=self.tree.yview)
        self.tree.configure(yscrollcommand=vs.set)
        self.tree.pack(side="left", fill="both", expand=True)
        vs.pack(side="right", fill="y")
        try:
            app._tag_tree(self.tree)
        except Exception:
            pass
        self.tree.bind("<Double-1>", self._on_double_click)

        self.protocol("WM_DELETE_WINDOW", self._on_close)
        threading.Thread(target=self._run, daemon=True).start()
        self._poll_refresh()

    # ---- 生命周期 ----
    def _on_close(self):
        self._stop = True
        try:
            self.destroy()
        except tk.TclError:
            pass

    def _poll_refresh(self):
        if self._stop:
            return
        try:
            while True:
                self._refresh_q.get_nowait()
                self._refresh()
        except queue.Empty:
            pass
        try:
            self.after(200, self._poll_refresh)
        except tk.TclError:
            return

    def _schedule_refresh(self):
        self._refresh_q.put(None)

    # ---- 外部 API ----
    def add(self, task: DownloadTask):
        with self._lock:
            self.tasks.append(task)
        self._schedule_refresh()

    # ---- UI ----
    def _toggle_pause(self):
        self._paused = not self._paused
        self.btn_pause.configure(text="▶ 继续全部" if self._paused else "⏸ 暂停全部")
        self._schedule_refresh()

    def _on_double_click(self, _e):
        sel = self.tree.selection()
        if not sel:
            return
        try:
            idx = int(sel[0])
            with self._lock:
                if idx < len(self.tasks):
                    t = self.tasks[idx]
                    if t.status == "完成" and t.path:
                        reveal_in_folder(t.path)
        except Exception:
            pass

    def _refresh(self):
        try:
            if not self.winfo_exists():
                return
        except tk.TclError:
            return
        try:
            self.tree.delete(*self.tree.get_children())
            with self._lock:
                tasks_snapshot = list(self.tasks)

            for i, t in enumerate(tasks_snapshot):
                size_str = _fmt_bytes(t.size) if t.size else "-"
                self.tree.insert("", "end", iid=str(i), values=(
                    t.name, size_str, t.status, f"{int(t.progress * 100)}%", t.error,
                ), tags=("odd",) if i % 2 else ("even",))
        except tk.TclError:
            pass

    # ---- 调度 ----
    def _next(self):
        with self._lock:
            for t in self.tasks:
                if t.status == "等待中":
                    return t
        return None

    def _run(self):
        while not self._stop:
            if self._paused:
                time.sleep(0.5)
                continue
            t = self._next()
            if not t:
                time.sleep(0.4)
                continue

            with self._lock:
                t.status = "下载中"
                t.error = ""
            self._schedule_refresh()

            def _prog(p, task=t):
                with self._lock:
                    task.progress = p
                self._schedule_refresh()

            try:
                if self.app.api is None:
                    raise RuntimeError("未登录")
                path = self.app.api.download_asset(
                    t.repo, t.asset, t.dest, on_progress=_prog)
                with self._lock:
                    t.status = "完成"
                    t.progress = 1.0
                    t.path = path
            except Exception as e:
                with self._lock:
                    t.status = "失败"
                    t.error = str(e)[:100]
            self._schedule_refresh()

    def _retry_failed(self):
        with self._lock:
            for t in self.tasks:
                if t.status == "失败":
                    t.status = "等待中"
                    t.progress = 0.0
                    t.error = ""
        self._schedule_refresh()

    def _clear_done(self):
        with self._lock:
            self.tasks = [t for t in self.tasks if t.status != "完成"]
        self._schedule_refresh()
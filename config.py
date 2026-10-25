import os
import json
import logging
import threading
import time
import sqlite3
from typing import Optional
from utils import _config_dir

try:
    import keyring
    from keyring.backends.fail import Keyring as _FailKeyring
    KEYRING_OK = not isinstance(keyring.get_keyring(), _FailKeyring)
except Exception:
    keyring = None
    KEYRING_OK = False


class ConfigStore:
    FILENAME = "config.json"
    SERVICE = "github-desktop-client"

    def __init__(self):
        self.dir = _config_dir()
        self.path = os.path.join(self.dir, self.FILENAME)
        self.profiles: list[str] = []
        self.current: Optional[str] = None
        self.remember = False
        self.last_dir: Optional[str] = None
        self.proxy = ""
        self.theme = "auto"
        self.oauth_client_id = ""
        self.poll_interval = 60
        # 新增
        self.geometry = ""
        self.col_widths: dict = {}
        self.search_history: list[str] = []
        self.font_size = 10
        self.last_tab = 0
        self.recent_repos: list[str] = []
        self.favorites: list[dict] = []   # [{"repo": str, "note": str, "ts": float}]
        self.muted_repos: list[str] = []
        self.theme_colors: dict = {}
        # ---- 自动更新 ----
        self.update_repo = ""
        self.update_channel = "stable"        # stable / beta
        self.auto_check_update = True
        self.skipped_version = ""
        self._tokens_in_file: dict[str, str] = {}
        self._load()

    def _load(self):
        try:
            with open(self.path, "r", encoding="utf-8") as f:
                data = json.load(f)
        except (OSError, ValueError):
            return
        self.profiles = data.get("profiles", []) or []
        self.current = data.get("current")
        self.remember = bool(data.get("remember", False))
        self.last_dir = data.get("last_dir") or None
        self.proxy = data.get("proxy", "")
        self.theme = data.get("theme", "auto")
        self.oauth_client_id = data.get("oauth_client_id", "")
        try:
            self.poll_interval = int(data.get("poll_interval", 60) or 60)
        except (ValueError, TypeError):
            self.poll_interval = 60
        self.geometry = data.get("geometry", "") or ""
        self.col_widths = data.get("col_widths", {}) or {}
        self.search_history = data.get("search_history", []) or []
        try:
            self.font_size = int(data.get("font_size", 10) or 10)
        except (ValueError, TypeError):
            self.font_size = 10
        self.font_size = max(8, min(16, self.font_size))
        try:
            self.last_tab = int(data.get("last_tab", 0) or 0)
        except (ValueError, TypeError):
            self.last_tab = 0
        self.recent_repos = data.get("recent_repos", []) or []
        self.favorites = data.get("favorites", []) or []
        self.muted_repos = data.get("muted_repos", []) or []
        self.theme_colors = data.get("theme_colors", {}) or {}
        self._tokens_in_file = data.get("tokens", {}) or {}
        # ---- 自动更新 ----
        self.update_repo = data.get("update_repo", "") or ""
        self.update_channel = data.get("update_channel", "stable") or "stable"
        self.auto_check_update = bool(data.get("auto_check_update", True))
        self.skipped_version = data.get("skipped_version", "") or ""

    def save(self) -> bool:
        data = {
            "profiles": self.profiles, "current": self.current,
            "remember": self.remember, "last_dir": self.last_dir,
            "proxy": self.proxy, "theme": self.theme,
            "oauth_client_id": self.oauth_client_id,
            "poll_interval": self.poll_interval,
            "geometry": self.geometry,
            "col_widths": self.col_widths,
            "search_history": self.search_history[-30:],
            "font_size": self.font_size,
            "last_tab": self.last_tab,
            "recent_repos": self.recent_repos[-30:],
            "favorites": self.favorites,
            "muted_repos": self.muted_repos,
            "theme_colors": self.theme_colors,
            "tokens": self._tokens_in_file,
            # ---- 自动更新 ----
            "update_repo": self.update_repo,
            "update_channel": self.update_channel,
            "auto_check_update": self.auto_check_update,
            "skipped_version": self.skipped_version,
        }
        try:
            os.makedirs(self.dir, exist_ok=True)
            tmp = self.path + ".tmp"
            with open(tmp, "w", encoding="utf-8") as f:
                json.dump(data, f, ensure_ascii=False, indent=2)
            try:
                os.chmod(tmp, 0o600)
            except OSError:
                pass
            os.replace(tmp, self.path)
            return True
        except OSError as e:
            logging.warning("保存配置失败：%s", e)
            return False

    def get_token(self, username: str) -> Optional[str]:
        if KEYRING_OK:
            try:
                t = keyring.get_password(self.SERVICE, username)
                if t:
                    return t
            except Exception:
                pass
        return self._tokens_in_file.get(username)

    def save_token(self, username: str, token: str):
        if username not in self.profiles:
            self.profiles.append(username)
        if KEYRING_OK:
            try:
                keyring.set_password(self.SERVICE, username, token)
                self._tokens_in_file.pop(username, None)
                self.save()
                return
            except Exception:
                pass
        self._tokens_in_file[username] = token
        self.save()

    def remove_profile(self, username: str):
        if KEYRING_OK:
            try:
                keyring.delete_password(self.SERVICE, username)
            except Exception:
                pass
        self._tokens_in_file.pop(username, None)
        if username in self.profiles:
            self.profiles.remove(username)
        if self.current == username:
            self.current = self.profiles[0] if self.profiles else None
        self.save()

    # ---------- 收藏 / 最近 / 静音 ----------
    def add_favorite(self, repo: str, note: str = ""):
        for f in self.favorites:
            if f.get("repo") == repo:
                f["note"] = note
                f["ts"] = time.time()
                self.save()
                return
        self.favorites.append({"repo": repo, "note": note, "ts": time.time()})
        self.save()

    def remove_favorite(self, repo: str):
        self.favorites = [f for f in self.favorites if f.get("repo") != repo]
        self.save()

    def is_favorite(self, repo: str) -> bool:
        return any(f.get("repo") == repo for f in self.favorites)

    def add_recent_repo(self, repo: str):
        if repo in self.recent_repos:
            self.recent_repos.remove(repo)
        self.recent_repos.append(repo)
        self.recent_repos = self.recent_repos[-30:]
        self.save()

    def toggle_mute(self, repo: str):
        if repo in self.muted_repos:
            self.muted_repos.remove(repo)
        else:
            self.muted_repos.append(repo)
        self.save()

    def add_search_history(self, q: str):
        if not q:
            return
        if q in self.search_history:
            self.search_history.remove(q)
        self.search_history.append(q)
        self.search_history = self.search_history[-30:]
        self.save()


class Cache:
    """SQLite 缓存，使用线程本地连接 + WAL 以降低连接开销。"""

    def __init__(self):
        self.dir = _config_dir()
        os.makedirs(self.dir, exist_ok=True)
        self.path = os.path.join(self.dir, "cache.db")
        self._local = threading.local()
        self._init_db()

    def _conn(self):
        con = getattr(self._local, "con", None)
        if con is None:
            con = sqlite3.connect(self.path, timeout=10, check_same_thread=False)
            try:
                con.execute("PRAGMA journal_mode=WAL")
                con.execute("PRAGMA synchronous=NORMAL")
            except Exception:
                pass
            self._local.con = con
        return con

    def _init_db(self):
        try:
            con = self._conn()
            con.execute(
                "CREATE TABLE IF NOT EXISTS kv (k TEXT PRIMARY KEY, v TEXT, t REAL)")
            con.commit()
        except Exception:
            pass

    def get(self, key: str, max_age: int = 600):
        try:
            row = self._conn().execute(
                "SELECT v, t FROM kv WHERE k=?", (key,)).fetchone()
            if not row:
                return None
            v, t = row
            if max_age > 0 and time.time() - t > max_age:
                return None
            return json.loads(v)
        except Exception:
            return None

    def set(self, key: str, value):
        try:
            con = self._conn()
            with con:
                con.execute(
                    "INSERT OR REPLACE INTO kv VALUES (?, ?, ?)",
                    (key, json.dumps(value, default=str), time.time()))
        except Exception:
            pass

    def delete(self, key: str):
        try:
            con = self._conn()
            with con:
                con.execute("DELETE FROM kv WHERE k=?", (key,))
        except Exception:
            pass
import os
import sys
import time
import logging
import re
import subprocess


def get_base_dir():
    # ---- 修复：PyInstaller 打包后资源位于 _MEIPASS ----
    # - onefile 模式：解压到临时目录 sys._MEIPASS
    # - onedir 模式（PyInstaller 6.x）：datas 位于 _internal，_MEIPASS 也指向它
    # - 开发模式：__file__ 所在目录
    if getattr(sys, "frozen", False):
        meipass = getattr(sys, "_MEIPASS", None)
        if meipass:
            return meipass
        return os.path.dirname(sys.executable)
    return os.path.dirname(os.path.abspath(__file__))


def _config_dir() -> str:
    if os.name == "nt":
        base = os.environ.get("APPDATA") or os.path.expanduser("~")
    elif sys.platform == "darwin":
        base = os.path.expanduser("~/Library/Application Support")
    else:
        base = os.environ.get("XDG_CONFIG_HOME") or os.path.expanduser("~/.config")
    return os.path.join(base, "github-client")


def _setup_logging():
    try:
        d = _config_dir()
        os.makedirs(d, exist_ok=True)
        logging.basicConfig(
            filename=os.path.join(d, "app.log"),
            level=logging.INFO,
            format="%(asctime)s [%(levelname)s] %(message)s",
        )
    except Exception:
        logging.basicConfig(level=logging.INFO)


def _fmt_time(s: str) -> str:
    if not s:
        return ""
    s = s.strip()
    from datetime import datetime
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is not None:
            dt = dt.astimezone()
        return dt.strftime("%Y-%m-%d %H:%M")
    except (ValueError, TypeError):
        pass
    for fmt in ("%Y-%m-%dT%H:%M:%SZ", "%Y-%m-%dT%H:%M:%S.%fZ"):
        try:
            return time.strftime("%Y-%m-%d %H:%M", time.strptime(s, fmt))
        except (ValueError, TypeError):
            continue
    return s[:19].replace("T", " ")


def _rel_time(s: str) -> str:
    """用 datetime 精准计算相对时间，避免 time.mktime 的时区误差。"""
    if not s:
        return ""
    from datetime import datetime, timezone
    try:
        dt = datetime.fromisoformat(s.replace("Z", "+00:00"))
        if dt.tzinfo is None:
            dt = dt.replace(tzinfo=timezone.utc)
        now = datetime.now(timezone.utc)
        diff = (now - dt).total_seconds()
    except (ValueError, TypeError):
        return _fmt_time(s)

    if diff < 0:
        return "刚刚"
    if diff < 60:
        return "刚刚"
    if diff < 3600:
        return f"{int(diff // 60)} 分钟前"
    if diff < 86400:
        return f"{int(diff // 3600)} 小时前"
    if diff < 86400 * 30:
        return f"{int(diff // 86400)} 天前"
    if diff < 86400 * 365:
        return f"{int(diff // (86400 * 30))} 个月前"
    return _fmt_time(s)[:10]


def _fmt_bytes(n) -> str:
    try:
        n = float(n)
    except (TypeError, ValueError):
        return "?"
    for unit in ("B", "KB", "MB", "GB", "TB"):
        if n < 1024:
            return f"{int(n)} B" if unit == "B" else f"{n:.1f} {unit}"
        n /= 1024
    return f"{n:.1f} PB"


class RateLimitError(RuntimeError):
    def __init__(self, reset_at: int):
        self.reset_at = reset_at
        wait = max(0, reset_at - int(time.time()))
        super().__init__(f"API 限流，请等待 {wait} 秒后再试")


def set_windows_app_id():
    if sys.platform == "win32":
        import ctypes
        try:
            ctypes.windll.shell32.SetCurrentProcessExplicitAppUserModelID(
                "github.desktop.client.1.0")
        except Exception:
            pass


def detect_system_theme() -> str:
    try:
        if sys.platform == "win32":
            import winreg
            key = winreg.OpenKey(
                winreg.HKEY_CURRENT_USER,
                r"Software\Microsoft\Windows\CurrentVersion\Themes\Personalize")
            val, _ = winreg.QueryValueEx(key, "AppsUseLightTheme")
            return "light" if val else "dark"
        if sys.platform == "darwin":
            r = subprocess.run(["defaults", "read", "-g", "AppleInterfaceStyle"],
                               capture_output=True, text=True)
            return "dark" if "Dark" in r.stdout else "light"
        r = subprocess.run(
            ["gsettings", "get", "org.gnome.desktop.interface", "color-scheme"],
            capture_output=True, text=True)
        if "dark" in r.stdout.lower():
            return "dark"
    except Exception:
        pass
    return "light"


def open_path_in_os(path: str):
    if not path or not os.path.exists(path):
        raise RuntimeError(f"路径不存在：{path}")
    if sys.platform == "win32":
        os.startfile(path)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", path])
    else:
        subprocess.Popen(["xdg-open", path])


def open_in_vscode(path: str):
    try:
        subprocess.Popen(["code", path], shell=(sys.platform == "win32"))
    except FileNotFoundError:
        raise RuntimeError("未找到 code 命令，请确认已安装 VS Code 并加入 PATH")


def open_terminal(path: str):
    if sys.platform == "win32":
        try:
            subprocess.Popen(["wt", "-d", path])
            return
        except FileNotFoundError:
            pass
        subprocess.Popen(f'start cmd /k "cd /d {path}"', shell=True)
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-a", "Terminal", path])
    else:
        for term in ("gnome-terminal", "konsole", "xterm"):
            try:
                subprocess.Popen([term, "--working-directory", path])
                return
            except FileNotFoundError:
                continue
        raise RuntimeError("未找到可用的终端")


def reveal_in_folder(path: str):
    """在系统文件管理器中定位文件/文件夹"""
    path = os.path.abspath(path)
    if sys.platform == "win32":
        if os.path.isdir(path):
            os.startfile(path)
        else:
            subprocess.Popen(["explorer", "/select,", path])
    elif sys.platform == "darwin":
        subprocess.Popen(["open", "-R", path])
    else:
        parent = path if os.path.isdir(path) else os.path.dirname(path)
        subprocess.Popen(["xdg-open", parent])


def md_fix_relative_images(html: str, repo: str, ref: str) -> str:
    base = f"https://raw.githubusercontent.com/{repo}/{ref}/"

    def _repl(m):
        src = m.group(1)
        if re.match(r"^[a-z]+://", src) or src.startswith("//") or src.startswith("data:"):
            return m.group(0)
        if src.startswith("./"):
            src = src[2:]
        if src.startswith("/"):
            src = src[1:]
        return f'src="{base}{src}"'

    return re.sub(r'src="([^"]+)"', _repl, html)


def get_avatar_cache_dir() -> str:
    d = os.path.join(_config_dir(), "avatars")
    os.makedirs(d, exist_ok=True)
    return d


def notify_desktop(title: str, msg: str):
    """跨平台桌面通知，纯原生实现，无第三方依赖，异步非阻塞。"""
    try:
        if sys.platform == "win32":
            env = os.environ.copy()
            env["GH_NOTIFY_TITLE"] = title
            env["GH_NOTIFY_MSG"] = msg
            ps_script = """
            $ErrorActionPreference = 'SilentlyContinue'
            [Windows.UI.Notifications.ToastNotificationManager, Windows.UI.Notifications, ContentType=WindowsRuntime] | Out-Null
            $template = [Windows.UI.Notifications.ToastNotificationManager]::GetTemplateContent([Windows.UI.Notifications.ToastTemplateType]::ToastText02)
            $textNodes = $template.GetElementsByTagName('text')
            $textNodes.Item(0).AppendChild($template.CreateTextNode($env:GH_NOTIFY_TITLE)) | Out-Null
            $textNodes.Item(1).AppendChild($template.CreateTextNode($env:GH_NOTIFY_MSG)) | Out-Null
            $toast = [Windows.UI.Notifications.ToastNotification]::new($template)
            [Windows.UI.Notifications.ToastNotificationManager]::CreateToastNotifier('GitHub 客户端').Show($toast)
            """
            subprocess.Popen(
                ["powershell", "-NoProfile", "-ExecutionPolicy", "Bypass", "-Command", ps_script],
                env=env,
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL,
            )

        elif sys.platform == "darwin":
            apple_script = 'on run argv\n display notification (item 1 of argv) with title (item 2 of argv)\nend run'
            subprocess.Popen(
                ["osascript", "-e", apple_script, msg, title],
                stdout=subprocess.DEVNULL,
                stderr=subprocess.DEVNULL
            )

        else:
            try:
                subprocess.Popen(["notify-send", title, msg],
                                 stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
            except FileNotFoundError:
                try:
                    subprocess.Popen(["zenity", "--info", "--title", title, "--text", msg],
                                     stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                except FileNotFoundError:
                    try:
                        subprocess.Popen(["kdialog", "--title", title, "--msgbox", msg],
                                         stdout=subprocess.DEVNULL, stderr=subprocess.DEVNULL)
                    except FileNotFoundError:
                        logging.warning("Linux 下未找到任何可用的通知程序 (notify-send / zenity / kdialog)")
    except Exception as e:
        logging.warning(f"发送桌面通知失败: {e}")
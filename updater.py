"""自动更新检查 / 下载 / 安装。

设计思路：
- 通过 GitHub Release 分发新版本（tag 即版本号，形如 v1.2.0 或 1.2.0-beta）
- 支持 stable / beta 双通道
- 下载完成后调用 apply_update() 启动安装程序；无法直接启动则打开所在目录
"""

from __future__ import annotations

import logging
import os
import re
import subprocess
import sys
from typing import Iterable, Optional

from api import GitHubAPI


# ---------- 版本解析 ----------
_VERSION_RE = re.compile(r"(\d+)\.(\d+)\.(\d+)(?:[-.]([0-9A-Za-z.\-]+))?")


def parse_version(text: str) -> tuple[tuple[int, int, int], str]:
    """把 tag / 版本号解析成 ((major, minor, patch), prerelease)。

    允许前缀（如 "v1.2.0"、"release-1.2.0"），取第一组 x.y.z。
    """
    m = _VERSION_RE.search(text or "")
    if not m:
        return (0, 0, 0), ""
    major, minor, patch = int(m.group(1)), int(m.group(2)), int(m.group(3))
    pre = (m.group(4) or "").lower()
    return (major, minor, patch), pre


def normalize_version(text: str) -> str:
    tup, pre = parse_version(text)
    v = ".".join(str(x) for x in tup)
    if pre:
        v += "-" + pre
    return v


def is_newer(latest: str, current: str) -> bool:
    """latest 是否比 current 新（semver 语义：1.2.0 > 1.2.0-beta）。"""
    a, ap = parse_version(latest)
    b, bp = parse_version(current)
    if a != b:
        return a > b
    if ap and not bp:
        return False
    if not ap and bp:
        return True
    return ap > bp


# ---------- Release 信息 ----------
class ReleaseInfo:
    def __init__(self, data: dict):
        self.raw = data
        self.tag = data.get("tag_name", "") or ""
        self.name = data.get("name") or self.tag
        self.body = data.get("body") or ""
        self.html_url = data.get("html_url") or ""
        self.published_at = data.get("published_at") or ""
        self.assets = data.get("assets") or []
        self.prerelease = bool(data.get("prerelease"))
        self.draft = bool(data.get("draft"))
        self.version = normalize_version(self.tag)

    def __repr__(self):
        return f"<ReleaseInfo {self.version} assets={len(self.assets)}>"


# ---------- 检查 ----------
def check_for_update(
    api: GitHubAPI,
    repo: str,
    current_version: str,
    include_prerelease: bool = False,
) -> Optional[ReleaseInfo]:
    """返回可用的新版本；已是最新则返回 None。

    - repo 为空 → 直接 None
    - 仓库 / Release 不存在（HTTP 404）→ 视为无更新
    - 其他错误（网络 / 限流 / 权限）→ 原样抛出
    """
    if not repo:
        return None

    try:
        if not include_prerelease:
            data = api.get_latest_release(repo)
            info = ReleaseInfo(data)
            return info if is_newer(info.version, current_version) else None

        releases = api.list_releases(repo) or []
        for r in releases:
            if r.get("draft"):
                continue
            info = ReleaseInfo(r)
            if is_newer(info.version, current_version):
                return info
        return None
    except RuntimeError as e:
        if "HTTP 404" in str(e):
            return None
        raise


# ---------- 资产挑选 ----------
def _platform_exts() -> tuple[str, ...]:
    if sys.platform == "win32":
        return (".exe", ".msi")
    if sys.platform == "darwin":
        return (".dmg", ".pkg")
    return (".appimage", ".deb", ".rpm")


def pick_asset(assets: Iterable[dict], channel: str = "stable") -> Optional[dict]:
    """挑选适合当前平台的安装包。"""
    exts = _platform_exts()
    matches = []
    for a in assets or []:
        name = (a.get("name") or "").lower()
        if any(name.endswith(e) for e in exts):
            matches.append(a)
    if not matches:
        return None
    if channel == "stable":
        stable = [
            a for a in matches
            if not any(k in (a.get("name") or "").lower()
                       for k in ("beta", "alpha", "rc", "preview", "pre", "dev"))
        ]
        if stable:
            return stable[0]
    return matches[0]


# ---------- 安装 ----------
def apply_update(path: str) -> None:
    """启动安装程序；无法直接启动则用系统默认程序打开。"""
    path = os.path.abspath(path)
    if not os.path.exists(path):
        raise RuntimeError(f"文件不存在：{path}")

    if sys.platform == "win32":
        os.startfile(path)  # type: ignore[attr-defined]
        return
    if sys.platform == "darwin":
        subprocess.Popen(["open", path])
        return

    # Linux
    lower = path.lower()
    if lower.endswith(".appimage"):
        try:
            os.chmod(path, 0o755)
        except OSError:
            pass
        subprocess.Popen([path])
        return
    subprocess.Popen(["xdg-open", path])
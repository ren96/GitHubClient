import base64
import json
import os
import re
import subprocess
import time
import zipfile
from urllib.parse import quote

import requests
from utils import RateLimitError

API = "https://api.github.com"
GRAPHQL = "https://api.github.com/graphql"


class GitHubAPI:
    def __init__(self, token: str, proxy: str = "", cache=None):
        self.token = token
        self.cache = cache
        self.s = requests.Session()
        self.s.headers.update({
            "Authorization": f"Bearer {token}",
            "Accept": "application/vnd.github+json",
            "X-GitHub-Api-Version": "2022-11-28",
        })
        if proxy:
            self.s.proxies = {"http": proxy, "https": proxy}

    def _req(self, method, path, retries=3, use_etag=False, **kw):
        etag_key = None
        cached_body = None
        if use_etag and self.cache is not None and method.upper() == "GET":
            params = kw.get("params") or {}
            etag_key = "etag:" + method.upper() + ":" + path + ":" + \
                       json.dumps(params, sort_keys=True, default=str)
            entry = self.cache.get(etag_key, max_age=0)
            if entry and isinstance(entry, dict):
                cached_body = entry.get("body")
                etag = entry.get("etag")
                if etag:
                    kw.setdefault("headers", {})["If-None-Match"] = etag

        last = None
        for attempt in range(retries):
            try:
                r = self.s.request(method, API + path, timeout=20, **kw)
            except requests.RequestException as e:
                last = e
                if attempt < retries - 1:
                    time.sleep(1.5 ** attempt)
                    continue
                raise RuntimeError(f"网络错误：{e}") from None

            if r.status_code == 304 and cached_body is not None:
                return cached_body
            if r.status_code in (403, 429) and r.headers.get("X-RateLimit-Remaining") == "0":
                reset = int(r.headers.get("X-RateLimit-Reset", "0"))
                raise RateLimitError(reset)
            if r.status_code >= 500 and attempt < retries - 1:
                last = RuntimeError(f"HTTP {r.status_code}")
                time.sleep(1.5 ** attempt)
                continue
            if r.status_code >= 400:
                err_msg = r.content[:300].decode("utf-8", errors="replace")
                raise RuntimeError(f"HTTP {r.status_code}: {err_msg}")

            body = r.json() if r.content else None
            if etag_key and r.headers.get("ETag") and self.cache is not None:
                self.cache.set(etag_key, {
                    "etag": r.headers["ETag"],
                    "body": body,
                })
            return body
        raise last or RuntimeError("未知错误")

    # ---------- user / repos ----------
    def me(self):
        return self._req("GET", "/user")

    def rate_limit(self):
        return self._req("GET", "/rate_limit")

    def my_repos(self, page=1, sort="updated", per_page=50, visibility="all"):
        return self._req("GET", "/user/repos", use_etag=True, params={
            "page": page, "sort": sort, "per_page": per_page,
            "affiliation": "owner,collaborator,organization_member",
            "visibility": visibility,
        })

    def list_starred(self, page=1, per_page=50):
        return self._req("GET", "/user/starred", use_etag=True,
                         params={"page": page, "per_page": per_page})

    def trending_repos(self, since="2024-01-01", per_page=30):
        q = f"created:>{since}"
        data = self._req("GET", "/search/repositories", params={
            "q": q, "per_page": per_page, "sort": "stars", "order": "desc",
        })
        return data.get("items", [])

    def get_repo(self, repo):
        return self._req("GET", f"/repos/{repo}", use_etag=True)

    def update_repo(self, repo, **fields):
        return self._req("PATCH", f"/repos/{repo}", json=fields)

    def create_repo(self, name, description="", private=False, auto_init=True):
        return self._req("POST", "/user/repos", json={
            "name": name, "description": description,
            "private": private, "auto_init": auto_init,
        })

    def delete_repo(self, repo):
        self._req("DELETE", f"/repos/{repo}")
        return True

    def set_topics(self, repo, topics):
        return self._req(
            "PUT", f"/repos/{repo}/topics",
            json={"names": topics},
            headers={"Accept": "application/vnd.github.mercy-preview+json"})

    def list_contributors(self, repo, per_page=30):
        try:
            return self._req("GET", f"/repos/{repo}/contributors",
                             params={"per_page": per_page}, use_etag=True)
        except RuntimeError:
            return []

    def get_user_avatar_bytes(self, avatar_url: str) -> bytes:
        """下载头像（不带 Authorization，避免泄漏 token 到 CDN）"""
        if not avatar_url:
            return b""
        proxies = self.s.proxies or None
        r = requests.get(avatar_url, timeout=15, proxies=proxies)
        r.raise_for_status()
        return r.content

    # ---------- search ----------
    def search_repos(self, query, per_page=30):
        data = self._req("GET", "/search/repositories", params={
            "q": query, "per_page": per_page, "sort": "stars", "order": "desc",
        })
        return data.get("items", []), data.get("total_count", 0)

    def search_code(self, query, per_page=20):
        data = self._req("GET", "/search/code",
                         params={"q": query, "per_page": per_page})
        return data.get("items", []), data.get("total_count", 0)

    # ---------- star / watch / fork ----------
    def is_starred(self, repo):
        try:
            self._req("GET", f"/user/starred/{repo}")
            return True
        except RuntimeError:
            return False

    def star(self, repo):
        self._req("PUT", f"/user/starred/{repo}")

    def unstar(self, repo):
        self._req("DELETE", f"/user/starred/{repo}")

    def watch(self, repo, subscribed=True):
        return self._req("PUT", f"/repos/{repo}/subscription",
                         json={"subscribed": subscribed, "ignored": False})

    def fork(self, repo):
        return self._req("POST", f"/repos/{repo}/forks")

    # ---------- issues ----------
    def list_issues(self, repo, state="open", page=1, per_page=50,
                    labels=None, assignee=None, creator=None, sort=None,
                    direction=None):
        params = {"state": state, "page": page, "per_page": per_page}
        if labels:
            params["labels"] = ",".join(labels) if isinstance(labels, (list, tuple)) else labels
        if assignee:
            params["assignee"] = assignee
        if creator:
            params["creator"] = creator
        if sort:
            params["sort"] = sort
        if direction:
            params["direction"] = direction
        return self._req("GET", f"/repos/{repo}/issues", use_etag=True, params=params)

    def get_issue(self, repo, number):
        return self._req("GET", f"/repos/{repo}/issues/{number}", use_etag=True)

    def create_issue(self, repo, title, body="", labels=None, assignees=None):
        payload = {"title": title, "body": body}
        if labels:
            payload["labels"] = labels
        if assignees:
            payload["assignees"] = assignees
        return self._req("POST", f"/repos/{repo}/issues", json=payload)

    def update_issue(self, repo, number, **fields):
        return self._req("PATCH", f"/repos/{repo}/issues/{number}", json=fields)

    def delete_issue(self, node_id):
        q = ("mutation($id: ID!) { deleteIssue(input: {issueId: $id}) "
             "{ clientMutationId } }")
        r = self.s.post(GRAPHQL, json={"query": q, "variables": {"id": node_id}},
                        timeout=20)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}: {r.content[:300]}")
        data = r.json()
        if data.get("errors"):
            raise RuntimeError("; ".join(e.get("message", "?") for e in data["errors"]))
        return data

    def list_comments(self, repo, number):
        return self._req("GET", f"/repos/{repo}/issues/{number}/comments",
                         params={"per_page": 100})

    def create_comment(self, repo, number, body):
        return self._req("POST", f"/repos/{repo}/issues/{number}/comments",
                         json={"body": body})

    def list_labels(self, repo):
        try:
            return self._req("GET", f"/repos/{repo}/labels",
                             params={"per_page": 100}, use_etag=True)
        except RuntimeError:
            return []

    # ---------- branches / commits / files ----------
    def list_branches(self, repo, page=1):
        return self._req("GET", f"/repos/{repo}/branches",
                         params={"page": page, "per_page": 100}, use_etag=True)

    def list_commits(self, repo, ref=None, page=1):
        params = {"page": page, "per_page": 50}
        if ref:
            params["sha"] = ref
        return self._req("GET", f"/repos/{repo}/commits", params=params)

    def get_commit_diff(self, repo, sha):
        r = self.s.get(f"{API}/repos/{repo}/commits/{sha}",
                       headers={"Accept": "application/vnd.github.diff"},
                       timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.text

    def get_readme(self, repo, ref=None):
        try:
            data = self._req("GET", f"/repos/{repo}/readme",
                             params={"ref": ref} if ref else {}, use_etag=True)
            if data.get("encoding") == "base64" and data.get("content"):
                return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
            return ""
        except RuntimeError:
            return ""

    def get_tree(self, repo, ref):
        ref_q = quote(str(ref), safe="")
        return self._req("GET", f"/repos/{repo}/git/trees/{ref_q}",
                         params={"recursive": 1})

    def get_file_content(self, repo, path, ref=None):
        path_q = quote(str(path), safe="/")
        data = self._req("GET", f"/repos/{repo}/contents/{path_q}",
                         params={"ref": ref} if ref else {})
        if isinstance(data, dict) and data.get("encoding") == "base64":
            return base64.b64decode(data["content"]).decode("utf-8", errors="replace")
        return ""

    # ---------- releases / assets ----------
    def list_releases(self, repo):
        return self._req("GET", f"/repos/{repo}/releases",
                         params={"per_page": 30}, use_etag=True)

    def get_latest_release(self, repo):
        return self._req("GET", f"/repos/{repo}/releases/latest")

    def create_release(self, repo, tag_name, name="", body="", draft=False,
                       prerelease=False, target_commitish=None):
        payload = {
            "tag_name": tag_name, "name": name or tag_name, "body": body,
            "draft": draft, "prerelease": prerelease,
        }
        if target_commitish:
            payload["target_commitish"] = target_commitish
        return self._req("POST", f"/repos/{repo}/releases", json=payload)

    def download_asset(self, repo, asset, dest_dir, on_progress=None):
        asset_id = asset.get("id")
        if asset_id is None:
            raise RuntimeError("资产缺少 id，无法下载")
        name = os.path.basename(asset.get("name") or "")
        if not name:
            raise RuntimeError("资产文件名非法")

        target = os.path.join(dest_dir, name)
        if os.path.exists(target):
            base, ext = os.path.splitext(name)
            i = 1
            while os.path.exists(os.path.join(dest_dir, f"{base} ({i}){ext}")):
                i += 1
            target = os.path.join(dest_dir, f"{base} ({i}){ext}")

        tmp = target + ".part"
        url = f"{API}/repos/{repo}/releases/assets/{asset_id}"
        r = None
        try:
            r = self.s.get(url, headers={"Accept": "application/octet-stream"},
                           allow_redirects=False, timeout=30, stream=True)
            if r.status_code in (301, 302, 303, 307, 308):
                loc = r.headers.get("Location")
                r.close()
                if not loc:
                    raise RuntimeError("重定向地址缺失")
                proxies = self.s.proxies or None
                r = requests.get(loc, stream=True, timeout=300, proxies=proxies)
            r.raise_for_status()
            total = int(r.headers.get("Content-Length") or asset.get("size") or 0)
            done = 0
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1024 * 64):
                    if not chunk:
                        continue
                    f.write(chunk)
                    done += len(chunk)
                    if on_progress and total:
                        on_progress(min(1.0, done / total))
            os.replace(tmp, target)
            return target
        finally:
            if r is not None:
                try:
                    r.close()
                except Exception:
                    pass
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ---------- pulls ----------
    def list_pulls(self, repo, state="open", page=1, head=None, base=None,
                   sort=None, direction=None):
        params = {"state": state, "page": page, "per_page": 30}
        if head:
            params["head"] = head
        if base:
            params["base"] = base
        if sort:
            params["sort"] = sort
        if direction:
            params["direction"] = direction
        return self._req("GET", f"/repos/{repo}/pulls", use_etag=True, params=params)

    def get_pull(self, repo, number):
        return self._req("GET", f"/repos/{repo}/pulls/{number}", use_etag=True)

    def list_pull_files(self, repo, number):
        return self._req("GET", f"/repos/{repo}/pulls/{number}/files",
                         params={"per_page": 100})

    def get_pull_diff(self, repo, number):
        r = self.s.get(f"{API}/repos/{repo}/pulls/{number}",
                       headers={"Accept": "application/vnd.github.diff"},
                       timeout=30)
        if r.status_code >= 400:
            raise RuntimeError(f"HTTP {r.status_code}")
        return r.text

    def list_pull_comments(self, repo, number):
        return self._req("GET", f"/repos/{repo}/pulls/{number}/comments",
                         params={"per_page": 100})

    def create_pull_review(self, repo, number, event, body=""):
        return self._req("POST", f"/repos/{repo}/pulls/{number}/reviews",
                         json={"event": event, "body": body})

    def create_pull(self, repo, title, head, base, body="", draft=False,
                    maintainer_can_modify=True):
        payload = {
            "title": title, "head": head, "base": base, "body": body,
            "draft": draft, "maintainer_can_modify": maintainer_can_modify,
        }
        return self._req("POST", f"/repos/{repo}/pulls", json=payload)

    def merge_pull(self, repo, number, method="merge"):
        return self._req("PUT", f"/repos/{repo}/pulls/{number}/merge",
                         json={"merge_method": method})

    def close_pull(self, repo, number):
        return self._req("PATCH", f"/repos/{repo}/pulls/{number}",
                         json={"state": "closed"})

    # ---------- notifications ----------
    def list_notifications(self, all_=False):
        return self._req("GET", "/notifications",
                         params={"all": "true" if all_ else "false", "per_page": 50})

    def mark_notification_read(self, thread_id):
        self._req("PATCH", f"/notifications/threads/{thread_id}")

    # ---------- actions ----------
    def list_action_runs(self, repo):
        return self._req("GET", f"/repos/{repo}/actions/runs",
                         params={"per_page": 20}, use_etag=True)

    def download_action_logs(self, repo, run_id, dest_dir):
        """下载某次 workflow run 的日志 zip，返回保存路径"""
        url = f"{API}/repos/{repo}/actions/runs/{run_id}/logs"
        tmp = os.path.join(dest_dir, f"_logs_{run_id}.zip")
        r = None
        try:
            r = self.s.get(url, allow_redirects=True, timeout=60, stream=True)
            r.raise_for_status()
            with open(tmp, "wb") as f:
                for chunk in r.iter_content(1024 * 64):
                    if chunk:
                        f.write(chunk)
            target = os.path.join(dest_dir, f"actions-{run_id}-logs.zip")
            os.replace(tmp, target)
            return target
        finally:
            if r is not None:
                try:
                    r.close()
                except Exception:
                    pass
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    # ---------- gists ----------
    def list_gists(self, page=1):
        return self._req("GET", "/gists", use_etag=True,
                         params={"page": page, "per_page": 30})

    def get_gist(self, gist_id):
        return self._req("GET", f"/gists/{gist_id}")

    def create_gist(self, description, files: dict, public=False):
        return self._req("POST", "/gists", json={
            "description": description, "public": public, "files": files,
        })

    def update_gist(self, gist_id, files: dict, description=None):
        payload = {"files": files}
        if description is not None:
            payload["description"] = description
        return self._req("PATCH", f"/gists/{gist_id}", json=payload)

    def delete_gist(self, gist_id):
        self._req("DELETE", f"/gists/{gist_id}")

    # ---------- download / git ----------
    def download_zip(self, repo, dest_dir, ref=None, on_progress=None):
        url = f"{API}/repos/{repo}/zipball" + (f"/{ref}" if ref else "")
        tmp = os.path.join(dest_dir, f"._dl_{repo.replace('/', '-')}.zip")
        try:
            r = self.s.get(url, allow_redirects=False, timeout=30)
            try:
                if r.status_code in (301, 302, 303, 307, 308):
                    loc = r.headers.get("Location")
                    r.close()
                    if not loc:
                        raise RuntimeError("重定向地址缺失")
                    proxies = self.s.proxies or None
                    r = requests.get(loc, stream=True, timeout=300, proxies=proxies)
                r.raise_for_status()
                total = int(r.headers.get("Content-Length") or 0)
                done = 0
                with open(tmp, "wb") as f:
                    for chunk in r.iter_content(1024 * 64):
                        if not chunk:
                            continue
                        f.write(chunk)
                        done += len(chunk)
                        if on_progress and total:
                            on_progress(min(1.0, done / total))
            finally:
                r.close()

            target = os.path.join(dest_dir, repo.replace("/", "-"))
            if os.path.exists(target):
                raise RuntimeError(f"目标目录已存在：{target}")
            with zipfile.ZipFile(tmp) as z:
                members = z.namelist()
                if not members:
                    raise RuntimeError("压缩包为空")
                base = os.path.realpath(dest_dir)
                for m in members:
                    p = os.path.realpath(os.path.join(dest_dir, m))
                    if not (p == base or p.startswith(base + os.sep)):
                        raise RuntimeError(f"压缩包含非法路径：{m}")
                z.extractall(dest_dir)
                top = members[0].split("/")[0]
                extracted_top = os.path.join(dest_dir, top)
                if os.path.isdir(extracted_top):
                    os.replace(extracted_top, target)
            return target
        finally:
            if os.path.exists(tmp):
                try:
                    os.remove(tmp)
                except OSError:
                    pass

    def _git_auth_args(self):
        auth = base64.b64encode(f"x-access-token:{self.token}".encode()).decode()
        return ["-c", f"http.extraheader=Authorization: Basic {auth}"]

    def clone_repo(self, repo, dest_dir, depth=1, on_progress=None):
        target = os.path.join(dest_dir, repo.split("/")[-1])
        if os.path.exists(target):
            raise RuntimeError(f"目标目录已存在：{target}")
        cmd = ["git"] + self._git_auth_args() + ["clone"]
        if depth:
            cmd += ["--depth", str(depth)]
        cmd += ["--progress", f"https://github.com/{repo}.git", target]
        try:
            proc = subprocess.Popen(
                cmd, stderr=subprocess.PIPE, stdout=subprocess.DEVNULL,
                text=True, bufsize=1, encoding="utf-8", errors="replace")
        except FileNotFoundError:
            raise RuntimeError("找不到 git 命令")
        for line in proc.stderr:
            line = line.strip()
            if on_progress:
                m = re.search(r"(\d+)%", line)
                if m:
                    on_progress(int(m.group(1)) / 100.0, line)
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"git clone 失败（exit {proc.returncode}）")
        return target

    def pull_repo(self, local_path, on_progress=None):
        if not os.path.isdir(os.path.join(local_path, ".git")):
            raise RuntimeError(f"不是 git 仓库：{local_path}")
        cmd = ["git"] + self._git_auth_args() + ["-C", local_path, "pull"]
        proc = subprocess.Popen(cmd, stderr=subprocess.PIPE, stdout=subprocess.PIPE,
                                text=True, encoding="utf-8", errors="replace")
        out, err = proc.communicate()
        if proc.returncode != 0:
            raise RuntimeError(f"git pull 失败：{(err or '').strip()}")
        return (out or "") + (err or "")

    # ---------- upload local project ----------
    def init_and_push_local(self, local_path, repo, branch="main",
                            commit_message="Initial commit", user=None,
                            on_progress=None):
        """把本地目录推送到 GitHub 仓库（自动 init / commit / push）"""
        import shutil as _shutil
        if not os.path.isdir(local_path):
            raise RuntimeError(f"目录不存在：{local_path}")
        if not _shutil.which("git"):
            raise RuntimeError("找不到 git 命令，请先安装 Git 并加入 PATH")

        is_git = os.path.isdir(os.path.join(local_path, ".git"))
        extra_cfg = []
        if user:
            extra_cfg = [
                "-c", f"user.name={user}",
                "-c", f"user.email={user}@users.noreply.github.com",
            ]

        def _run(args, check=True):
            cmd = ["git"] + self._git_auth_args() + extra_cfg + \
                  ["-C", local_path] + args
            if on_progress:
                try:
                    on_progress(-1, f"$ git {' '.join(args)}")
                except Exception:
                    pass
            proc = subprocess.Popen(
                cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE,
                text=True, encoding="utf-8", errors="replace")
            out, err = proc.communicate()
            if check and proc.returncode != 0:
                msg = (err or out or "").strip()
                raise RuntimeError(f"git {' '.join(args)} 失败：{msg[:500]}")
            return out, err

        # 1) 初始化仓库
        if not is_git:
            _run(["init"])
            is_git = True

        # 2) 切到目标分支（空仓库也支持）
        _run(["checkout", "-B", branch], check=False)

        # 3) 配置 origin
        url = f"https://github.com/{repo}.git"
        out, _ = _run(["remote"], check=False)
        remotes = (out or "").split()
        if "origin" in remotes:
            _run(["remote", "set-url", "origin", url])
        else:
            _run(["remote", "add", "origin", url])

        # 4) add & commit
        _run(["add", "-A"])
        status_out, _ = _run(["status", "--porcelain"], check=False)
        has_changes = bool((status_out or "").strip())
        has_commit = False
        try:
            h_out, _ = _run(["rev-parse", "--verify", "HEAD"], check=False)
            has_commit = bool((h_out or "").strip())
        except Exception:
            has_commit = False
        if has_changes or not has_commit:
            _run(["commit", "-m", commit_message, "--allow-empty"])

        # 5) push（流式输出，捕捉进度）
        push_cmd = ["git"] + self._git_auth_args() + extra_cfg + \
                   ["-C", local_path, "push", "-u", "origin", branch]
        if on_progress:
            try:
                on_progress(-1, "正在推送…")
            except Exception:
                pass
        proc = subprocess.Popen(
            push_cmd, stdout=subprocess.PIPE, stderr=subprocess.STDOUT,
            text=True, encoding="utf-8", errors="replace", bufsize=1)
        assert proc.stdout is not None
        for line in proc.stdout:
            if on_progress and line.strip():
                try:
                    on_progress(-1, line.strip())
                except Exception:
                    pass
        proc.wait()
        if proc.returncode != 0:
            raise RuntimeError(f"git push 失败（exit {proc.returncode}）")

        if on_progress:
            try:
                on_progress(1.0, "推送完成")
            except Exception:
                pass
        return url
"""GitHub OAuth Device Flow
用户需在 https://github.com/settings/developers 创建一个 OAuth App，
client_id 填入设置页。不需要 client_secret（公开客户端）。
"""
import time
import requests


class DeviceFlow:
    def __init__(self, client_id, proxy=""):
        self.client_id = client_id
        self.proxies = {"http": proxy, "https": proxy} if proxy else {}
        self.s = requests.Session()
        self.s.headers.update({
            "Accept": "application/json",
            "User-Agent": "github-desktop-client",
        })

    def start(self, scope="repo read:user notifications gist"):
        r = self.s.post(
            "https://github.com/login/device/code",
            data={"client_id": self.client_id, "scope": scope},
            timeout=20, proxies=self.proxies,
        )
        r.raise_for_status()
        data = r.json()
        if "error" in data:
            raise RuntimeError(data.get("error_description", data["error"]))
        return data

    def poll_once(self, device_code):
        r = self.s.post(
            "https://github.com/login/oauth/access_token",
            data={
                "client_id": self.client_id,
                "device_code": device_code,
                "grant_type": "urn:ietf:params:oauth:grant-type:device_code",
            },
            timeout=20, proxies=self.proxies,
        )
        r.raise_for_status()
        return r.json()

    def wait_for_token(self, start_info, on_tick=None, cancel_flag=None):
        device_code = start_info["device_code"]
        interval = max(5, int(start_info.get("interval", 5)))
        deadline = time.time() + int(start_info.get("expires_in", 900))
        while time.time() < deadline:
            if cancel_flag and cancel_flag():
                raise RuntimeError("已取消")
            if on_tick:
                on_tick(int(deadline - time.time()))
            time.sleep(interval)
            data = self.poll_once(device_code)
            if data.get("access_token"):
                return data["access_token"]
            err = data.get("error")
            if err == "authorization_pending":
                continue
            if err == "slow_down":
                interval += 5
                continue
            if err in ("expired_token", "access_denied"):
                raise RuntimeError(f"授权失败：{err}")
            if err:
                raise RuntimeError(f"授权失败：{err}")
        raise RuntimeError("验证超时，请重新开始")
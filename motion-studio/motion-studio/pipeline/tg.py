"""Telegram helpers (the Motion Studio bot)."""
import os
from common import S, env, retry


class Telegram:
    def __init__(self, chat_id):
        self.token = env("MOTION_TG_TOKEN", required=True)
        self.chat = chat_id
        self.base = f"https://api.telegram.org/bot{self.token}"

    def send(self, text):
        r = S.post(self.base + "/sendMessage", json={"chat_id": self.chat, "text": text[:4000], "disable_web_page_preview": True}, timeout=30)
        try:
            return r.json().get("result", {}).get("message_id")
        except Exception:  # noqa: BLE001
            return None

    def edit(self, message_id, text):
        r = S.post(self.base + "/editMessageText", json={"chat_id": self.chat, "message_id": message_id, "text": text[:4000], "disable_web_page_preview": True}, timeout=30)
        return r.status_code == 200

    def send_video(self, path, caption=""):
        def go():
            with open(path, "rb") as f:
                r = S.post(self.base + "/sendVideo", data={"chat_id": self.chat, "caption": caption[:1000], "supports_streaming": "true"}, files={"video": f}, timeout=600)
            if r.status_code != 200:
                raise RuntimeError(f"{r.status_code} {r.text[:150]}")
        retry(go, tries=2, what="send video")

    def send_photo(self, path, caption=""):
        with open(path, "rb") as f:
            S.post(self.base + "/sendPhoto", data={"chat_id": self.chat, "caption": caption[:1000]}, files={"photo": f}, timeout=120)

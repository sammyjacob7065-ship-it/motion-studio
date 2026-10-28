"""Supabase Storage helpers. Everything for a job lives under motion/jobs/<job>/ in the bucket."""
import json
import os
from urllib.parse import quote
from common import S, env, retry


class Store:
    def __init__(self):
        self.url = env("SUPABASE_URL", required=True).rstrip("/")
        self.key = env("SUPABASE_SERVICE_KEY", required=True)
        self.bucket = env("SUPABASE_BUCKET", "betrayer-assets")
        self.h = {"apikey": self.key, "Authorization": "Bearer " + self.key}

    def _obj(self, path, auth=False):
        return f"{self.url}/storage/v1/object/{'authenticated/' if auth else ''}{self.bucket}/{quote(path)}"

    def put_json(self, path, obj):
        def go():
            r = S.post(self._obj(path), headers={**self.h, "Content-Type": "application/json", "x-upsert": "true"}, data=json.dumps(obj), timeout=30)
            if r.status_code >= 300:
                raise RuntimeError(f"{r.status_code} {r.text[:120]}")
        retry(go, what=f"save {path}")

    def get_json(self, path):
        try:
            r = S.get(self._obj(path, auth=True), headers=self.h, timeout=30)
            if r.status_code != 200:
                return None
            return r.json()
        except Exception:  # noqa: BLE001
            return None

    def exists(self, path):
        return self.get_json(path) is not None

    def download(self, path, dest):
        def go():
            r = S.get(self._obj(path, auth=True), headers=self.h, timeout=300, stream=True)
            if r.status_code != 200:
                raise RuntimeError(f"{r.status_code}")
            os.makedirs(os.path.dirname(dest) or ".", exist_ok=True)
            with open(dest, "wb") as f:
                for chunk in r.iter_content(1 << 20):
                    f.write(chunk)
        retry(go, what=f"download {path}")
        return dest

    def upload_file(self, path, src, content_type="application/octet-stream"):
        def go():
            with open(src, "rb") as f:
                r = S.post(self._obj(path), headers={**self.h, "Content-Type": content_type, "x-upsert": "true"}, data=f, timeout=600)
            if r.status_code >= 300:
                raise RuntimeError(f"{r.status_code} {r.text[:120]}")
        retry(go, what=f"upload {path}")

    def signed_url(self, path, days=7):
        r = S.post(f"{self.url}/storage/v1/object/sign/{self.bucket}/{quote(path)}", headers={**self.h, "Content-Type": "application/json"}, data=json.dumps({"expiresIn": days * 86400}), timeout=30)
        if r.status_code != 200:
            return ""
        u = r.json().get("signedURL", "")
        return self.url + "/storage/v1" + u if u.startswith("/object") else (self.url + u if u.startswith("/") else u)

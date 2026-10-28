import os
import time
import requests

S = requests.Session()


def env(name, default=None, required=False):
    v = os.environ.get(name)
    if isinstance(v, str):
        v = v.strip()
    if v is None or v == "":      # an unset GitHub secret arrives as an empty text: treat it as "not set" and use the default
        v = default
    if required and not v:
        raise RuntimeError(f"Missing setting {name}. Add it in GitHub: repo Settings > Secrets and variables > Actions.")
    return v


def retry(fn, tries=3, wait=2.0, what="request"):
    last = None
    for i in range(tries):
        try:
            return fn()
        except Exception as e:  # noqa: BLE001
            last = e
            if i < tries - 1:
                time.sleep(wait * (i + 1))
    raise RuntimeError(f"{what} failed: {str(last)[:200]}")


class Cancelled(Exception):
    pass

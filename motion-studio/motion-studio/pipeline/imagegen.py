"""Makes a picture from a description. Same order as the movie factory:
Agnes (4 keys, one after the other) -> Cloudflare FLUX -> AI Horde. Returns (path, provider) or (None, why)."""
import base64
import os
import re
import time

import requests

from common import env

try:
    import image_keys as K
except Exception:  # noqa: BLE001
    K = None

_BLOCKED = {}          # provider -> why (a dead key / used-up quota is skipped for the rest of the job)
_START = {"i": 0}      # Agnes: each picture starts on a different key
DEAD = ("quota exceeded", "out of credit", "no credit", "balance", "insufficient", "401", "402", "403", "unauthor", "invalid api key", "invalid token", "authentication", "daily")


def _agnes_keys():
    own = [env(f"AGNES_API_KEY{s}") for s in ("", "_2", "_3", "_4")]
    own = [k for k in own if k]
    return own or list(getattr(K, "AGNES_KEYS", []) or [])


def _is_img(b):
    return bool(b) and len(b) > 1500 and (b[:3] == b"\xff\xd8\xff" or b[:4] == b"\x89PNG" or b[:4] == b"RIFF")


def _ext(b):
    return "png" if b[:4] == b"\x89PNG" else ("webp" if b[:4] == b"RIFF" else "jpg")


def _ratio(aspect):
    return {"16:9": "16:9", "9:16": "9:16", "1:1": "1:1", "4:5": "9:16"}.get(aspect or "9:16", "9:16")


def _agnes(prompt, aspect):
    keys = _agnes_keys()
    if not keys:
        raise RuntimeError("no Agnes key")
    last = ""
    for n in range(len(keys)):
        key = keys[(_START["i"] + n) % len(keys)]
        try:
            r = requests.post("https://apihub.agnes-ai.com/v1/images/generations", headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                              json={"model": "agnes-image-2.1-flash", "prompt": prompt[:1800], "size": "1K", "ratio": _ratio(aspect), "return_base64": True}, timeout=150)
            if r.status_code >= 400:
                last = f"{r.status_code} {r.text[:120]}"
                continue
            d = (r.json().get("data") or [{}])[0]
            if d.get("b64_json"):
                b = base64.b64decode(d["b64_json"])
            elif d.get("url"):
                b = requests.get(d["url"], timeout=90).content
            else:
                last = "no picture in answer"
                continue
            if _is_img(b):
                _START["i"] += 1
                return b
            last = "broken picture"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:120]
    raise RuntimeError(last or "Agnes failed")


def _cloudflare(prompt, aspect):
    acc, tok = env("CLOUDFLARE_ACCOUNT_ID") or getattr(K, "CLOUDFLARE_ACCOUNT", ""), env("CLOUDFLARE_API_TOKEN") or getattr(K, "CLOUDFLARE_TOKEN", "")
    if not acc or not tok:
        raise RuntimeError("no Cloudflare key")
    r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/@cf/black-forest-labs/flux-1-schnell",
                      headers={"Authorization": "Bearer " + tok, "Content-Type": "application/json"}, json={"prompt": prompt[:1700], "steps": 4}, timeout=110)
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code} {r.text[:120]}")
    if r.headers.get("content-type", "").startswith("image"):
        b = r.content
    else:
        j = r.json()
        if j.get("success") is False:
            raise RuntimeError(str(j.get("errors"))[:150])
        b = base64.b64decode((j.get("result") or {}).get("image") or j.get("image") or "")
    if not _is_img(b):
        raise RuntimeError("broken picture")
    return b


def _horde(prompt, aspect, wait=420):
    key = env("HORDE_API_KEY") or getattr(K, "HORDE_KEY", "") or "0000000000"
    H = {"apikey": key, "Client-Agent": "motion-studio:1.0:owner"}
    w, h = {"16:9": (1024, 576), "1:1": (768, 768)}.get(aspect or "9:16", (576, 1024))
    model = "Flux.1-Schnell fp8 (Compact)"
    try:
        live = requests.get("https://aihorde.net/api/v2/status/models?type=image&min_count=1&model_state=known", headers=H, timeout=15).json()
        names = {m.get("name"): int(m.get("count") or 0) for m in live if isinstance(m, dict)}
        if names.get(model, 0) <= 0:
            alt = [n for n in ("AlbedoBase XL (SDXL)", "Juggernaut XL", "SDXL 1.0", "Deliberate") if names.get(n, 0) > 0]
            if not alt:
                raise RuntimeError("no AI Horde worker online")
            model = alt[0]
    except RuntimeError:
        raise
    except Exception:  # noqa: BLE001
        pass
    flux = model.startswith("Flux")
    params = {"width": w, "height": h, "steps": 8 if flux else 25, "cfg_scale": 1 if flux else 6, "sampler_name": "k_euler" if flux else "k_dpmpp_2m", "karras": not flux, "n": 1}
    r = requests.post("https://aihorde.net/api/v2/generate/async", headers=H, json={"prompt": prompt[:700] + " ### text, watermark, logo, blurry, deformed", "params": params, "nsfw": False, "censor_nsfw": True, "r2": True, "slow_workers": True, "models": [model]}, timeout=30)
    if r.status_code >= 400:
        raise RuntimeError(f"{r.status_code} {r.text[:120]}")
    jid, t0 = r.json().get("id"), time.time()
    while time.time() - t0 < wait:
        time.sleep(6)
        c = requests.get(f"https://aihorde.net/api/v2/generate/check/{jid}", headers=H, timeout=20).json()
        if c.get("faulted"):
            raise RuntimeError("AI Horde job failed")
        if c.get("done"):
            g = (requests.get(f"https://aihorde.net/api/v2/generate/status/{jid}", headers=H, timeout=30).json().get("generations") or [{}])[0]
            if not g.get("img") or g.get("censored"):
                raise RuntimeError("AI Horde gave no usable picture")
            b = requests.get(g["img"], timeout=90).content
            if _is_img(b):
                return b
            raise RuntimeError("broken picture")
    try:
        requests.delete(f"https://aihorde.net/api/v2/generate/status/{jid}", headers=H, timeout=10)
    except Exception:  # noqa: BLE001
        pass
    raise RuntimeError("AI Horde took too long")


PROVIDERS = [("agnes", _agnes), ("cloudflare", _cloudflare), ("horde", _horde)]

LOG = []        # every attempt: {pic, provider, ok, why}


def plain(why):
    """The reason in plain words (what the client can act on)."""
    w = str(why or "").lower()
    if re.search(r"no (agnes|cloudflare|horde) key", w):
        return "key is missing in GitHub secrets"
    if re.search(r"\b40[13]\b|unauthori|invalid (api )?(key|token)|authentication|revoked|forbidden", w):
        return "key or token was refused (wrong, expired or revoked)"
    if re.search(r"\b402\b|insufficient|balance|credit|quota|daily|neurons|exceeded|usage limit", w):
        return "free limit or credit is used up"
    if re.search(r"\b429\b|rate|too many", w):
        return "too many requests at once (rate limit)"
    if re.search(r"censor|nsfw|safety|moderat|blocked|not allowed|no usable picture|flagged|policy", w):
        return "blocked by the provider's safety filter"
    if re.search(r"timed out|timeout|took too long", w):
        return "took too long (timed out)"
    if re.search(r"no ai horde worker", w):
        return "no free AI Horde worker is online"
    if re.search(r"\b5\d\d\b|overload|unavailable|busy|bad gateway|internal", w):
        return "the provider is busy or down"
    if re.search(r"broken picture|no picture in answer|too small", w):
        return "the provider sent no valid picture"
    if "skipped" in w:
        return "skipped (it failed repeatedly just before)"
    return str(why)[:70]


def reasons_for(pic):
    """'Agnes: ...; Cloudflare: ...; Horde: ...' - the latest plain reason of each provider for one picture."""
    last = {}
    for e in LOG:
        if e["pic"] == pic and not e["ok"]:
            last[e["provider"]] = e["why"]
    return "; ".join(f"{p.title()}: {plain(w)}" for p, w in last.items()) or "no reason was reported"


def summary():
    """One line per provider: how many pictures it made, how many attempts failed, and why (most common reason)."""
    out = []
    for p, _fn in PROVIDERS:
        ok = sum(1 for e in LOG if e["provider"] == p and e["ok"])
        bad = [plain(e["why"]) for e in LOG if e["provider"] == p and not e["ok"]]
        if not ok and not bad:
            continue
        top = max(set(bad), key=bad.count) if bad else ""
        out.append(f"{p.title()}: {ok} made, {len(bad)} failed" + (f" ({top})" if top else ""))
    return out


def _simple(prompt):
    """A shorter, plainer version of the prompt for the last try (long prompts are sometimes refused or time out)."""
    first = re.split(r"(?<=[.!?])\s+", str(prompt).strip())[0]
    return first[:260].rstrip(" ,;.") + "."


def _clean(b, path):
    """Opens the bytes as a picture (raises when it is not one or too small), and saves a plain RGB JPEG."""
    import io
    from PIL import Image
    im = Image.open(io.BytesIO(b))
    im.load()
    if min(im.size) < 256:
        raise RuntimeError(f"picture too small ({im.size[0]}x{im.size[1]})")
    im = im.convert("RGB")
    im.thumbnail((2160, 2160))                          # very big pictures make the renderer slow and can time it out
    im.save(path, "JPEG", quality=93)


def generate(prompt, aspect, dest_dir, name, exact=False, rounds=3):
    """Tries the providers in order, and when all of them fail it rests and tries the whole chain again (up to 3 rounds, the last one with a simpler prompt),
    so a picture is not given up on after one bad moment. Returns (path, provider) or (None, 'why each failed')."""
    if env("IMAGE_AI", "1") == "0":
        return None, "AI pictures switched off"
    base = str(prompt).strip()
    notes = []
    for rnd in range(rounds):
        text = base if rnd < rounds - 1 else _simple(base)
        if exact:                                               # the client's own image prompt: used as written
            text += " No text, no watermark, no logo."
        else:
            text += (" Photorealistic, natural light, sharp, professional photo. No text, no watermark, no logo." if "photo" not in text.lower() else " No text, no watermark, no logo.")
        for pname, fn in PROVIDERS:
            until = _BLOCKED.get(pname)
            if until and time.time() < until[0]:
                notes.append(f"{pname}: skipped ({until[1]})")
                LOG.append({"pic": name, "provider": pname, "ok": False, "why": until[1]})
                continue
            try:
                b = fn(text, aspect)
                path = os.path.join(dest_dir, f"{name}.jpg")
                _clean(b, path)                                 # must really be a picture; saved as a clean JPEG the renderer can always open
                LOG.append({"pic": name, "provider": pname, "ok": True, "why": ""})
                return path, pname
            except Exception as e:  # noqa: BLE001
                why = str(e)[:140]
                LOG.append({"pic": name, "provider": pname, "ok": False, "why": why})
                notes.append(f"round {rnd + 1} {pname}: {why}")
                if pname != "horde" and any(q in why.lower() for q in DEAD):
                    _BLOCKED[pname] = (time.time() + 20 * 60, why[:60])      # a dead key / empty credit: skip for 20 minutes, then look again
        if rnd < rounds - 1:
            print(f"::warning::picture '{name}' failed on every provider - resting before round {rnd + 2}")
            time.sleep(20 * (rnd + 1))
    return None, "; ".join(notes[-6:])

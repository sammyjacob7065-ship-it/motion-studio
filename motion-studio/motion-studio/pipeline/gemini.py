"""Google Gemini (free key): reads videos and writes big JSON answers. Tries the models in order and rests when one is busy.
Key: GitHub secret GEMINI_API_KEY (optional extras GEMINI_API_KEY_2, _3). Models: secret GEMINI_MODELS (comma list) or the default list."""
import base64
import json
import re
import time

from common import S, env

BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
DEFAULT_MODELS = "gemini-3.8-flash,gemini-3.7-flash,gemini-2.5-flash,gemini-flash-lite-latest"
_K = {"i": 0}
LAST = {"finish": ""}                                       # why the last answer ended (STOP, MAX_TOKENS ...)


def keys():
    out = []
    for n in ("GEMINI_API_KEY", "GEMINI_API_KEY_2", "GEMINI_API_KEY_3"):
        v = env(n)
        if v and v not in out:
            out.append(v)
    return out


def available():
    return bool(keys())


_FOUND = {"list": None}


def _version(name):
    m = re.search(r"gemini-(\d+(?:\.\d+)?)", name)
    return float(m.group(1)) if m else 0.0


def discover():
    """Asks Google which models this key can use, and returns the usable text models, best first (newest flash, then pro, then lite). Cached; [] when the list cannot be read."""
    if _FOUND["list"] is not None:
        return _FOUND["list"]
    out = []
    ks = keys()
    if ks:
        try:
            r = S.get(BASE.rstrip("/"), headers={"x-goog-api-key": ks[0]}, params={"pageSize": 200}, timeout=30)
            for m in (r.json().get("models") or []) if r.status_code == 200 else []:
                name = str(m.get("name", "")).replace("models/", "")
                if "generateContent" not in (m.get("supportedGenerationMethods") or []):
                    continue
                if not name.startswith("gemini") or re.search(r"image|tts|audio|live|embed|robotics|computer|transcribe|omni|vision-only|learnlm|exp-|preview-\d\d-\d\d", name):
                    continue
                out.append(name)
        except Exception as e:  # noqa: BLE001
            print("::warning::could not list Gemini models:", str(e)[:100])
    def rank(n):
        tier = 0 if "flash" in n and "lite" not in n else (1 if "pro" in n else 2)      # flash is quick and generous, pro is slower, lite is weakest
        return (tier, -_version(n), n)
    _FOUND["list"] = sorted(set(out), key=rank)[:10]
    return _FOUND["list"]


def models():
    """GEMINI_MODELS (secret) if set. Otherwise every usable model the key can see (best first), then the built-in list as a last resort."""
    chosen = [m.strip() for m in env("GEMINI_MODELS", "").split(",") if m.strip()]
    if chosen:
        return chosen
    out = []
    for m in discover() + [x.strip() for x in DEFAULT_MODELS.split(",")]:
        if m and m not in out:
            out.append(m)
    return out


def _finish(resp):
    c = (resp.get("candidates") or [{}])[0]
    return str(c.get("finishReason") or "")


def _text(resp):
    out = []
    for c in (resp.get("candidates") or [])[:1]:
        for p in (c.get("content") or {}).get("parts") or []:
            if p.get("text") and not p.get("thought"):
                out.append(p["text"])
    return "".join(out).strip()


def generate(prompt, system=None, json_mode=True, video=None, video_mime="video/mp4", temperature=0.3, max_tokens=32000, rounds=3, images=None, timeout=300, deadline=None):
    """Returns the answer text. video = bytes of a video (up to about 20 MB) shown to the model together with the prompt."""
    ks = keys()
    if not ks:
        raise RuntimeError("No Gemini key set (GitHub secret GEMINI_API_KEY).")
    parts = [{"text": prompt}]
    if video:
        parts.insert(0, {"inline_data": {"mime_type": video_mime, "data": base64.b64encode(video).decode()}})
    for im in (images or []):                                  # pictures (bytes, mime) shown to the model
        parts.insert(0, {"inline_data": {"mime_type": im[1], "data": base64.b64encode(im[0]).decode()}})
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"temperature": temperature, "maxOutputTokens": max_tokens}}
    if json_mode:
        body["generationConfig"]["responseMimeType"] = "application/json"
    if system:
        body["systemInstruction"] = {"parts": [{"text": system}]}
    # A thinking model spends part of the answer budget on its own thinking: with a long JSON the answer was then cut off in the middle (the log showed the text stopping after a comma).
    # The thinking is limited so the whole answer fits, and an answer that still ends by the token limit is asked again with a bigger budget and almost no thinking.
    think = int(env("GEMINI_THINKING", "1024") or 0)
    if json_mode and think >= 0:
        body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": think}
    cut = False
    last = ""
    t0 = time.time()
    for rnd in range(rounds):
        for m in models():
            for attempt in range(4):                           # (a setting dropped or a bigger limit asked for is one more try, not a lost one)
                if deadline and time.time() - t0 > deadline:
                    raise RuntimeError("Gemini took too long: " + (last or "no answer"))
                key = ks[_K["i"] % len(ks)]
                try:
                    r = S.post(BASE + m + ":generateContent", headers={"x-goog-api-key": key, "Content-Type": "application/json"}, data=json.dumps(body), timeout=timeout)
                except Exception as e:  # noqa: BLE001
                    last = str(e)[:150]
                    time.sleep(3)
                    continue
                if r.status_code == 400 and "thinking" in r.text.lower() and "thinkingConfig" in body["generationConfig"]:
                    body["generationConfig"].pop("thinkingConfig", None)       # this model has no thinking setting: asked again without it
                    last = f"{m}: no thinking setting"
                    continue
                if r.status_code == 200:
                    rj = r.json()
                    t = _text(rj)
                    LAST["finish"] = _finish(rj)
                    if t and LAST["finish"] == "MAX_TOKENS" and not cut:
                        cut = True                                             # the answer was cut off by the token limit: once more with a bigger limit and nearly no thinking
                        body["generationConfig"]["maxOutputTokens"] = 65000
                        if json_mode:
                            body["generationConfig"]["thinkingConfig"] = {"thinkingBudget": 256}
                        print(f"::warning::{m}: the answer was cut off by the token limit, asking again with a bigger limit")
                        continue
                    if t:
                        return t
                    last = "empty answer"
                    break
                last = f"{m}: {r.status_code} {r.text[:160]}"
                if r.status_code == 429 and len(ks) > 1:
                    _K["i"] += 1                      # another key
                    continue
                if r.status_code in (500, 502, 503, 504) and attempt == 0:
                    time.sleep(6)                     # a busy model: one short rest, then the next model
                    continue
                break
        if rnd < rounds - 1:
            print(f"::warning::all Gemini models busy - resting {20 * (rnd + 1)} s")
            time.sleep(20 * (rnd + 1))
    raise RuntimeError("Gemini failed: " + last)


def _repair_commas(body):
    """Fixes what models often get wrong in long JSON: a missing comma between two items (inserted where the parser stopped), trailing commas, '}{' side by side."""
    fixed = re.sub(r",\s*([}\]])", r"\1", body)
    fixed = re.sub(r"\}\s*\{", "},{", fixed)
    fixed = re.sub(r"\]\s*\[", "],[", fixed)
    for _ in range(200):
        try:
            return json.loads(fixed)
        except json.JSONDecodeError as e:
            if "delimiter" in e.msg or "Expecting ','" in e.msg:
                j = e.pos
                while j > 0 and fixed[j - 1].isspace():
                    j -= 1
                fixed = fixed[:j] + "," + fixed[j:]
                continue
            print("::warning::JSON still broken near:", repr(fixed[max(0, e.pos - 60):e.pos + 40]))
            break
    try:
        import json_repair                                    # optional helper package (pip install json-repair)
        return json.loads(json_repair.repair_json(body))
    except Exception:  # noqa: BLE001
        pass
    return json.loads(fixed)


def parse_json(text):
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", str(text).strip())
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON in answer")
    body = t[a:b + 1]
    try:
        return json.loads(body)
    except ValueError:
        return _repair_commas(body)

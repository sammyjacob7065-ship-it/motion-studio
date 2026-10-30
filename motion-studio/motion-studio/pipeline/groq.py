import json
import re
import time
from common import S, env

CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


_KEY = {"i": 0}


def _keys():
    """GROQ_API_KEY, then the optional extra keys GROQ_API_KEY_2 ... GROQ_API_KEY_6 (empty ones are ignored)."""
    out = []
    for n in ("GROQ_API_KEY", "GROQ_API_KEY_2", "GROQ_API_KEY_3", "GROQ_API_KEY_4", "GROQ_API_KEY_5", "GROQ_API_KEY_6"):
        v = env(n)
        if v and v not in out:
            out.append(v)
    if not out:
        env("GROQ_API_KEY", required=True)
    return out


def _key():
    ks = _keys()
    return ks[_KEY["i"] % len(ks)]


def _next_key():
    """Move to the next key. True if there is another key to use."""
    ks = _keys()
    if len(ks) < 2:
        return False
    _KEY["i"] = (_KEY["i"] + 1) % len(ks)
    return True


def _models(first):
    """The model to try first, then backups with more room (the free plan of a model can be small: gpt-oss is 8,000 tokens per minute)."""
    extra = [m.strip() for m in env("DIRECTOR_FALLBACKS", "openai/gpt-oss-20b,qwen/qwen3.8-27b").split(",") if m.strip()]
    out = []
    for m in [first] + extra:
        if m and m not in out:
            out.append(m)
    return out


def chat(messages, model=None, temperature=0.4, max_tokens=6000, json_mode=True, tries=5, reasoning=None):
    """Same as _chat_once, but when every model is out of room for this minute it rests a full minute and tries the whole list again (up to 3 rounds)."""
    for rnd in range(3):
        try:
            return _chat_once(messages, model, temperature, max_tokens, json_mode, tries, reasoning)
        except RuntimeError as e:
            if "429" not in str(e) or rnd == 2:
                raise
            print(f"::warning::all Groq models are busy for this minute - resting 65 s (round {rnd + 1} of 3)")
            time.sleep(65)


def _chat_once(messages, model=None, temperature=0.4, max_tokens=6000, json_mode=True, tries=5, reasoning=None):
    """One chat call with patient retries (free-tier rate limits are normal).
    If a model says the request is too big for its plan (413) or its daily tokens are used up, the next backup model is tried."""
    first = model or env("DIRECTOR_MODEL", "openai/gpt-oss-120b")
    last = ""
    models = _models(first) if not model or model == env("DIRECTOR_MODEL", "openai/gpt-oss-120b") else [model]
    for mi, model in enumerate(models):
        body = {"model": model, "messages": messages, "temperature": temperature,
                "max_tokens": max_tokens if model.startswith("openai/gpt-oss") else min(max_tokens, 8000)}
        if json_mode:
            body["response_format"] = {"type": "json_object"}
        if model.startswith("openai/gpt-oss"):
            body["reasoning_effort"] = reasoning or env("DIRECTOR_REASONING", "medium")
        switch = False
        rot = 0
        for i in range(tries):
            try:
                r = S.post(CHAT_URL, headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"}, data=json.dumps({k: v for k, v in body.items() if k != "_shrunk"}), timeout=180)
            except Exception as e:  # noqa: BLE001
                last = str(e)
                time.sleep(4 * (i + 1))
                continue
            if r.status_code == 200:
                try:
                    out = r.json()["choices"][0]["message"]["content"] or ""
                    _next_key()                    # spread the work: the next request uses the next key
                    return out
                except Exception:  # noqa: BLE001
                    last = "empty answer"
                    continue
            last = f"{r.status_code} {r.text[:200]}"
            low = r.text.lower()
            if r.status_code == 429 and rot < len(_keys()) - 1 and _next_key():
                rot += 1                           # this key has no room now (per minute or per day): use the next key at once
                continue
            if r.status_code == 413:
                m2 = re.search(r"Limit (\d+), Requested (\d+)", r.text)
                if m2 and not body.get("_shrunk"):
                    over = int(m2.group(2)) - int(m2.group(1))
                    if 0 < over < body["max_tokens"] - 1000:          # the answer space counted too: ask for a shorter answer and try again
                        body["max_tokens"] = body["max_tokens"] - over - 300
                        body["_shrunk"] = True
                        continue
            if r.status_code == 413 or (r.status_code == 429 and ("per day" in low or "tpd" in low)) or r.status_code == 404 or "decommission" in low or "model_not_found" in low:
                switch = True                      # this model cannot do this request: try the next one
                break
            if r.status_code == 429 and i >= 1 and mi < len(models) - 1:
                switch = True                      # still no room after one rest: the next model has its own minute budget
                break
            if r.status_code == 429:
                wait = 12.0
                m = re.search(r"try again in ([0-9.]+)s", r.text)
                if m:
                    wait = min(60.0, float(m.group(1)) + 1.5)
                time.sleep(wait)
            elif r.status_code >= 500:
                time.sleep(5 * (i + 1))
            elif r.status_code == 400 and json_mode and "json" in low:
                body.pop("response_format", None)  # some models cannot do json mode: retry plain
            else:
                break
        if switch and mi < len(models) - 1:
            print(f"::warning::{model} cannot take this request ({last[:90]}) - trying {models[mi + 1]}")
            continue
        break
    raise RuntimeError("Groq failed: " + last)


_VIS = {"model": None, "done": False}


def vision_model():
    """A Groq model that can look at pictures. Tries VISION_MODEL first, then every model on the account that looks like a vision model; the first that answers a tiny picture test is used (cached). None when there is none."""
    if _VIS["done"]:
        return _VIS["model"]
    _VIS["done"] = True
    import base64
    import io
    try:
        from PIL import Image
        buf = io.BytesIO()
        Image.new("RGB", (64, 64), (220, 30, 30)).save(buf, "JPEG")
        b64 = base64.b64encode(buf.getvalue()).decode()
    except Exception:  # noqa: BLE001
        return None
    cands = []
    first = env("VISION_MODEL")
    if first:
        cands.append(first)
    try:
        r = S.get("https://api.groq.com/openai/v1/models", headers={"Authorization": "Bearer " + _key()}, timeout=30)
        for m in r.json().get("data", []):
            mid = str(m.get("id", ""))
            if re.search(r"vision|scout|maverick|[-/]vl|llava|pixtral|gemma-?[34]|qwen3\.?\d*-?vl", mid, re.I) and not re.search(r"whisper|guard|tts|orpheus|embed", mid, re.I) and mid not in cands:
                cands.append(mid)
    except Exception:  # noqa: BLE001
        pass
    for mid in cands[:8]:
        try:
            r = S.post(CHAT_URL, headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"}, timeout=60,
                       data=json.dumps({"model": mid, "max_tokens": 8, "messages": [{"role": "user", "content": [{"type": "text", "text": "One word: the colour of this picture?"}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]}))
            if r.status_code == 200:
                _VIS["model"] = mid
                break
        except Exception:  # noqa: BLE001
            continue
    return _VIS["model"]


def describe_frame(path, ask, model=None):
    """One picture + a question to a Groq vision model. Returns the answer text (or '' when no vision model works)."""
    import base64
    m = model or vision_model()
    if not m:
        return ""
    with open(path, "rb") as f:
        b64 = base64.b64encode(f.read()).decode()
    try:
        r = S.post(CHAT_URL, headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"}, timeout=90,
                   data=json.dumps({"model": m, "max_tokens": 300, "temperature": 0.2, "messages": [{"role": "user", "content": [{"type": "text", "text": ask}, {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]}))
        if r.status_code == 200:
            _next_key()
            return r.json()["choices"][0]["message"]["content"] or ""
    except Exception:  # noqa: BLE001
        pass
    return ""


def parse_json(text):
    """Pulls the first JSON object out of a model answer."""
    if not text:
        raise ValueError("empty answer")
    t = text.strip()
    t = re.sub(r"^```(?:json)?\s*|\s*```$", "", t)
    a, b = t.find("{"), t.rfind("}")
    if a < 0 or b <= a:
        raise ValueError("no JSON in answer")
    return json.loads(t[a:b + 1])


def transcribe_words(path, language=None):
    """Whisper with word times. Returns (words, full_text, duration). words = [{w, s, e}]."""
    def once():
        with open(path, "rb") as f:
            data = {"model": "whisper-large-v3-turbo", "response_format": "verbose_json", "timestamp_granularities[]": ["word", "segment"]}
            if language:
                data["language"] = language
            r = S.post(STT_URL, headers={"Authorization": "Bearer " + _key()}, files={"file": f}, data=data, timeout=300)
        return r
    last = ""
    for i in range(4):
        r = once()
        if r.status_code == 200:
            _next_key()                            # spread the work over the keys
            j = r.json()
            words = [{"w": str(w.get("word", "")).strip(), "s": round(float(w.get("start", 0)), 3), "e": round(float(w.get("end", 0)), 3)} for w in j.get("words", []) if str(w.get("word", "")).strip()]
            return words, j.get("text", ""), float(j.get("duration") or 0)
        last = f"{r.status_code} {r.text[:150]}"
        if r.status_code == 429 and _next_key():
            continue                               # try the next key at once
        time.sleep(8 * (i + 1) if r.status_code == 429 else 3)
    raise RuntimeError("Whisper failed: " + last)

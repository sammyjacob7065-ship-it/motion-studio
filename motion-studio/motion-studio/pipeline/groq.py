import json
import re
import time
from common import S, env

CHAT_URL = "https://api.groq.com/openai/v1/chat/completions"
STT_URL = "https://api.groq.com/openai/v1/audio/transcriptions"


def _key():
    return env("GROQ_API_KEY", required=True)


def chat(messages, model=None, temperature=0.4, max_tokens=6000, json_mode=True, tries=5, reasoning=None):
    """One chat call with patient retries (free-tier rate limits are normal)."""
    model = model or env("DIRECTOR_MODEL", "openai/gpt-oss-120b")
    body = {"model": model, "messages": messages, "temperature": temperature, "max_tokens": max_tokens}
    if json_mode:
        body["response_format"] = {"type": "json_object"}
    if model.startswith("openai/gpt-oss"):
        body["reasoning_effort"] = reasoning or env("DIRECTOR_REASONING", "medium")
    last = ""
    for i in range(tries):
        try:
            r = S.post(CHAT_URL, headers={"Authorization": "Bearer " + _key(), "Content-Type": "application/json"}, data=json.dumps(body), timeout=180)
        except Exception as e:  # noqa: BLE001
            last = str(e)
            time.sleep(4 * (i + 1))
            continue
        if r.status_code == 200:
            try:
                return r.json()["choices"][0]["message"]["content"] or ""
            except Exception:  # noqa: BLE001
                last = "empty answer"
                continue
        last = f"{r.status_code} {r.text[:200]}"
        if r.status_code == 429:
            wait = 12.0
            m = re.search(r"try again in ([0-9.]+)s", r.text)
            if m:
                wait = min(60.0, float(m.group(1)) + 1.5)
            time.sleep(wait)
        elif r.status_code >= 500:
            time.sleep(5 * (i + 1))
        elif r.status_code == 400 and json_mode and "json" in r.text.lower():
            body.pop("response_format", None)  # some models cannot do json mode: retry plain
        else:
            break
    raise RuntimeError("Groq failed: " + last)


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
            j = r.json()
            words = [{"w": str(w.get("word", "")).strip(), "s": round(float(w.get("start", 0)), 3), "e": round(float(w.get("end", 0)), 3)} for w in j.get("words", []) if str(w.get("word", "")).strip()]
            return words, j.get("text", ""), float(j.get("duration") or 0)
        last = f"{r.status_code} {r.text[:150]}"
        time.sleep(8 * (i + 1) if r.status_code == 429 else 3)
    raise RuntimeError("Whisper failed: " + last)

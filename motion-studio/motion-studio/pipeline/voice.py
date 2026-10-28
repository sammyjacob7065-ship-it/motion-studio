"""Voice-over: your Edge-TTS server (same Nigerian voices as the movie factory), then Whisper for word times."""
import os
import re
import subprocess
import threading
import time
from common import S, env
import groq
import pronounce


def _chunks(text, limit=850):
    sents = re.split(r"(?<=[.!?])\s+", text.strip())
    out, cur = [], ""
    for s in sents:
        if len(cur) + len(s) + 1 > limit and cur:
            out.append(cur.strip())
            cur = ""
        cur += s + " "
    if cur.strip():
        out.append(cur.strip())
    return out or [text]


def _speak(text, dest, voice, speed, base):
    last = ""
    for i in range(5):
        try:
            r = S.post(base + "/v1/audio/speech", json={"input": text, "voice": voice, "response_format": "mp3", "speed": speed}, timeout=150)
            if r.status_code == 200 and len(r.content) > 2000:
                with open(dest, "wb") as f:
                    f.write(r.content)
                return
            last = f"{r.status_code} {r.text[:100]}"
        except Exception as e:  # noqa: BLE001
            last = str(e)[:100]
        time.sleep(8 * (i + 1))  # the free server may be asleep: give it time to wake
    raise RuntimeError("Voice server did not answer: " + last)


_WAKE = {"done": False}


def _base():
    return env("TTS_URL", "https://openai-edge-tts-9mrp.onrender.com").rstrip("/")


def wake():
    """Wake the free voice server in the background at the START of the job (it sleeps when idle), so it is ready
    by the time the voice is needed. Never blocks and never raises."""
    base = _base()

    def go():
        for _ in range(40):
            try:
                r = S.get(base + "/v1/models", timeout=45)
                if r.status_code < 500:
                    break
            except Exception:  # noqa: BLE001
                pass
            time.sleep(5)
        _WAKE["done"] = True

    try:
        _WAKE["done"] = False
        threading.Thread(target=go, daemon=True).start()
    except Exception:  # noqa: BLE001
        _WAKE["done"] = True


def _wait_awake(limit=150):
    t0 = time.time()
    while not _WAKE["done"] and time.time() - t0 < limit:
        time.sleep(1)


def generate(text, out_path, workdir):
    text = pronounce.apply(text)       # only the voice hears the sound-spellings of hard names
    _wait_awake()                      # the wake-up started at the beginning of the job
    base = _base()
    voice = env("TTS_VOICE", "en-NG-AbeoNeural")
    speed = float(env("TTS_SPEED", "1.0"))
    parts = []
    for i, c in enumerate(_chunks(text)):
        p = os.path.join(workdir, f"tts_{i}.mp3")
        _speak(c, p, voice, speed, base)
        parts.append(p)
    if len(parts) == 1:
        os.replace(parts[0], out_path)
        return out_path
    lst = os.path.join(workdir, "tts_list.txt")
    with open(lst, "w") as f:
        for p in parts:
            f.write(f"file '{p}'\n")
    r = subprocess.run(["ffmpeg", "-y", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "libmp3lame", "-b:a", "192k", out_path], capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("could not join voice parts: " + r.stderr[-150:])
    return out_path


def words_for(path):
    """Word times for a voice file. Long files are split into 10-minute pieces."""
    import assets
    dur = assets.duration_of(path)
    if dur <= 600:
        w, text, _ = groq.transcribe_words(path)
        return w, text, dur
    words, texts = [], []
    off = 0.0
    while off < dur:
        piece = path + f".p{int(off)}.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(off), "-t", "600", "-i", path, "-ac", "1", "-ar", "16000", "-b:a", "48k", piece], check=True)
        w, t, _ = groq.transcribe_words(piece)
        words += [{"w": x["w"], "s": round(x["s"] + off, 3), "e": round(x["e"] + off, 3)} for x in w]
        texts.append(t)
        off += 600
    return words, " ".join(texts), dur

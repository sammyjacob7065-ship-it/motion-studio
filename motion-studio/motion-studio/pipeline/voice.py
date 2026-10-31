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


def _setting(name, default):
    """An unset GitHub secret arrives as an empty text: that counts as 'not set', whatever version of common.py is installed."""
    v = str(os.environ.get(name) or "").strip()
    return v or default


def _base():
    return _setting("TTS_URL", "https://openai-edge-tts-9mrp.onrender.com").rstrip("/")


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


def _sh(cmd):
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("ffmpeg: " + r.stderr[-160:])
    return r


def _dur(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path], capture_output=True, text=True)
    try:
        return float(r.stdout.strip())
    except ValueError:
        return 0.0


def _tight(src, dst, question=False):
    """One spoken sentence -> a clean wav: the engine's own long silences at the start and end are cut (the PAUSE between sentences is set by the studio, not by the engine),
    and a question gets a rising tone on its last words (the voice reads '?' like a comma, so the lift is made here)."""
    trim = "silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.02,areverse,silenceremove=start_periods=1:start_threshold=-48dB:start_silence=0.02,areverse"
    tmp = dst + ".t.wav"
    _sh(["ffmpeg", "-y", "-loglevel", "error", "-i", src, "-ac", "1", "-ar", "24000", "-af", trim, tmp])
    d = _dur(tmp)
    lift = float(_setting("QUESTION_LIFT", "1.16"))
    if question and d > 0.8 and lift > 1.0:
        tail = min(0.55, d * 0.35)
        fc = (f"[0:a]atrim=0:{d - tail:.3f},asetpts=N/SR/TB[a];"
              f"[0:a]atrim={d - tail:.3f},asetpts=N/SR/TB,asetrate={int(24000 * lift)},aresample=24000,atempo={1 / lift:.4f}[b];[a][b]concat=n=2:v=0:a=1[o]")
        _sh(["ffmpeg", "-y", "-loglevel", "error", "-i", tmp, "-filter_complex", fc, "-map", "[o]", "-ac", "1", "-ar", "24000", dst])
        os.remove(tmp)
    else:
        os.replace(tmp, dst)
    return dst


def _pause_after(sentence):
    base = float(_setting("VOICE_PAUSE", "0.26"))          # seconds of silence after a full stop; a comma inside a sentence keeps the engine's own short pause
    t = sentence.rstrip()
    if t.endswith(("...", "\u2026")):
        return base * 2.2                                  # "..." = a deliberate long pause
    if t.endswith("?"):
        return base * 1.15
    if t.endswith("!"):
        return base * 0.9
    return base


def _sentences(text):
    out = []
    for para in re.split(r"\n\s*\n", text.strip()):
        out += [s.strip() for s in re.split(r"(?<=[.!?])\s+", " ".join(para.split())) if s.strip()]
        if out:
            out[-1] = out[-1] + ("" if out[-1].rstrip().endswith(("...", "\u2026")) else "")
    return out


def generate(text, out_path, workdir, speed=None):
    text = pronounce.apply(text)       # only the voice hears the sound-spellings of hard names
    _wait_awake()                      # the wake-up started at the beginning of the job
    base = _base()
    voice = _setting("TTS_VOICE", "en-NG-AbeoNeural")
    speed = float(speed) if speed else float(_setting("TTS_SPEED", "1.0"))
    if _setting("VOICE_STYLE", "tight") != "plain":
        try:
            return _generate_tight(text, out_path, workdir, voice, speed, base)
        except Exception as e:  # noqa: BLE001
            print("::warning::sentence-by-sentence voice failed, using the plain voice:", str(e)[:140])
    return _generate_plain(text, out_path, workdir, voice, speed, base)


def _generate_tight(text, out_path, workdir, voice, speed, base):
    from concurrent.futures import ThreadPoolExecutor
    sents = _sentences(text)
    if not sents:
        raise RuntimeError("no text")
    raw = [os.path.join(workdir, f"sent_{i}.mp3") for i in range(len(sents))]

    def one(i):
        _speak(sents[i], raw[i], voice, speed, base)
        return _tight(raw[i], os.path.join(workdir, f"sent_{i}.wav"), question=sents[i].rstrip().endswith("?"))
    with ThreadPoolExecutor(max_workers=3) as ex:
        wavs = list(ex.map(one, range(len(sents))))
    lst = os.path.join(workdir, "tight_list.txt")
    with open(lst, "w") as f:
        for i, w in enumerate(wavs):
            f.write(f"file '{w}'\n")
            if i < len(wavs) - 1:
                gap = os.path.join(workdir, f"gap_{i}.wav")
                _sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "anullsrc=r=24000:cl=mono", "-t", f"{_pause_after(sents[i]):.3f}", gap])
                f.write(f"file '{gap}'\n")
    _sh(["ffmpeg", "-y", "-loglevel", "error", "-f", "concat", "-safe", "0", "-i", lst, "-c:a", "libmp3lame", "-b:a", "192k", out_path])
    return out_path


def _generate_plain(text, out_path, workdir, voice, speed, base):
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

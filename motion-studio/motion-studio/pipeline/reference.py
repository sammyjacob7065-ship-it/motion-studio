"""Reference department. The client sends a motion video he likes; this reads it and saves a short 'spec' (structure, pace, look, what to provide).
Reading levels (first that works wins):  1) Gemini watches the video   2) Groq backup: sampled frames (vision model) + speech (Whisper) + facts   3) facts only (cuts, length, colours, beat), said honestly.
Run:  python pipeline/reference.py <chat_id>      (reads motion/<chat>/reference/ref.mp4, writes motion/<chat>/reference/spec.json, tells the client on Telegram)"""
import json
import os
import re
import subprocess
import sys

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import beats  # noqa: E402
import gemini  # noqa: E402
import groq  # noqa: E402
from common import env  # noqa: E402

SYSTEM = ("You are a senior motion designer reading a reference video for a studio that must build a NEW video with the same structure, pace and feel. "
          "Never copy the reference's brand, words or pictures: describe structure and style only. Answer ONLY with JSON.")
SCHEMA = ('{"summary":"2 sentences: what the video is and how it feels","aspect":"9:16|16:9|1:1","pace":"slow|medium|fast","style":"look: colours, type, effects, camera in one sentence",'
          '"music":"none|calm|upbeat|cinematic...","voiceover":true,'
          '"scenes":[{"start":0.0,"end":3.0,"what":"what is shown (kind of picture/shot, not the brand)","text_on_screen":"style of the text and what it says in general","motion":"camera / animation","transition":"how it changes to the next"}],'
          '"needs":{"pictures":6,"voice_script_words":60,"logo":true,"texts":["brand name","phone number"]},"notes":"anything else worth copying"}')


def facts(path):
    """Plain measurements: length, size, scene cuts, colours, beat. No AI."""
    import assets
    f = {"duration": 0.0, "aspect": "9:16", "cuts": [], "palette": [], "beat": None}
    try:
        info = assets.analyze_basic(path) if hasattr(assets, "analyze_basic") else None
    except Exception:  # noqa: BLE001
        info = None
    try:
        pr = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=width,height:format=duration", "-of", "json", path], capture_output=True, text=True)
        j = json.loads(pr.stdout or "{}")
        f["duration"] = round(float((j.get("format") or {}).get("duration") or 0), 2)
        w, h = (j.get("streams") or [{}])[0].get("width", 0), (j.get("streams") or [{}])[0].get("height", 0)
        if w and h:
            r = w / h
            f["aspect"] = "9:16" if r < 0.8 else ("1:1" if r < 1.2 else "16:9")
    except Exception:  # noqa: BLE001
        pass
    try:   # scene cuts
        p = subprocess.run(["ffmpeg", "-i", path, "-vf", "select='gt(scene,0.28)',showinfo", "-an", "-f", "null", "-"], capture_output=True, text=True)
        cuts = [round(float(m), 2) for m in re.findall(r"pts_time:([\d.]+)", p.stderr)]
        f["cuts"] = [c for i, c in enumerate(cuts) if i == 0 or c - cuts[i - 1] > 0.4][:60]
    except Exception:  # noqa: BLE001
        pass
    try:   # main colours of a few frames
        from PIL import Image
        cols = {}
        for i in range(5):
            t = f["duration"] * (i + 0.5) / 5
            out = f"/tmp/_refc{i}.png"
            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", str(t), "-i", path, "-frames:v", "1", "-vf", "scale=48:-1", out], check=True)
            im = Image.open(out).convert("RGB").quantize(4).convert("RGB")
            for c, n in im.getcolors(5000) or []:
                k = tuple(v // 32 * 32 + 16 for v in n) if isinstance(n, tuple) else None
                if k:
                    cols[k] = cols.get(k, 0) + c
        f["palette"] = ["#%02x%02x%02x" % k for k, _ in sorted(cols.items(), key=lambda kv: -kv[1])[:5]]
    except Exception:  # noqa: BLE001
        pass
    try:
        f["beat"] = beats.analyze(path)
    except Exception:  # noqa: BLE001
        pass
    return f


def frames(path, dur, n=8):
    out = []
    from PIL import Image  # noqa: F401
    for i in range(n):
        t = max(0.0, min(dur - 0.1, dur * (i + 0.5) / n))
        p = f"/tmp/_reff{i}.jpg"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-ss", f"{t:.2f}", "-i", path, "-frames:v", "1", "-vf", "scale=512:-2", "-q:v", "5", p], check=True)
        out.append((t, p))
    return out


def speech(path):
    """What is said in the reference (Groq Whisper). ('' when nothing / failed)"""
    try:
        wav = "/tmp/_refs.mp3"
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", path, "-vn", "-ac", "1", "-ar", "16000", "-b:a", "48k", wav], check=True)
        if os.path.getsize(wav) < 4000:
            return "", []
        w, text, _ = groq.transcribe_words(wav)
        return (text or "").strip(), w
    except Exception as e:  # noqa: BLE001
        print("speech not read:", str(e)[:100])
        return "", []


def _fact_text(f, said):
    return (f"MEASURED FACTS: length {f['duration']}s, shape {f['aspect']}, scene cuts at (s): {f['cuts']}, main colours {f['palette']}"
            + (f", music about {f['beat']['bpm']:.0f} BPM" if f.get("beat") else ", no clear music beat")
            + (f". SPEECH IN THE VIDEO: \"{said[:1500]}\"" if said else ". No speech heard.") + "\n")


def by_gemini(path, f, said):
    video = open(path, "rb").read()
    if len(video) > 19 * 1024 * 1024:
        raise RuntimeError("video too big for Gemini inline")
    ans = gemini.parse_json(gemini.generate(_fact_text(f, said) + "Watch the video and fill this JSON (scenes in order, times in seconds):\n" + SCHEMA, system=SYSTEM, video=video, temperature=0.2, rounds=2))
    return ans


def by_groq(path, f, said):
    shots = frames(path, f["duration"] or 10, 8)
    notes = []
    for t, p in shots:
        d = groq.describe_frame(p, "Describe this video frame for a motion designer in 2 short sentences: what picture/shot, any text on screen and its style, colours, effects. Do not guess brand names.")
        if d:
            notes.append(f"at {t:.1f}s: {d.strip()}")
    if not notes:
        raise RuntimeError("no Groq vision model answered")
    user = (_fact_text(f, said) + "FRAME NOTES:\n" + "\n".join(notes) + "\nFrom these notes and facts write the reference reading as JSON (scenes in order, times in seconds; use the cut times for scene starts):\n" + SCHEMA)
    return groq.parse_json(groq.chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], temperature=0.2, max_tokens=5000, reasoning="medium"))


def from_facts(f, said):
    cuts = [0.0] + [c for c in f["cuts"] if c < f["duration"] - 0.5]
    scenes = [{"start": c, "end": (cuts[i + 1] if i + 1 < len(cuts) else f["duration"]), "what": "unknown (could not look inside the video)", "text_on_screen": "", "motion": "", "transition": "cut"} for i, c in enumerate(cuts)]
    avg = f["duration"] / max(1, len(scenes))
    return {"duration": f["duration"], "summary": f"A {f['duration']:.0f}s {f['aspect']} video with {len(scenes)} scenes.", "aspect": f["aspect"], "pace": "fast" if avg < 2.5 else ("medium" if avg < 5 else "slow"),
            "style": "unknown; colours " + ", ".join(f["palette"]), "music": "music with a beat" if f.get("beat") else "unknown", "voiceover": bool(said), "scenes": scenes,
            "needs": {"pictures": len(scenes), "voice_script_words": int(len(said.split()) or f["duration"] * 2.2), "logo": True, "texts": ["brand name", "phone number"]}, "notes": "Only measured facts: the content of the scenes could not be read."}


def read(path):
    """Returns (spec, level) where level is 'gemini' | 'groq' | 'facts'."""
    f = facts(path)
    said, _w = speech(path)
    errs = []
    if gemini.available():
        try:
            return _fix(by_gemini(path, f, said), f), "gemini"
        except Exception as e:  # noqa: BLE001
            errs.append("Gemini: " + str(e)[:100])
            print("::warning::reference by Gemini failed:", errs[-1])
    try:
        return _fix(by_groq(path, f, said), f), "groq"
    except Exception as e:  # noqa: BLE001
        errs.append("Groq: " + str(e)[:100])
        print("::warning::reference by Groq failed:", errs[-1])
    spec = from_facts(f, said)
    spec["why_facts_only"] = errs
    return spec, "facts"


def _fix(spec, f):
    if not isinstance(spec, dict) or not isinstance(spec.get("scenes"), list) or not spec["scenes"]:
        raise RuntimeError("answer had no scenes")
    spec.setdefault("aspect", f["aspect"])
    spec["duration"] = f["duration"]
    n = spec.setdefault("needs", {})
    n.setdefault("pictures", len(spec["scenes"]))
    n.setdefault("voice_script_words", int(f["duration"] * 2.3))
    n.setdefault("logo", True)
    n.setdefault("texts", [])
    return spec


def ask_text(spec, level):
    n = spec["needs"]
    head = {"gemini": "✅ Reference saved and read (Gemini).", "groq": "✅ Reference saved and read (Groq backup, from sampled frames + speech).",
            "facts": "✅ Reference saved. I could only measure it (cuts, length, colours) - I could not look inside, so I will copy its rhythm, not its content."}[level]
    texts = ", ".join(str(t) for t in (n.get("texts") or [])) or "brand name, phone number"
    return (f"{head}\n\n{spec.get('summary', '')}\n\n"
            f"Structure: {len(spec['scenes'])} scenes, {spec['duration']:.0f}s, {spec.get('aspect', '9:16')}, pace {spec.get('pace', '?')}.\n\n"
            "To make yours, send now (then your prompt or /go):\n"
            f"- {n.get('pictures')} pictures (or tell me to generate them)\n"
            f"- voice script of about {n.get('voice_script_words')} words (or your script file)\n"
            + ("- your logo (send as File)\n" if n.get("logo") else "")
            + f"- your texts: {texts}\n\n"
            "I copy the structure, pace and feel - never the other creator's words, brand or pictures. /noreference clears it.")


def main(chat):
    from sb import Store
    from tg import Telegram
    store = Store()
    tg = Telegram(chat)
    base = f"motion/{chat}/reference"
    work = os.path.abspath(f"work/ref_{chat}")
    os.makedirs(work, exist_ok=True)
    try:
        path = store.download(f"{base}/ref.mp4", os.path.join(work, "ref.mp4"))
        spec, level = read(path)
        spec["level"] = level
        store.put_json(f"{base}/spec.json", {"spec": spec, "created": __import__("time").time(), "used": False})
        tg.send(ask_text(spec, level))
    except Exception as e:  # noqa: BLE001
        tg.send("⚠️ I could not read the reference: " + str(e)[:200] + "\nSend the video again with /reference.")
        raise


if __name__ == "__main__":
    main(sys.argv[1])

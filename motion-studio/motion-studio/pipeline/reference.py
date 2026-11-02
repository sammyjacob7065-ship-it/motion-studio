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
    head = {"gemini": "✅ Reference saved and read (Gemini).", "groq": "✅ Reference saved and read (Groq backup, from sampled frames + speech).",
            "facts": "✅ Reference saved. I could only measure it (cuts, length, colours) - I could not look inside, so I will copy its rhythm, not its content."}[level]
    return (f"{head}\n\n{spec.get('summary', '')}\n\n"
            f"Structure: {len(spec['scenes'])} scenes, {spec['duration']:.0f}s, {spec.get('aspect', '9:16')}, pace {spec.get('pace', '?')}.\n\n"
            "Now tell me, in your own words:\n"
            "1) What is this for? The brand and the product (for example: a coffee brand, Milo, my clothing brand, a phone, a restaurant).\n"
            "2) Do you want it EXACT (same structure, timing and style) or WITH CHANGES? If changes, say what to change.\n\n"
            "We can talk as much as you like, ask me anything about it. When you are happy, send your script, or send /make and I write it from our chat.\n"
            "I copy the structure, pace and feel, never the other creator's words, brand or pictures. /noreference clears it.")


CHAT_SYSTEM = ("You are the reference consultant of a motion-graphics ad studio, talking with the client on Telegram. The client liked a reference video and wants a NEW video made with its structure, pace and feel, for HIS OWN brand and product. "
               "You know the reference only through the reading below. Be smart, short, friendly and practical: plain words, short paragraphs, no markdown symbols, at most about 900 characters. "
               "Find out two things: (1) the brand and the product the new video is for, (2) EXACT (same number of scenes, same timing, same camera moves, text animation and transitions) or WITH CHANGES (what to change, what to keep). "
               "If the client asks something else about the reference or the plan, answer it. Never copy the reference's brand, words, pictures or logo: only structure and style. "
               "Once the product is known, go through the reference scenes: say which scenes suit the product as they are, and which do not (for example a cap pop does not suit a shirt) and what you will show instead. "
               "Once the product is known, give the exact list of what the client should send, tailored to the product (specific pictures, logo as File, texts, voice script words). Give the list once, then only update it when something changes. "
               "End with the next step: send the script (or a .txt file), or send /make and the studio writes it from this chat. "
               "Reply with JSON only.")
CHAT_SCHEMA = ('{"reply":"what you say to the client","agreed":{"brand":"","product":"","mode":"exact|changes|unknown","changes":["each change the client asked for"],"keep":["what must stay the same"],'
               '"scene_plan":[{"n":1,"show":"what scene n shows for the new product","note":"kept as the reference | changed because ..."}],"extra":"anything else the client said that matters"},'
               '"needs":{"items":["specific things to send"],"voice_script_words":60},"ready":true,'
               '"brief":"ONLY when brand, product and mode are known: a complete prompt for the studio to make the whole video: the brand and product, the exact or changed structure scene by scene, the mood, a voice-over written in full (about voice_script_words words) in simple natural English with a hook first, the look, and the end line. Otherwise empty."}')


def _agreed(rf):
    return (rf.get("spec") or {}).get("agreed") or {}


def chat_turn(rf, user_text):
    """One turn of the conversation. Returns (reply text, updated agreed dict, brief text or '')."""
    spec = rf.get("spec") or {}
    hist = rf.get("history") or []
    ref = {k: spec.get(k) for k in ("summary", "duration", "aspect", "pace", "style", "music", "voiceover", "scenes", "needs", "notes")}
    convo = "\n".join(f"{'CLIENT' if h.get('who') == 'c' else 'YOU'}: {h.get('text', '')}" for h in hist[-14:])
    prompt = (f"REFERENCE READING:\n{json.dumps(ref, separators=(',', ':'))[:7000]}\n\nWHAT IS AGREED SO FAR:\n{json.dumps(_agreed(rf), separators=(',', ':'))}\n\n"
              f"CONVERSATION SO FAR:\n{convo or '(nothing yet)'}\n\nNEW MESSAGE FROM THE CLIENT:\n{user_text}\n\nAnswer with this JSON (update \"agreed\" with everything known so far, keep earlier facts):\n{CHAT_SCHEMA}")
    ans, err = None, ""
    if gemini.available():
        try:
            ans = gemini.parse_json(gemini.generate(prompt, system=CHAT_SYSTEM, temperature=0.4, rounds=2))
        except Exception as e:  # noqa: BLE001
            err = "Gemini: " + str(e)[:100]
            print("::warning::reference chat by Gemini failed:", err)
    if not isinstance(ans, dict):
        try:
            ans = groq.parse_json(groq.chat([{"role": "system", "content": CHAT_SYSTEM}, {"role": "user", "content": prompt}], temperature=0.4, max_tokens=5000, reasoning="medium"))
        except Exception as e:  # noqa: BLE001
            err += " Groq: " + str(e)[:100]
            print("::warning::reference chat by Groq failed:", str(e)[:100])
    if not isinstance(ans, dict) or not str(ans.get("reply", "")).strip():
        return None, _agreed(rf), ""
    ag = ans.get("agreed") if isinstance(ans.get("agreed"), dict) else {}
    old = _agreed(rf)
    merged = {**old, **{k: v for k, v in ag.items() if v not in (None, "", [], {})}}
    if str(merged.get("mode", "")).lower() not in ("exact", "changes"):
        merged["mode"] = "unknown"
    needs = ans.get("needs") if isinstance(ans.get("needs"), dict) else {}
    if needs:
        merged["needs"] = needs
    brief = str(ans.get("brief") or "").strip() if (merged.get("product") and merged["mode"] != "unknown") else ""
    if brief:
        merged["brief"] = brief
    return str(ans["reply"]).strip()[:1500], merged, brief


def extra_text(ref):
    """The reference part of the studio's instructions. Plain facts for the director: the reading, the client's agreement (exact or changes, his product) and the scene plan."""
    lines = "\n".join(f"  {i + 1}. {sc.get('start', 0):.1f}-{sc.get('end', 0):.1f}s: {sc.get('what', '')} | text: {sc.get('text_on_screen', '')} | motion: {sc.get('motion', '')} | change: {sc.get('transition', '')}" for i, sc in enumerate(ref["scenes"][:30]))
    ag = ref.get("agreed") or {}
    mode = str(ag.get("mode", "unknown")).lower()
    out = (f"STYLE REFERENCE (a video the client likes; its length {ref.get('duration', 0):.0f}s, pace {ref.get('pace', '')}, look: {ref.get('style', '')}, music: {ref.get('music', '')}). ")
    if mode == "exact":
        out += (f"The client wants it EXACT: build the NEW video with EXACTLY the same structure: {len(ref['scenes'])} scenes, each scene starting and ending at the same times (within a quarter of a second), the same kind of text animation, the same camera moves, the same transitions, the same pace and look. ")
    elif mode == "changes":
        out += (f"The client wants the same structure WITH CHANGES: keep everything the same ({len(ref['scenes'])} scenes, rhythm, text animation, camera moves, transitions) except what the changes below ask. ")
    else:
        out += f"Build the NEW video with the SAME structure: about {len(ref['scenes'])} scenes, the same rhythm (scene lengths close to these), the same kind of text animation, camera moves and transitions. "
    out += "Use ONLY the client's own words, brand, pictures and logo; never copy anything written in the reference.\n"
    if ag.get("brand") or ag.get("product"):
        out += f"THE NEW VIDEO IS FOR: brand {ag.get('brand') or '?'}, product {ag.get('product') or '?'}.\n"
    if ag.get("changes"):
        out += "CHANGES THE CLIENT ASKED FOR:\n" + "\n".join(f"  - {c}" for c in ag["changes"][:12]) + "\n"
    if ag.get("keep"):
        out += "KEEP THE SAME: " + "; ".join(str(k) for k in ag["keep"][:12]) + "\n"
    if ag.get("scene_plan"):
        out += "SCENE PLAN FOR THE CLIENT'S PRODUCT (follow it):\n" + "\n".join(f"  scene {p.get('n')}: {p.get('show', '')} ({p.get('note', '')})" for p in ag["scene_plan"][:30] if isinstance(p, dict)) + "\n"
    if ag.get("extra"):
        out += "ALSO: " + str(ag["extra"])[:500] + "\n"
    return out + "REFERENCE SCENES:\n" + lines + "\n"


def _now_ms():
    return int(__import__("time").time() * 1000)


def main(chat, mode="read"):
    from sb import Store
    from tg import Telegram
    store = Store()
    tg = Telegram(chat)
    base = f"motion/{chat}/reference"
    if mode == "chat":
        return chat_main(store, tg, base)
    work = os.path.abspath(f"work/ref_{chat}")
    os.makedirs(work, exist_ok=True)
    try:
        path = store.download(f"{base}/ref.mp4", os.path.join(work, "ref.mp4"))
        spec, level = read(path)
        spec["level"] = level
        spec["agreed"] = {"brand": "", "product": "", "mode": "unknown", "changes": [], "keep": [], "scene_plan": [], "extra": ""}
        store.put_json(f"{base}/spec.json", {"spec": spec, "created": _now_ms(), "used": False, "chat": True, "history": [], "seen": []})
        store.put_json(f"{base}/inbox.json", {"msgs": []})
        tg.send(ask_text(spec, level))
    except Exception as e:  # noqa: BLE001
        tg.send("⚠️ I could not read the reference: " + str(e)[:200] + "\nSend the video again with /reference.")
        raise


def chat_main(store, tg, base):
    """The client wrote while a reference is open: read what is new in the inbox, answer, keep what was agreed."""
    rf = store.get_json(f"{base}/spec.json") or {}
    if not rf.get("spec") or rf.get("used"):
        return
    inbox = store.get_json(f"{base}/inbox.json") or {"msgs": []}
    seen = set(rf.get("seen") or [])
    pending = [m for m in inbox.get("msgs", []) if m.get("id") not in seen and str(m.get("text", "")).strip()]
    if not pending:
        return
    rf["seen"] = sorted(seen | {m["id"] for m in pending})[-200:]
    store.put_json(f"{base}/spec.json", rf)                     # claimed: a second worker does not answer the same message
    text = "\n".join(str(m["text"]).strip() for m in pending)[:3000]
    reply, agreed, brief = chat_turn(rf, text)
    if not reply:
        tg.send("⚠️ I could not think about that just now (the AI was busy). Send your message again in a minute.")
        rf["seen"] = [i for i in rf["seen"] if i not in {m["id"] for m in pending}]
        store.put_json(f"{base}/spec.json", rf)
        return
    rf = store.get_json(f"{base}/spec.json") or rf              # newer than my claim? keep it
    rf["spec"]["agreed"] = agreed
    rf["history"] = ((rf.get("history") or []) + [{"who": "c", "text": text[:600]}, {"who": "s", "text": reply[:600]}])[-24:]
    rf["created"] = _now_ms()                                   # the conversation keeps the reference alive
    store.put_json(f"{base}/spec.json", rf)
    tg.send(reply)


if __name__ == "__main__":
    main(sys.argv[1], sys.argv[2] if len(sys.argv) > 2 else "read")

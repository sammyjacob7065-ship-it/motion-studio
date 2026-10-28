"""The AI director: understands the brief, plans, writes the timeline, and checks its own work.

Three kinds of calls, each separate so they can be tuned or swapped for a stronger model:
  plan()      brief -> requirements, concept, voice-over text, stock needs, style
  timeline()  brief + plan + assets + word times -> exact timeline
  repair()    timeline + problems -> corrected timeline
  critique()  looks at preview frames (vision) and lists visible problems
  coverage()  ticks every requirement against the finished timeline
"""
import json
import os
import groq
from common import env

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(os.path.dirname(HERE), "director")


def _read(p):
    with open(os.path.join(DIR, p), encoding="utf-8") as f:
        return f.read()


def system_prompt():
    ex = json.load(open(os.path.join(DIR, "examples", "fintech.json"), encoding="utf-8"))
    return _read("system.md").replace("{{BLOCKS}}", _read("BLOCKS.md")).replace("{{EXAMPLE}}", json.dumps(ex, separators=(",", ":")))


def asset_table(registry):
    if not registry:
        return "(no files supplied)"
    rows = []
    for name, a in registry.items():
        k = a.get("kind")
        bits = [k or "file"]
        if a.get("width"):
            bits.append(f"{a['width']}x{a['height']}")
        if a.get("alpha"):
            bits.append("transparent background")
        if a.get("duration"):
            bits.append(f"{a['duration']}s")
        if k == "video":
            bits.append("has sound" if a.get("audio") else "no sound")
        if a.get("colors"):
            bits.append("colors " + " ".join(a["colors"][:4]))
        d = a.get("describe")
        if d:
            bits.append("shows: " + str(d.get("what", ""))[:120] + (" [logo]" if d.get("is_logo") else "") + (" [has text]" if d.get("has_text") else ""))
        for f in a.get("flags", []):
            bits.append("WARNING " + f)
        if a.get("origin"):
            bits.append(a["origin"])
        rows.append(f"- {name} | " + " | ".join(bits))
    return "\n".join(rows)


PLAN_SYSTEM = """You are the planning assistant of a motion graphics studio. Read the client brief and the list of supplied files, then reply with ONE JSON object:
{
 "requirements": ["every explicit instruction in the brief as a short checkable sentence, in the client's order, nothing invented"],
 "concept": "2-3 sentences: what the video is and how it should feel",
 "aspect": "9:16 | 16:9 | 1:1 | 4:5",
 "duration": number of seconds or null,
 "voiceover": {"mode": "supplied | generate | none", "text": "exact words to speak (only for generate)"},
 "stock": [{"id":"stock1","query":"search words","kind":"image|video","why":"short"}],
 "cutout": ["file names whose background should be removed"],
 "captions": true or false,
 "transcribe_videos": true or false,
 "style": {"palette": {"primary":"#hex","accent":"#hex","text":"#hex"}, "background": ["#hex","#hex"], "fonts": ["Poppins"], "mood": "words"}
}
Rules:
- aspect: use what the brief says; otherwise follow the supplied video/pictures; otherwise 9:16 for social/mobile content and 16:9 for YouTube/website/TV content.
- duration: the length the brief asks for; if not stated and a voice-over exists leave null; otherwise 12-20.
- voiceover: "supplied" if an audio file that is a voice was supplied. If the brief states the exact words to be spoken, mode "generate" with EXACTLY those words (do not rewrite them). If the brief asks for a voice-over without giving words, write a clear script in simple English that fits the duration (about 2.4 words per second). If the brief does not mention a voice-over, mode "none".
- stock: only when the brief asks you to find pictures/videos or needs imagery that was not supplied. Maximum 6. Search words must be concrete, in English.
- cutout: only when the brief asks to remove a background, or a product picture has a plain background and must float in a scene.
- captions: true if the brief asks for captions/subtitles, or a talking-person video is made for social media.
- transcribe_videos: true if supplied videos contain speech that captions, quotes or timing will use.
- style: use the client's brand colors/fonts if given; otherwise choose a palette that fits the topic and the supplied pictures' colors. Fonts only from: Inter, Poppins, Montserrat, Space Grotesk, Playfair Display, Bebas Neue, Oswald, DM Sans, Outfit, Sora, Anton.
Never invent requirements the client did not write."""


def plan(prompt, registry, urls_note=""):
    user = f"CLIENT BRIEF (verbatim):\n<<<\n{prompt}\n>>>\n\nSUPPLIED FILES:\n{asset_table(registry)}\n{urls_note}"
    for _ in range(3):
        try:
            return groq.parse_json(groq.chat([{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": user}], temperature=0.3, max_tokens=4000, reasoning="medium"))
        except Exception as e:  # noqa: BLE001
            err = e
    raise RuntimeError(f"Director could not plan: {err}")


def words_block(words, voice_start):
    """Compact word times, already shifted to the video timeline."""
    if not words:
        return "(no voice-over)"
    out, line, t0 = [], [], None
    for w in words:
        if t0 is None:
            t0 = w["s"] + voice_start
        line.append(f"{w['w']}@{w['s'] + voice_start:.2f}")
        if w["w"].endswith((".", "!", "?")) or len(line) >= 14:
            out.append(" ".join(line))
            line, t0 = [], None
    if line:
        out.append(" ".join(line))
    return "\n".join(out)


def timeline(prompt, plan_json, registry, words, voice_start, size, sfx_names, min_duration=None, extra=""):
    W, H = size
    dur = plan_json.get("duration") or min_duration or 14
    reqs = "\n".join(f"{i + 1}. {r}" for i, r in enumerate(plan_json.get("requirements", [])))
    vo_end = (words[-1]["e"] + voice_start) if words else None
    user = (
        f"CLIENT BRIEF (verbatim, follow it exactly):\n<<<\n{prompt}\n>>>\n\n"
        f"REQUIREMENTS (all must be satisfied):\n{reqs or '(none stated: use your best judgement)'}\n\n"
        f"CONCEPT: {plan_json.get('concept', '')}\n"
        f"STYLE: {json.dumps(plan_json.get('style', {}))}\n"
        f"CANVAS: {W}x{H} ({plan_json.get('aspect', '9:16')}), 30 fps, target duration about {dur} seconds"
        + (f"; the voice-over ends at {vo_end:.2f}s so the video must last at least {vo_end + 1.2:.1f}s" if vo_end else "")
        + f"\n\nASSETS (use these exact file names):\n{asset_table(registry)}\n\n"
        f"VOICE-OVER WORD TIMES (word@seconds on the video timeline; sync effects to these exactly):\n{words_block(words, voice_start)}\n\n"
        f"CAPTIONS: {'add one captions layer (words_from voice)' if plan_json.get('captions') and words else 'only if the brief asks'}\n"
        f"SOUND EFFECTS AVAILABLE: {', '.join(sfx_names)}\n{extra}"
    )
    ans = groq.chat([{"role": "system", "content": system_prompt()}, {"role": "user", "content": user}], temperature=0.45, max_tokens=14000, reasoning="high")
    return _split(groq.parse_json(ans)), user


def _split(obj):
    tl = obj.get("timeline", obj)
    return tl, obj.get("audio", []), obj.get("notes", "")


def repair(prev_tl, prev_audio, problems, original_user):
    msg = (
        original_user + "\n\nYOUR PREVIOUS ANSWER:\n" + json.dumps({"timeline": prev_tl, "audio": prev_audio}, separators=(",", ":"))
        + "\n\nPROBLEMS FOUND (fix them all, keep everything else exactly as it is, and still follow the brief):\n" + "\n".join("- " + p for p in problems)
        + "\n\nReply with the full corrected JSON object."
    )
    ans = groq.chat([{"role": "system", "content": system_prompt()}, {"role": "user", "content": msg}], temperature=0.3, max_tokens=14000, reasoning="high")
    return _split(groq.parse_json(ans))


def critique(images_b64, requirements, times):
    """Vision check of preview frames. Returns list of {severity, time, what, fix}."""
    model = env("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    content = [{"type": "text", "text": (
        "These are frames from a motion graphics video at times " + ", ".join(f"{t:.1f}s" for t in times) + ". "
        "Look only for problems a viewer would notice: text overlapping other text or objects, text that is cut off or too small to read, text with poor contrast, "
        "elements cut off by the screen edge, large empty or unbalanced areas, things hiding the main subject, a client logo or product that looks stretched. "
        "Required items: " + "; ".join(requirements[:12]) + ". "
        'Reply JSON only: {"issues":[{"severity":"major|minor","time":number,"what":"short","fix":"short instruction"}]}. Empty list if it looks clean. Do not invent problems.')}]
    for b in images_b64[:5]:
        content.append({"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b}})
    ans = groq.chat([{"role": "user", "content": content}], model=model, temperature=0.1, max_tokens=900, json_mode=False)
    return groq.parse_json(ans).get("issues", [])


def summarize_timeline(tl):
    rows = []
    for l in tl.get("layers", []):
        p = l.get("props", {})
        what = p.get("text") or p.get("asset") or p.get("name") or p.get("kind") or p.get("mode") or ""
        rows.append(f"{l['id']} [{l['type']}] {l['start']:.1f}-{l['end']:.1f}s {str(what)[:70]}" + (f" enter={l['enter']['preset']}" if l.get("enter") else ""))
    return "\n".join(rows) + f"\ncamera keys: {len(tl.get('camera', []))}"


def coverage(requirements, tl, audio, notes=""):
    """Ticks each requirement. Returns list of {requirement, status: done|simplified|missing, note}."""
    if not requirements:
        return []
    sys_msg = 'You check a finished motion graphics timeline against the client requirements. Reply JSON only: {"results":[{"n":1,"status":"done|simplified|missing","note":"short, only if not done"}]}. "done" only if the timeline clearly does it.'
    user = "REQUIREMENTS:\n" + "\n".join(f"{i + 1}. {r}" for i, r in enumerate(requirements)) + "\n\nTIMELINE:\n" + summarize_timeline(tl) + "\n\nAUDIO EVENTS:\n" + "\n".join(f"{a.get('role')} {a.get('sfx') or a.get('asset', '')} @{a.get('start', 0)}" for a in audio or []) + (f"\n\nDIRECTOR NOTES: {notes}" if notes else "")
    try:
        res = groq.parse_json(groq.chat([{"role": "system", "content": sys_msg}, {"role": "user", "content": user}], temperature=0.1, max_tokens=2500, reasoning="low")).get("results", [])
    except Exception:  # noqa: BLE001
        return []
    out = []
    for r in res:
        try:
            i = int(r.get("n")) - 1
            out.append({"requirement": requirements[i], "status": r.get("status", "done"), "note": r.get("note", "")})
        except Exception:  # noqa: BLE001
            continue
    return out

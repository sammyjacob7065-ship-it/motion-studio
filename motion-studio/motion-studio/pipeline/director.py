"""The AI director: understands the brief, plans, writes the timeline, and checks its own work.

Three kinds of calls, each separate so they can be tuned or swapped for a stronger model:
  plan()      brief -> requirements, concept, voice-over text, stock needs, style
  timeline()  brief + plan + assets + word times -> exact timeline
  repair()    timeline + problems -> corrected timeline
  critique()  looks at preview frames (vision) and lists visible problems
  coverage()  ticks every requirement against the finished timeline
"""
import json
import re
import os
import groq
from common import env

HERE = os.path.dirname(os.path.abspath(__file__))
DIR = os.path.join(os.path.dirname(HERE), "director")


def _read(p):
    with open(os.path.join(DIR, p), encoding="utf-8") as f:
        return f.read()


def system_prompt(example=True):
    base = _read("system.md").replace("{{BLOCKS}}", _read("BLOCKS.md"))
    if not example:                       # the short version used when the request must stay small
        return base.split("# Example")[0].rstrip() + "\n"
    ex = json.load(open(os.path.join(DIR, "examples", "fintech.json"), encoding="utf-8"))
    return base.replace("{{EXAMPLE}}", json.dumps(ex, separators=(",", ":")))


def est_tokens(*texts):
    """A safe over-estimate of how many tokens a request uses (JSON and code count heavier than plain words)."""
    return int(sum(len(t) for t in texts) / 3.0)


SMALL_REQUEST = 5500          # a request estimated above this many tokens is written in parts (the free Groq plan allows 8,000 per minute)
PART_SECONDS = 9.0


def _use_gemini():
    try:
        import gemini
        return gemini.available() and env("GEMINI_FOR_DIRECTOR", "1") != "0"
    except Exception:  # noqa: BLE001
        return False


def _limit(extra=0):
    """How big a request may be before it must be written in parts: Gemini takes the whole thing, the free Groq plan only a small one."""
    return 10 ** 9 if _use_gemini() else int(env("SMALL_REQUEST", str(SMALL_REQUEST))) + extra


def _chat(messages, temperature=0.4, max_tokens=6000, reasoning=None):
    """Gemini first (big answers, big input), Groq as the backup. Returns JSON text, like groq.chat."""
    if _use_gemini():
        try:
            import gemini
            system = next((m["content"] for m in messages if m.get("role") == "system"), None)
            user = "\n\n".join(str(m["content"]) for m in messages if m.get("role") != "system")
            obj = gemini.parse_json(gemini.generate(user, system=system, temperature=temperature, max_tokens=max(int(max_tokens), 16000), rounds=2))
            return json.dumps(obj)
        except Exception as e:  # noqa: BLE001
            print("::warning::Gemini could not answer, using Groq:", str(e)[:140])
    return groq.chat(messages, temperature=temperature, max_tokens=max_tokens, reasoning=reasoning)


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
 "stock": [{"id":"stock1","query":"2-4 plain words of what the photo shows","prompt":"one full sentence describing exactly the picture to make: subject, place, light, camera angle (photorealistic, no text)","phrase":"the exact words of the voice-over line it goes with","kind":"image","why":"short"}],
 "cutout": ["file names whose background should be removed"],
 "captions": true or false,
 "transcribe_videos": true or false,
 "style": {"palette": {"primary":"#hex","accent":"#hex","text":"#hex"}, "background": ["#hex","#hex"], "fonts": ["Poppins"], "mood": "words"}
}
Rules:
- aspect: use what the brief says; otherwise follow the supplied video/pictures; otherwise 9:16 for social/mobile content and 16:9 for YouTube/website/TV content.
- duration: the length the brief asks for; if not stated and a voice-over exists leave null; otherwise 12-20.
- voiceover: "supplied" if an audio file that is a voice was supplied. If the brief states the exact words to be spoken, mode "generate" with EXACTLY those words (do not rewrite them). If the brief asks for a voice-over without giving words, write a clear script in simple English that fits the duration (about 2.4 words per second). If the brief does not mention a voice-over, mode "none".
- stock: only when the brief asks you to find pictures/videos or needs imagery that was not supplied. Maximum 8. Each picture is made by an AI from your "prompt", so describe exactly what the voice-over line says at that moment (voice says good roads -> a tarred estate road with street lights, never a room). One picture per spoken idea. Never ask for music or sound as a picture. Keep Nigerian people and places when the brief is Nigerian.
- cutout: only when the brief asks to remove a background, or a product picture has a plain background and must float in a scene.
- captions: true if the brief asks for captions/subtitles, or a talking-person video is made for social media.
- transcribe_videos: true if supplied videos contain speech that captions, quotes or timing will use.
- style: use the client's brand colors/fonts if given; otherwise choose a palette that fits the topic and the supplied pictures' colors. Fonts only from: Inter, Poppins, Montserrat, Space Grotesk, Playfair Display, Bebas Neue, Oswald, DM Sans, Outfit, Sora, Anton.
Never invent requirements the client did not write."""


def _repair_plan(plan, prompt):
    """A weak or backup model sometimes writes a thin plan (one requirement, no voice, a few seconds). The brief itself is the
    truth: take the length, the exact voice-over words, the stock-picture wishes and the instruction lines from the brief."""
    import re
    if not isinstance(plan, dict):
        plan = {}
    text = str(prompt or "")
    # length stated in the brief ("30-second", "30 seconds", "30 sec")
    stated = None
    for mm in re.finditer(r"\b(\d{1,3})\s*[- ]?\s*(?:seconds?|secs?)\b", text, re.I):
        stated = float(mm.group(1))
        break
    try:
        dur = float(plan.get("duration") or 0)
    except Exception:  # noqa: BLE001
        dur = 0
    if stated and (dur < stated * 0.8 or dur > stated * 1.5):
        plan["duration"] = stated
    # exact voice-over words in quotes after the word VOICE-OVER / VOICEOVER / NARRATION
    vo = plan.get("voiceover") or {}
    if not isinstance(vo, dict):
        vo = {}
    if vo.get("mode") != "supplied" and not str(vo.get("text") or "").strip():
        q = re.search(r"(?:voice[- ]?over|narration|voice)[^\n\"\u201c]{0,120}[:\n]\s*[\"\u201c]([^\"\u201d]{20,2500})[\"\u201d]", text, re.I)
        if q:
            plan["voiceover"] = {"mode": "generate", "text": " ".join(q.group(1).split())}
    # pictures written in the brief line by line:  1. "voice words": Picture of a tarred road ...
    pics = pictures_from_brief(text)
    if pics and len(pics) > len(plan.get("stock") or []):
        plan["stock"] = pics
    # stock pictures the brief asks us to find
    if not plan.get("stock"):
        f = re.search(r"find\b[^.\n]{0,60}?\b(photos?|pictures?|images?|videos?|clips?)\b[^.\n]{0,40}?\bof\b\s+([^.\n]{10,400})", text, re.I)
        if f:
            parts = [p.strip(" ,;") for p in re.split(r",\s*(?:and\s+)?|\s+and\s+", f.group(2)) if len(p.strip(" ,;")) >= 4][:5]
            plan["stock"] = [{"id": f"stock{i + 1}", "query": p, "kind": "image", "why": "asked in the brief"} for i, p in enumerate(parts)]
    # instruction lines
    reqs = [str(r) for r in (plan.get("requirements") or []) if str(r).strip()]
    lines = [" ".join(l.split()) for l in text.splitlines() if len(" ".join(l.split())) >= 12]
    if len(lines) >= 6 and len(reqs) < max(4, len(lines) // 3):
        low = " ".join(reqs).lower()
        for l in lines:
            if l.lower()[:40] not in low and len(reqs) < 30:
                reqs.append(l[:240])
        plan["requirements"] = reqs
    plan.setdefault("aspect", "9:16" if re.search(r"9\s*:\s*16|vertical", text, re.I) else "16:9")
    if re.search(r"\b(captions?|subtitles?)\b", text, re.I):
        plan["captions"] = True
    return plan


def plan(prompt, registry, urls_note=""):
    user = f"CLIENT BRIEF (verbatim):\n<<<\n{prompt}\n>>>\n\nSUPPLIED FILES:\n{asset_table(registry)}\n{urls_note}"
    for _ in range(3):
        try:
            return _repair_plan(groq.parse_json(_chat([{"role": "system", "content": PLAN_SYSTEM}, {"role": "user", "content": user}], temperature=0.3, max_tokens=4000, reasoning="medium")), prompt)
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
    try:
        plan_dur = float(plan_json.get("duration") or 0)
    except Exception:  # noqa: BLE001
        plan_dur = 0.0
    dur = max(plan_dur, (float(min_duration) + 1.2) if min_duration else 0.0) or 14      # never shorter than the voice-over
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
    if est_tokens(system_prompt(), user) > _limit():
        return _timeline_in_parts(user, prompt, plan_json, registry, words, voice_start, size, sfx_names, dur), user
    try:
        ans = _chat([{"role": "system", "content": system_prompt()}, {"role": "user", "content": user}], temperature=0.45, max_tokens=14000, reasoning="high")
        return _split(groq.parse_json(ans)), user
    except Exception as e:  # noqa: BLE001
        if est_tokens(system_prompt(), user) > int(env("SMALL_REQUEST", str(SMALL_REQUEST))):      # Gemini and Groq both failed on a big request: write it in small parts
            print("::warning::the whole timeline could not be written in one go, writing it in parts:", str(e)[:120])
            return _timeline_in_parts(user, prompt, plan_json, registry, words, voice_start, size, sfx_names, dur), user
        raise


def _layer_line(l):
    p = l.get("props") or {}
    what = p.get("text") or p.get("asset") or p.get("shape") or p.get("name") or p.get("mode") or ""
    return "- %s %s %.1f-%.1fs x=%s y=%s z=%s %s" % (l.get("id", "?"), l.get("type", "?"), float(l.get("start", 0) or 0), float(l.get("end", 0) or 0),
                                                  l.get("x", ""), l.get("y", ""), l.get("z", ""), str(what).replace("\n", " / ")[:40])


_HEAD = re.compile(r"^\s*(?:#+\s*)?(?:scene|shot|picture|image)\s*\d{1,2}\b|^\s*\d{1,2}[.)]\s", re.I)
_IMG = re.compile(r"^\s*(?:[-*\u2022]\s*)?(?:image[ _-]?prompt|picture[ _-]?prompt|image|picture|photo|visual|background[ _-]?image)\s*[:\-]\s*(.+)$", re.I)
_VO = re.compile(r"^\s*(?:[-*\u2022]\s*)?(?:voice[- ]?over|voice|narration|narrator|vo|say|speech|line)\s*[:\-]\s*[\"\u201c]?(.+?)[\"\u201d]?\s*$", re.I)
_OTHER = re.compile(r"^\s*(?:[-*\u2022]\s*)?(?:seconds?|time|camera|motion|action|animation|label|text|title|sound|sfx|music|caption|captions|transition|note|notes|effect|effects|graphic|graphics)\s*[:\-]", re.I)


def pictures_from_brief(text):
    """The script controls the pictures. Reads the image prompt the client wrote for each scene (IMAGE: / IMAGE PROMPT: / PICTURE: ...) and the voice line
    of the same scene (VOICE: / NARRATION: ...). The prompt is used exactly as written. Also understands '1. "spoken words": Picture of ...' lines."""
    lines = str(text or "").splitlines()
    blocks, cur = [], None
    for ln in lines:
        if _HEAD.match(ln) and not _IMG.match(ln):
            cur = {"img": "", "vo": "", "head": ln}
            blocks.append(cur)
            rest = re.sub(r"^\s*(?:#+\s*)?(?:scene|shot|picture|image)?\s*\d{1,2}[.):\-]?\s*", "", ln, flags=re.I)
            q = re.match(r"[\"\u201c]([^\"\u201d]{3,200})[\"\u201d]\s*[:\-]?\s*(.*)$", rest)
            if q:
                cur["vo"] = q.group(1)
                d = re.search(r"\b(?:picture|image|photo|photograph)\s+of\s+(.+?)(?:\.\s|\.$|$)", q.group(2), re.I)
                if d:
                    cur["img"] = "Photo of " + " ".join(d.group(1).split()).strip(" .")
            cur["_cap"] = None
            continue
        if cur is None:
            continue
        m = _IMG.match(ln)
        if m:
            cur["img"], cur["_cap"] = m.group(1).strip(), "img"
            continue
        m = _VO.match(ln)
        if m:
            cur["vo"], cur["_cap"] = m.group(1).strip(), "vo"
            continue
        if _OTHER.match(ln) or not ln.strip():
            cur["_cap"] = None
            continue
        if cur.get("_cap") == "img":
            cur["img"] += " " + ln.strip()
        elif cur.get("_cap") == "vo":
            cur["vo"] += " " + ln.strip().strip("\"\u201c\u201d")
    out = []
    for b in blocks:
        img = " ".join(b["img"].split())
        if len(img) < 8:
            continue
        out.append({"id": f"pic{len(out) + 1}", "query": " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", img).split()[:5]), "prompt": img[:900], "exact": True,
                    "phrase": " ".join(b["vo"].split())[:200], "kind": "image", "why": "written in the brief"})
    return out[:12]


def image_department(brief_text, plan, supplied_images, have_video=False, has_music=False, dur_hint=None):
    """The picture department. When the client sent no (or few) pictures, it decides which pictures the video needs, one for each spoken idea,
    and writes the image prompt for each. Returns stock-style requests [{id, query, prompt, phrase, kind}] that the image makers fill."""
    import math
    text = str(brief_text or "")
    if re.search(r"\b(no|without)\s+(pictures?|images?|photos?|stock)\b|text[- ]only|only text|only the (supplied|my) (pictures|images)", text, re.I):
        return []
    vo = plan.get("voiceover") or {}
    spoken = " ".join(str(vo.get("text") or "").split())
    try:
        dur = float(plan.get("duration") or 0) or 30.0
    except Exception:  # noqa: BLE001
        dur = 30.0
    if any(x.get("why") == "written in the brief" for x in (plan.get("stock") or [])):
        return []                                              # the script wrote its own picture prompts: it controls the pictures
    have = len(plan.get("stock") or []) + supplied_images
    want = max(3, min(9, int(round(dur / 4.0))))
    if have_video or have >= 3:
        return []                                              # a supplied video is the footage; enough pictures already
    if not spoken:
        # no voice-over: pictures are still made when a song was sent or the brief talks about pictures; they come from the brief itself
        if not (has_music or re.search(r"\b(image|images|picture|pictures|photo|photos|scene|scenes|visual|visuals)\b", text, re.I)):
            return []
        d = float(dur_hint or dur or 24)
        need = max(3, min(10, int(round(d / 3.0)))) - have
        if need <= 0:
            return []
        context = " ".join((text + " " + str(plan.get("concept") or "")).split())[:600]
        african = bool(re.search(r"nigeria|lagos|abuja|naira|ibadan|africa|ghana|kenya", text, re.I))
        pics = []
        try:
            ans = _chat([{"role": "system", "content": "You are the picture editor of a professional advert studio. You write precise image prompts."},
                             {"role": "user", "content": f"Brief: {context}\n\nWrite {need} different image prompts for a {int(d)}-second video with music, one picture per scene, in the order of the story of the brief. Each prompt is one sentence "
                              "(subject, place, light, camera angle) and must show something the brief is about. No text, no logos." + (" People and places are African/Nigerian." if african else "") + '\nReply JSON only: {"pictures":[{"prompt":"photorealistic ..."}]}'}],
                            temperature=0.5, max_tokens=1500, reasoning="low")
            for it in (groq.parse_json(ans).get("pictures") or [])[:need]:
                if isinstance(it, dict) and str(it.get("prompt") or "").strip():
                    pics.append(str(it["prompt"]).strip()[:600])
        except Exception as e:  # noqa: BLE001
            print("picture department (no voice): simple way (", str(e)[:80], ")")
        while len(pics) < need:
            pics.append(f"Photorealistic cinematic photo, scene {len(pics) + 1} of {need}: {context[:200]}" + (" African setting." if african else ""))
        return [{"id": f"auto{i + 1}", "query": " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", p).split()[:5]) or "scene", "prompt": p, "phrase": "", "kind": "image", "why": "picture department"} for i, p in enumerate(pics[:need])]
    if not spoken:
        return []
    need = want - have
    sentences = [s.strip() for s in re.split(r"(?<=[.!?])\s+", spoken) if len(s.strip()) > 3]
    african = bool(re.search(r"nigeria|lagos|abuja|naira|ibadan|africa|ghana|kenya|en-NG", text + " " + str(vo), re.I))
    context = " ".join(text.split())[:260]
    pics = []
    try:
        msg = ("Voice-over sentences:\n" + "\n".join(f"{i + 1}. {s}" for i, s in enumerate(sentences[:24])) + f"\n\nBrief (for the subject and mood): {context}\n\n"
               f"Choose {need} voice-over sentences or ideas that deserve a picture on screen, spread across the whole video. For each give the exact words of that voice line and an image prompt: one sentence that describes the picture the viewer should SEE while that line is spoken "
               "(subject, place, light, camera angle). It must show what the words say, never something else. No text, no logos, no people's faces in close-up unless the line is about people." + (" People and places are African/Nigerian." if african else "") +
               '\nReply JSON only: {"pictures":[{"phrase":"exact words","prompt":"photorealistic ... "}]}')
        ans = _chat([{"role": "system", "content": "You are the picture editor of a professional advert studio. You write precise image prompts."}, {"role": "user", "content": msg}], temperature=0.4, max_tokens=1500, reasoning="low")
        for it in (groq.parse_json(ans).get("pictures") or [])[:need]:
            if isinstance(it, dict) and str(it.get("prompt") or "").strip():
                pics.append({"phrase": str(it.get("phrase") or "")[:200], "prompt": str(it["prompt"]).strip()[:600]})
    except Exception as e:  # noqa: BLE001
        print("picture department: using the simple way (", str(e)[:80], ")")
    if len(pics) < need:                                       # simple way: one picture per spoken idea, taken from the words themselves
        step = max(1, len(sentences) // max(1, need))
        used = {p["phrase"] for p in pics}
        for s in sentences[::step]:
            if len(pics) >= need:
                break
            if s not in used:
                pics.append({"phrase": s, "prompt": f"Photorealistic cinematic photo that shows: {s} {context[:120]}" + (" African setting." if african else "")})
    out = []
    for i, p in enumerate(pics[:need]):
        out.append({"id": f"auto{i + 1}", "query": " ".join(re.sub(r"[^A-Za-z0-9 ]", " ", p["phrase"]).split()[:5]) or "scene", "prompt": p["prompt"], "phrase": p["phrase"], "kind": "image", "why": "picture department"})
    return out


PART_HOOK = {"load": None, "save": None}     # set by run.py: saves each finished part so /resume does not redo it


def _timeline_in_parts(user, prompt, plan_json, registry, words, voice_start, size, sfx_names, dur):
    """Write the video in 2-4 short parts (about 9 seconds each), one after another, so every request stays small.
    Part 1 also sets palette, background and camera. Each later part sees what is already on screen."""
    import math
    n = max(2, int(math.ceil(float(dur) / PART_SECONDS)))
    step = float(dur) / n
    sysmsg = system_prompt(example=False)
    head = user.split("VOICE-OVER WORD TIMES")[0]            # brief, requirements, concept, style, canvas, assets
    tail_sfx = "SOUND EFFECTS AVAILABLE: " + ", ".join(sfx_names)
    first_tl, layers, audio, notes = {}, [], [], []
    seen = set()
    for k in range(n):
        t0, t1 = round(k * step, 2), round((k + 1) * step, 2) if k < n - 1 else round(float(dur), 2)
        ws = [w for w in words if t0 - 0.6 <= w["s"] + voice_start < t1 + 1.0]
        wtxt = words_block(ws, voice_start) if ws else "(no spoken words in this part)"
        msg = (
            head + f"VOICE-OVER WORD TIMES for this part (word@seconds):\n{wtxt}\n\n" + tail_sfx + "\n\n"
            + f"YOU ARE WRITING PART {k + 1} OF {n}. The video is written in parts so every answer stays short. This part covers {t0:.1f}s to {t1:.1f}s of a {float(dur):.1f}s video.\n"
            + f"- Output ONLY layers whose start is from {t0:.1f}s up to {t1:.1f}s (they may end later). Give every layer id the prefix p{k + 1}_ . Use the exact word times above to sync.\n"
        )
        if k == 0:
            msg += (f"- ALSO output for the WHOLE video: aspect, fps, duration ({float(dur):.1f}), palette, background, and the camera keyframes from 0 to {float(dur):.1f}s.\n"
                    '- Reply JSON: {"timeline": {"aspect":..,"fps":30,"duration":..,"palette":{..},"background":{..},"camera":[..],"layers":[..]}, "audio": [..], "notes": ".."}\n')
        else:
            msg += (f"- Do NOT output palette, background or camera: they are set. Palette: {json.dumps(first_tl.get('palette', {}))}. Background: {json.dumps(first_tl.get('background', {}))[:300]}.\n"
                    '- Reply JSON: {"timeline": {"layers": [..]}, "audio": [..], "notes": ".."}\n'
                    "- Already placed by earlier parts (continue the same look; do not repeat them; do not put text over their text):\n" + "\n".join(_layer_line(l) for l in layers[-40:]) + "\n")
        if k == n - 1:
            msg += f"- This is the LAST part: it must include the final reveal and the final frame must stay visible for at least 1.2 s, until {float(dur):.1f}s. Add the captions layer here only if it was not placed already.\n"
        tl = None
        saved = None
        try:
            saved = PART_HOOK["load"](k) if PART_HOOK["load"] else None
        except Exception:  # noqa: BLE001
            saved = None
        if saved and isinstance(saved.get("tl"), dict):
            tl, au, nt = saved["tl"], saved.get("au"), saved.get("nt")
        for attempt in range(0 if tl is not None else 2):
            ask = msg if attempt == 0 else msg + "- YOUR LAST ANSWER WAS CUT OFF OR INVALID. Answer again with a SHORTER part: at most 8 layers, no long descriptions, valid JSON only.\n"
            try:
                ans = _chat([{"role": "system", "content": sysmsg}, {"role": "user", "content": ask}], temperature=0.45, max_tokens=4500, reasoning="low")
                tl, au, nt = _split(groq.parse_json(ans))
                break
            except ValueError:
                tl = None
        if tl is None:
            raise RuntimeError(f"The director's answer for part {k + 1} was not valid twice.")
        if not saved and PART_HOOK["save"]:
            try:
                PART_HOOK["save"](k, {"tl": tl, "au": au, "nt": nt})
            except Exception:  # noqa: BLE001
                pass
        if k == 0:
            first_tl = {kk: vv for kk, vv in tl.items() if kk != "layers"}
        for l in tl.get("layers", []) or []:
            if not isinstance(l, dict):
                continue
            lid = str(l.get("id") or f"p{k + 1}_{len(layers)}")
            if lid in seen:
                lid = f"{lid}_{k + 1}{len(layers)}"
            l["id"] = lid
            seen.add(lid)
            layers.append(l)
        audio += au or []
        if nt:
            notes.append(str(nt))
    first_tl["layers"] = layers
    first_tl.setdefault("duration", float(dur))
    first_tl.setdefault("fps", 30)
    return first_tl, audio, " ".join(notes)[:400]


def _split(obj):
    tl = obj.get("timeline", obj)
    return tl, obj.get("audio", []), obj.get("notes", "")


def repair(prev_tl, prev_audio, problems, original_user):
    msg = (
        original_user + "\n\nYOUR PREVIOUS ANSWER:\n" + json.dumps({"timeline": prev_tl, "audio": prev_audio}, separators=(",", ":"))
        + "\n\nPROBLEMS FOUND (fix them all, keep everything else exactly as it is, and still follow the brief):\n" + "\n".join("- " + p for p in problems)
        + "\n\nReply with the full corrected JSON object."
    )
    if est_tokens(system_prompt(), msg) > _limit(1500):
        return prev_tl, prev_audio, "A fix round was skipped: the request was too big for the free Groq plan."
    ans = _chat([{"role": "system", "content": system_prompt()}, {"role": "user", "content": msg}], temperature=0.3, max_tokens=14000, reasoning="high")
    return _split(groq.parse_json(ans))


def edit(prev_tl, prev_audio, notes, registry, plan_json, brief_text, size, sfx_names):
    """The edit department: changes ONLY what the client's edit notes ask for in the finished timeline, keeps everything else exactly.
    Uses Gemini (big answers) when its key is set, otherwise the Groq director. Returns (timeline, audio, new_pictures, what_changed)."""
    import gemini
    W, H = size
    user = (
        f"ORIGINAL CLIENT BRIEF (for context):\n<<<\n{str(brief_text)[:6000]}\n>>>\n\n"
        f"CANVAS: {W}x{H} ({plan_json.get('aspect', '9:16')}), 30 fps\n\n"
        f"ASSETS (use these exact file names):\n{asset_table(registry)}\n\n"
        f"SOUND EFFECTS AVAILABLE: {', '.join(sfx_names)}\n\n"
        f"THE FINISHED VIDEO AS A TIMELINE (JSON):\n{json.dumps({'timeline': prev_tl, 'audio': prev_audio}, separators=(',', ':'))}\n\n"
        "EDIT REQUESTS FROM THE CLIENT (do exactly these, in order):\n" + "\n".join(f"{i + 1}. {n}" for i, n in enumerate(notes)) + "\n\n"
        "RULES FOR THIS EDIT:\n"
        "- Change ONLY what the requests ask. Every other layer keeps its id, start, end, position, size, effects and timing exactly as in the timeline above.\n"
        "- Keep the voice-over timing, captions and the video length unless a request says otherwise.\n"
        "- If a request needs a NEW picture (for example: show a modern kitchen), list it in new_pictures with a file name newpic1.jpg, newpic2.jpg ... and a full image prompt "
        "(one sentence: subject, place, light, camera angle, photorealistic, no text), and use that file name in the image layer that replaces the old picture (same start, end and size).\n"
        "- A request about a time (for example: the price comes late) means move that layer's start/end and its sound; keep its length.\n"
        '- Reply with JSON only: {"timeline": {the FULL timeline with the changes}, "audio": [the FULL audio list with the changes], "new_pictures": [{"asset":"newpic1.jpg","prompt":"..."}], "changed": "one short plain sentence per request saying what you did"}'
    )
    ans, why = None, ""
    if gemini.available():
        ask = user
        for attempt in range(3):                               # an answer with a broken comma is asked for again, not given up on
            try:
                ans = gemini.parse_json(gemini.generate(ask, system=system_prompt(example=False), temperature=0.2 if attempt == 0 else 0.0))
                break
            except Exception as e:  # noqa: BLE001
                why = str(e)[:150]
                print(f"::warning::Gemini edit attempt {attempt + 1} failed:", why)
                if "JSON" not in why and "Expecting" not in why and "delimiter" not in why and "no JSON" not in why:
                    break
                ask = user + f"\n\nIMPORTANT: your previous answer was NOT valid JSON ({why}). Answer again with the complete answer as STRICTLY valid JSON: double quotes, commas between all items, no comments, no trailing commas, nothing outside the JSON."
    if ans is None:                                            # backup: the Groq director
        if est_tokens(system_prompt(False), user) > int(env("SMALL_REQUEST", str(SMALL_REQUEST))) + 1500:
            raise RuntimeError("The edit is too big for the free Groq plan" + (f" and Gemini failed ({why})" if why else " (no Gemini key set)") + ". Try /resume in a few minutes.")
        ans = groq.parse_json(groq.chat([{"role": "system", "content": system_prompt(False)}, {"role": "user", "content": user}], temperature=0.2, max_tokens=14000, reasoning="high"))
    tl = ans.get("timeline")
    if not isinstance(tl, dict) or not tl.get("layers"):
        raise RuntimeError("The edit answer had no timeline.")
    pics = [x for x in (ans.get("new_pictures") or []) if isinstance(x, dict) and x.get("asset") and x.get("prompt")][:6]
    return tl, ans.get("audio") if isinstance(ans.get("audio"), list) else prev_audio, pics, str(ans.get("changed") or "")[:600]


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


def coverage(requirements, tl, audio, notes="", facts=""):
    """Ticks each requirement. Returns list of {requirement, status: done|simplified|missing, note}."""
    if not requirements:
        return []
    sys_msg = 'You check a finished motion graphics timeline against the client requirements. Reply JSON only: {"results":[{"n":1,"status":"done|simplified|missing","note":"short, only if not done"}]}. "done" only if the timeline clearly does it, or if the studio facts say it was done.'
    user = "REQUIREMENTS:\n" + "\n".join(f"{i + 1}. {r}" for i, r in enumerate(requirements)) + "\n\nTIMELINE:\n" + summarize_timeline(tl) + "\n\nAUDIO EVENTS:\n" + "\n".join(f"{a.get('role')} {a.get('sfx') or a.get('asset', '')} @{a.get('start', 0)}" for a in audio or []) + (f"\n\nDIRECTOR NOTES: {notes}" if notes else "") + (f"\n\nTHE STUDIO ALSO ADDED (count these as done): {facts}" if facts else "")
    try:
        res = groq.parse_json(_chat([{"role": "system", "content": sys_msg}, {"role": "user", "content": user}], temperature=0.1, max_tokens=2500, reasoning="low")).get("results", [])
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

"""ONE PHOTO -> A WHOLE AD. The creative-director step.
When a client sends one or two pictures and a short brief ("make a 30 second ad for this"), this step looks at the picture(s), works out what the product is, who buys it,
what mood sells it, and WRITES the ad: the idea, the exact voice-over words, a beat-by-beat plan with the camera moves and the 3D / depth effects to use, the on-screen words,
the colours and the sound mood. That text is added to the brief, and the normal director then builds the timeline from it.
It never touches a brief that is already a full script (scene lines, exact voice-over, "CREATIVE: off"): a detailed prompt is built exactly as written."""
import os
import re

STRUCTURE = re.compile(r"^\s*(scene\s*\d+|voice[- ]?over\s*[:\-]|narration\s*[:\-]|image\s*prompt\s*[:\-]|motion\s*[:\-]|label\s*[:\-]|sound\s*[:\-]|background\s*[:\-]|captions?\s*[:\-])", re.I | re.M)


def _images(registry):
    return [n for n, a in registry.items() if a.get("kind") == "image" and not str(n).endswith(".svg")]


def wanted(prompt, registry):
    """True when the studio should write the ad itself."""
    p = str(prompt or "")
    if os.environ.get("CREATIVE_AI", "").strip() == "0":
        return False                                            # switched off for this run (tests, or a repository variable)
    if re.search(r"^\s*CREATIVE\s*:\s*off\b", p, re.I | re.M):
        return False
    if re.search(r"^\s*CREATIVE\s*:\s*(on|yes|auto)\b", p, re.I | re.M) or re.search(r"\bcreative director\b", p, re.I):
        return bool(_images(registry))
    if STRUCTURE.search(p) or len(p) > 900:
        return False                                            # a written script: built exactly as written
    if not _images(registry) or len(_images(registry)) > 3:
        return False
    return bool(re.search(r"\b(ad|advert|advertisement|commercial|promo|promotion|video|reel|short|spot|campaign)\b", p, re.I)) or len(p) < 160


def duration_of(prompt, default=30):
    """Seconds asked for in the brief. A studio ad is 6-120 s; a longer wish is capped (the report says so)."""
    m = re.search(r"(\d+(?:\.\d+)?)\s*(seconds?|secs?|s\b|minutes?|mins?|m\b)", str(prompt or ""), re.I)
    if not m:
        return default, None
    v = float(m.group(1)) * (60 if m.group(2).lower().startswith("m") else 1)
    if v > 120:
        return 120, f"asked for {int(v)} s: an ad is capped at 120 s here"
    return max(6, v), None


def _toolkit():
    return (
        "TOOLKIT the renderer can do (use these names in the beats):\n"
        "- DEPTH ORBIT / PUSH / DRIFT: the flat photo becomes a 3D scene, the camera moves through it (subject separates from background). Best for the opening and for slow beauty moments.\n"
        "- SOLID3D SPIN / SWING (round products like bottles, cans, jars: cylinder; flat products like phones, boxes, books, shoes: slab): the cut-out product turns in real 3D with shading and a moving highlight. Best for the reveal and the product showcase.\n"
        "- Product cut-out floating over a gradient, with soft shadow, glow and light sweep; tilt/flip/roll in 3D; parallax; floating particles; kinetic text with word highlights; counters (prices, percentages, only if stated);\n"
        "  magic effects (shockwave, liquid, spotlight, ripples, glitch, lens flare) when they suit the mood; a call-to-action end card with the brand and one line.\n")


SYSTEM = (
    "You are the creative director of a premium motion-graphics studio, at the level of an After Effects specialist at a top agency. A client sends one picture of a product and a short wish. "
    "You invent the whole advert from that picture. Be specific and fresh: a real hook, a clear idea, a build, a reveal, a close. No clichés, no filler.\n"
    "RULES: use only facts visible in the picture or stated in the brief (name, flavour, colours, text on the pack). Never invent prices, discounts, awards, certifications, ingredients, medical or performance claims, or contact details. "
    "Voice-over: simple, confident, short sentences; the first line is a hook of at most 9 words; the total word count must fit the duration at about 2.4 words per second, leaving about 1.5 s of silence at the end. "
    "On-screen words: at most 6 words per beat, never over the product. The product picture is shown exactly as supplied (never redrawn); only 3D effects, cut-outs and camera moves are applied to it.\n"
    + _toolkit() +
    'Reply with ONE JSON object only: {"product":"what it is, with the name printed on it","category":"short","audience":"who buys it","mood":"3-5 words","palette":["#hex","#hex","#hex"],'
    '"concept":"the idea of the ad in two sentences","voiceover":["line 1","line 2",...],"beats":[{"t0":0,"t1":3,"what":"what we see and do, concrete","technique":"one of the toolkit names","text":"on-screen words or empty"}],'
    '"sound":"music mood + the sound effects that fit (soft for calm products, hits only for bold ones)","cta":"closing line with the brand name"}')


def _ask(prompt, registry, paths, dur):
    import director
    table = director.asset_table(registry)
    user = f"CLIENT WISH (verbatim):\n<<<\n{prompt}\n>>>\n\nPICTURES SUPPLIED:\n{table}\n\nDURATION: {dur:g} seconds (aspect 9:16 unless the wish says otherwise).\nThe beats must cover 0 to {dur:g} s without gaps."
    imgs = []
    try:
        import gemini
        if gemini.available():
            for n in _images(registry)[:3]:
                p = paths.get(n)
                if p:
                    from PIL import Image
                    import io
                    im = Image.open(p).convert("RGB")
                    im.thumbnail((1280, 1280))
                    b = io.BytesIO(); im.save(b, "JPEG", quality=88)
                    imgs.append((b.getvalue(), "image/jpeg"))
            if imgs:
                txt = gemini.generate(user, system=SYSTEM, json_mode=True, temperature=0.8, max_tokens=6000, images=imgs)
                return gemini.parse_json(txt)
    except Exception as e:  # noqa: BLE001
        print("::warning::creative director (vision) fell back to text:", str(e)[:120])
    import groq
    return groq.parse_json(director._chat([{"role": "system", "content": SYSTEM}, {"role": "user", "content": user}], temperature=0.8, max_tokens=6000))


def _fallback(prompt, registry, dur):
    """No AI available: a sound, plain ad structure from what the studio already knows about the picture."""
    img = (_images(registry) or [""])[0]
    d = registry.get(img, {}).get("describe") or {}
    name = str(d.get("product_name") or d.get("what") or "this product").strip()
    cols = [c for c in (registry.get(img, {}).get("colors") or [])][:3] or ["#0f1b2d", "#2f6fed", "#f5f5f5"]
    t = lambda f: round(dur * f, 1)  # noqa: E731
    return {"product": name, "category": "", "audience": "", "mood": "clean, confident, premium", "palette": cols,
            "concept": f"A premium reveal of {name}: the photo comes alive in 3D, the product turns, then the brand closes.",
            "voiceover": [f"Meet {name}.", "Made to be noticed.", "Look closer.", "This is the one."][: max(2, int(dur // 8))],
            "beats": [{"t0": 0, "t1": t(.25), "what": "the photo as a 3D scene, camera orbits slowly, one big word appears", "technique": "DEPTH ORBIT", "text": name[:30]},
                      {"t0": t(.25), "t1": t(.7), "what": "the cut-out product floats over a gradient and turns in 3D with a moving highlight", "technique": "SOLID3D SPIN", "text": ""},
                      {"t0": t(.7), "t1": dur, "what": "product holds centre, light sweep, brand and closing line", "technique": "DEPTH PUSH", "text": name[:30]}],
            "sound": "calm modern music feel, soft whooshes, one soft hit on the reveal", "cta": name}


def _norm(c, dur):
    c = dict(c or {})
    c["voiceover"] = [str(x).strip() for x in (c.get("voiceover") or []) if str(x).strip()]
    bs = []
    for b in c.get("beats") or []:
        try:
            bs.append({"t0": max(0.0, float(b.get("t0", 0))), "t1": min(float(dur), float(b.get("t1", dur))), "what": str(b.get("what", "")).strip(), "technique": str(b.get("technique", "")).strip(), "text": str(b.get("text", "")).strip()})
        except (TypeError, ValueError):
            continue
    c["beats"] = [b for b in bs if b["t1"] > b["t0"] and b["what"]]
    return c


def render_brief(c, dur):
    """The creative plan as text for the director. The voice-over line is the exact words (the director must not rewrite them)."""
    vo = " ".join(c.get("voiceover") or [])
    lines = ["", "CREATIVE DIRECTION (written by the studio's creative director from the supplied picture; follow it):",
             f"DURATION: {dur:g} seconds", "ASPECT: 9:16 (unless the wish above says otherwise)",
             f"PRODUCT: {c.get('product', '')}", f"AUDIENCE: {c.get('audience', '')}", f"MOOD: {c.get('mood', '')}",
             "COLOURS: " + ", ".join(c.get("palette") or []), f"IDEA: {c.get('concept', '')}"]
    if vo:
        lines.append(f'VOICE-OVER: "{vo}"')
    lines.append("BEATS:")
    for b in c.get("beats") or []:
        lines.append(f"- {b['t0']:g}-{b['t1']:g} s | {b['technique']} | {b['what']}" + (f" | on-screen words: \"{b['text']}\"" if b.get("text") else ""))
    if c.get("sound"):
        lines.append(f"SOUND: {c['sound']}")
    if c.get("cta"):
        lines.append(f"END CARD: {c['cta']}")
    lines.append("Use depth layers (type depth) for the photo scenes and solid3d for the turning product; keep the product picture exactly as supplied.")
    return "\n".join(lines)


def expand(prompt, registry, paths):
    """Returns (new_prompt, report_line) or (None, reason)."""
    if not wanted(prompt, registry):
        return None, "not needed (the brief is a full script, or there is no product picture)"
    dur, cap = duration_of(prompt)
    try:
        c = _norm(_ask(prompt, registry, paths, dur), dur)
        if not c["beats"] or not c["voiceover"]:
            raise RuntimeError("the answer had no beats or no voice-over")
        how = "written from your picture"
    except Exception as e:  # noqa: BLE001
        print("::warning::creative director used the plain structure:", str(e)[:140])
        c = _norm(_fallback(prompt, registry, dur), dur)
        how = "plain structure (the AI was not available)"
    text = str(prompt).rstrip() + "\n" + render_brief(c, dur)
    return text, f"creative ad {how}, {dur:g} s" + (f" ({cap})" if cap else "")

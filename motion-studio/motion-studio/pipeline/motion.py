"""Motion department: gives every video a directed look instead of one look for all.
  1. STYLE        luxury, cinematic, documentary, corporate, news, social, high-energy, explainer, motivational, modern. Chosen from the brief (a line
                  "STYLE: luxury" in the prompt, or the words of the brief decide it); a style sets the pace of the camera, the transitions, the amount of
                  motion blur, how much a picture drifts, and tells the director how text should enter.
  2. TRANSITIONS  every cut between two pictures gets its own treatment chosen by what happens there (a hit or a riser: flash; a quick cut: whip or push;
                  the last picture: zoom through, dip or match cut; calm styles: crossfades), never the same one twice in a row. Transitions the script itself asks for are kept.
  3. MOTION BLUR  fast pushes, whips, slams and slides get a short blur that fades out as the move lands.
  4. QUALITY      before rendering: moves that leave the frame are pulled back, pictures with no movement get a camera-like drift, repeated identical drifts are varied,
                  hard cuts get a soft bridge, calm styles are kept calm.
  5. SUBJECTS     cut-out people and products (transparent pictures) sit in front of the background picture and move with a different depth (parallax), with a slow independent drift.
Everything is written as plain timeline data the renderer already plays (keyframe tracks, enter presets, transition layers): no new renderer code, nothing here can break a render.
It only adds; what the script or the director set explicitly is kept, and any failure leaves the timeline as it was."""
import copy
import random
import re

STYLES = {
    "cinematic": dict(label="Cinematic", tx={"crossfade": 3, "zoom": 3, "match": 2.5, "dip": 1, "flash": 0.5}, blur=0.6, kb=(1.06, 1.14), cam=0.10, cam_ease="inOutQuart", parallax=1.0, bold=False,
                      text="Text enters with blurIn, fade or riseGlow (words for headlines), slow ease (outExpo, inOutQuart); no bouncing; one hero element at a time."),
    "luxury": dict(label="Luxury", tx={"crossfade": 5, "dip": 3.5, "match": 1.5}, blur=0.3, kb=(1.03, 1.07), cam=0.06, cam_ease="inOutQuad", parallax=0.6, bold=False,
                   text="Text enters with fade or blurIn only, thin elegant type (Playfair Display), slow and spacious, long pauses, no bouncing, no shaking, no pop."),
    "documentary": dict(label="Documentary", tx={"crossfade": 6, "match": 2, "push": 2}, blur=0.2, kb=(1.04, 1.1), cam=0.05, cam_ease="inOutQuad", parallax=0.5, bold=False,
                        text="Text is calm: fade or slideUp, lower-third style names and short phrases, no bouncing."),
    "corporate": dict(label="Modern corporate", tx={"crossfade": 3, "push": 3, "wipe": 3, "zoom": 1}, blur=0.3, kb=(1.04, 1.08), cam=0.05, cam_ease="inOutQuad", parallax=0.6, bold=False,
                      text="Text enters with slideUp, slideLeft or fade, clean sans-serif, confident and orderly, no bouncing."),
    "news": dict(label="News broadcast", tx={"wipe": 4, "push": 3, "crossfade": 2, "flash": 1}, blur=0.3, kb=(1.03, 1.06), cam=0.03, cam_ease="inOutQuad", parallax=0.4, bold=False,
                 text="Headlines on a plate slide in with slideLeft or wipe, short and factual, a lower-third look, no bouncing."),
    "social": dict(label="Social media", tx={"whip": 3, "zoom": 2.5, "push": 2, "flash": 1.5, "match": 1}, blur=0.9, kb=(1.08, 1.18), cam=0.12, cam_ease="inOutQuart", parallax=1.0, bold=True,
                   text="Text is big and fast: pop, scaleIn or slideUp with words, quick and punchy, highlight key words."),
    "high_energy": dict(label="High-energy promotional", tx={"flash": 3, "whip": 2.5, "zoom": 2.5, "push": 1, "wipe": 1}, blur=1.0, kb=(1.1, 1.2), cam=0.14, cam_ease="inOutQuart", parallax=1.0, bold=True,
                        text="Text slams in: pop, zoomIn, drop with words, very fast, big, with flashes on the beats; the biggest word gets the biggest hit."),
    "explainer": dict(label="Explainer", tx={"wipe": 3, "push": 3, "crossfade": 2.5, "zoom": 1.5}, blur=0.4, kb=(1.04, 1.1), cam=0.06, cam_ease="inOutQuad", parallax=0.6, bold=False,
                      text="Text and icons enter one idea at a time with pop, slideUp or draw; steady pace, clear steps."),
    "motivational": dict(label="Motivational", tx={"zoom": 3, "crossfade": 2.5, "dip": 2, "flash": 1.5, "match": 1}, blur=0.6, kb=(1.07, 1.15), cam=0.10, cam_ease="inOutQuart", parallax=0.9, bold=True,
                         text="Strong short lines: scaleIn or zoomIn with words, big bold type, dramatic pauses, the key word highlighted."),
    "modern": dict(label="Modern", tx={"flash": 2, "zoom": 2, "push": 2, "crossfade": 1.5, "wipe": 1.5, "match": 1}, blur=0.6, kb=(1.06, 1.14), cam=0.09, cam_ease="inOutQuart", parallax=0.8, bold=True,
                   text="Text enters with a mix of slideUp, scaleIn and blurIn (words for headlines); smooth, confident and varied."),
}
ALIASES = {"high energy": "high_energy", "high-energy": "high_energy", "highenergy": "high_energy", "promo": "high_energy", "promotional": "high_energy", "hype": "high_energy",
           "tiktok": "social", "reels": "social", "instagram": "social", "social media": "social", "news broadcast": "news", "broadcast": "news",
           "modern corporate": "corporate", "business": "corporate", "premium": "luxury", "elegant": "luxury", "film": "cinematic", "movie": "cinematic",
           "motivation": "motivational", "inspirational": "motivational", "tutorial": "explainer", "how it works": "explainer"}
KEYWORDS = {
    "luxury": "luxury luxurious premium elegant gold golden jewel jewellery perfume fragrance watch fashion couture exclusive prestige refined opulent",
    "news": "breaking news headline bulletin report update anchor broadcast live",
    "social": "tiktok reels instagram viral social trend trending shorts story stories hashtag followers",
    "high_energy": "sale promo promotion discount offer hype club party energy energetic drop launch giveaway extreme fast bold deal weekend",
    "corporate": "corporate company business b2b enterprise bank fintech insurance consulting investors professional partner solution",
    "documentary": "documentary history story true real people heritage behind journey interview testimony",
    "explainer": "explain explainer how steps step guide tutorial works learn process feature features app",
    "motivational": "motivation motivational inspire inspiring inspiration success dream believe hustle grind mindset discipline champion rule kingdom",
    "cinematic": "cinematic film movie trailer epic dramatic moody dark atmospheric cinema",
}
CURRENT = {"name": "modern", "explicit": False}


def pick_style(prompt, hint=""):
    """The style name for a brief. A line 'STYLE: x' or 'MOTION STYLE: x' wins; otherwise the words of the brief (and the planner's style hint) decide."""
    text = str(prompt or "")
    m = re.search(r"^[ \t]*(?:MOTION[ \t]+)?STYLE[ \t]*:[ \t]*(.+?)[ \t]*$", text, re.I | re.M)
    if m:
        w = m.group(1).strip().lower()
        w = ALIASES.get(w, w.replace("-", "_").replace(" ", "_"))
        if w in STYLES:
            return w, True
        for key, val in ALIASES.items():
            if key in m.group(1).lower() and val in STYLES:
                return val, True
        for k in STYLES:
            if k.replace("_", " ") in m.group(1).lower():
                return k, True
    low = (text + " " + str(hint or "")).lower()
    for key, val in ALIASES.items():
        if re.search(r"(?<![a-z])" + re.escape(key) + r"(?![a-z])", low) and (key in ("news broadcast", "modern corporate", "high energy", "high-energy", "social media")):
            return val, False
    score = {}
    words = re.findall(r"[a-z]+", low)
    for st, kw in KEYWORDS.items():
        ks = set(kw.split())
        score[st] = sum(1 for w in words if w in ks)
    best = max(score, key=lambda k: score[k])
    return (best, False) if score[best] >= 2 else ("modern", False)


def set_style(prompt, hint=""):
    name, explicit = pick_style(prompt, hint)
    CURRENT["name"], CURRENT["explicit"] = name, explicit
    return name


def style_note(name=None):
    """Lines for the director's prompt: the look of this style. The studio itself adds the transitions between pictures, the camera drift and the motion blur."""
    name = name or CURRENT["name"]
    s = STYLES.get(name) or STYLES["modern"]
    return (f"\nMOTION STYLE: {s['label']}. {s['text']} "
            "The studio adds the transitions between full-screen pictures, the motion blur and the slow drift of pictures by itself: do not add 'transition' layers unless the brief asks for one, "
            "and never use the same text entrance for every text. Every movement needs a reason (what moves, when it starts, where it stops) and ends on a clear hold.\n")


# ----------------------------------------------------------------------------- helpers
def _num(v, d=0.0):
    try:
        return float(v)
    except (TypeError, ValueError):
        return d


def _fullbleed(l, W):
    return l.get("type") == "image" and _num((l.get("props") or {}).get("width")) >= 0.9 * W


def _ambient(l, dur):
    return l.get("type") in ("particles", "captions", "transition") or (l.get("start", 0) <= 0.01 and l.get("end", 0) >= dur - 0.05)


def _pics(tl):
    W, dur = tl["width"], tl["duration"]
    return sorted([l for l in tl["layers"] if _fullbleed(l, W) and not _ambient(l, dur)], key=lambda x: x["start"])


def sample(keys, t, default):
    """Same keyframe sampling as the renderer (linear here; only used to check positions)."""
    if not keys:
        return default
    ks = sorted(keys, key=lambda k: k[0])
    if t <= ks[0][0]:
        return float(ks[0][1])
    if t >= ks[-1][0]:
        return float(ks[-1][1])
    for a, b in zip(ks, ks[1:]):
        if a[0] <= t <= b[0]:
            return float(a[1]) + (float(b[1]) - float(a[1])) * (t - a[0]) / max(1e-6, b[0] - a[0])
    return default


def _set_track(layer, name, keys):
    """Adds a keyframe track only when the layer does not already have one (what the script or director set is kept). Returns True when added."""
    anim = layer.setdefault("anim", {}) or {}
    layer["anim"] = anim
    if anim.get(name):
        return False
    anim[name] = [list(k) for k in keys]
    return True


def _near_sound(audio, t, names, win=0.3):
    for a in audio or []:
        if a.get("role") == "sfx" and a.get("sfx") in names and abs(_num(a.get("start")) - t) <= win:
            return True
    return False


def _choose(style, i, prev, allowed, rnd):
    w = {k: v for k, v in STYLES[style]["tx"].items() if k in allowed}
    if prev in w and len(w) > 1:
        w = {k: v for k, v in w.items() if k != prev}
    if not w:
        w = {"crossfade": 1}
    kinds = list(w)
    return rnd.choices(kinds, weights=[w[k] for k in kinds])[0]


# ----------------------------------------------------------------------------- 1. transitions
def transitions(tl, style, audio):
    """Treatment for every boundary between two full-screen pictures. Returns report lines."""
    W, H, dur = tl["width"], tl["height"], tl["duration"]
    st = STYLES[style]
    pics = _pics(tl)
    trans = [l for l in tl["layers"] if l["type"] == "transition"]
    rnd = random.Random(sum(map(ord, style)) + len(pics))
    done, prev = [], None
    blur_amt = 22 * st["blur"]
    for i, (A, B) in enumerate(zip(pics, pics[1:])):
        tb = B["start"]
        if any(abs(((t["start"] + t["end"]) / 2) - tb) < 0.5 for t in trans):
            prev = None                                      # a transition the script asked for: kept
            continue
        gap = tb - A["start"]
        last = (i == len(pics) - 2)
        allowed = {"crossfade", "push", "zoom", "whip", "wipe", "flash", "dip", "match"}
        if gap < 1.3:
            allowed &= {"flash", "whip", "push", "wipe"}
        if gap < 0.7:
            allowed &= {"flash", "whip"}
        kind = None
        if _near_sound(audio, tb, ("hit", "riser", "boom")) and "flash" in st["tx"]:
            kind = "flash"
        elif last and gap >= 1.3:
            kind = _choose(style, i, prev, allowed & {"zoom", "dip", "match", "crossfade", "flash"}, rnd) if allowed & {"zoom", "dip", "match", "crossfade", "flash"} else None
        if kind is None:
            kind = _choose(style, i, prev, allowed, rnd)
        x0A, x0B = _num(A.get("x"), W / 2), _num(B.get("x"), W / 2)
        pal = tl.get("palette") or {}
        dt = {"crossfade": 0.5, "push": 0.5, "zoom": 0.45, "whip": 0.3, "wipe": 0.65, "flash": 0.4, "dip": 0.7, "match": 0.55}[kind]
        if style in ("luxury", "documentary"):
            dt *= 1.35
        dt = min(dt, max(0.2, gap * 0.45))
        if kind in ("crossfade", "push", "zoom", "whip", "match"):          # the outgoing picture stays under the incoming one while it arrives
            A["end"] = round(min(dur, max(A["end"], tb + dt)), 3)
            A["exit"] = None
            B["z"] = max(_num(B.get("z"), 10), _num(A.get("z"), 10) + 0.01)
        ok = False
        if kind == "crossfade":
            if not B.get("enter"):
                B["enter"] = {"preset": "fade", "dur": round(dt, 3), "ease": "inOutQuad"}
            ok = True
        elif kind in ("push", "whip"):
            d = dt
            ok = _set_track(A, "x", [[tb, x0A], [tb + d, x0A - W * 1.02, "inOutQuart"]])
            ok = _set_track(B, "x", [[tb, x0B + W * 1.02], [tb + d, x0B, "inOutQuart"]]) or ok
            b = blur_amt * (1.3 if kind == "whip" else 0.8)
            if b >= 1:
                _set_track(A, "blur", [[tb, 0], [tb + d * 0.5, b, "inQuad"], [tb + d, b, "linear"]])
                _set_track(B, "blur", [[tb, b], [tb + d * 0.55, b * 0.6, "linear"], [tb + d, 0, "outQuad"]])
        elif kind == "zoom":
            ok = _set_track(A, "scale", [[tb, 1.0], [tb + dt, 1.4, "inQuart"]])
            _set_track(A, "opacity", [[tb + dt * 0.35, 1.0], [tb + dt, 0.0, "inQuad"]])
            ok = _set_track(B, "scale", [[tb, 0.72], [tb + dt, 1.0, "outQuart"]]) or ok
            if not B.get("enter"):
                B["enter"] = {"preset": "fade", "dur": round(dt * 0.6, 3), "ease": "outQuad"}
            b = 12 * st["blur"]
            if b >= 1:
                _set_track(A, "blur", [[tb, 0], [tb + dt, b, "inQuad"]])
                _set_track(B, "blur", [[tb, b], [tb + dt, 0, "outQuad"]])
        elif kind == "match":                                               # the outgoing picture ends at a push; the incoming one starts at the same size and settles: it feels like one continuous move
            s = 1.0 + (0.1 + 0.05 * st["blur"])
            ok = _set_track(A, "scale", [[max(A["start"], tb - 0.45), 1.0], [tb + dt, s, "inQuad"]])
            ok = _set_track(B, "scale", [[tb, s], [tb + 0.7, 1.0, "outQuart"]]) or ok
            if not B.get("enter"):
                B["enter"] = {"preset": "fade", "dur": round(dt, 3), "ease": "outQuad"}
        elif kind in ("flash", "wipe", "dip"):
            if kind == "dip":
                tk = {"kind": "fade", "color": "#000000"}
                a, b2 = tb - dt * 0.5, tb + dt * 0.5
            elif kind == "flash":
                tk = {"kind": "flash", "color": "#ffffff", "intensity": 0.6 if st["bold"] else 0.35}
                a, b2 = tb - 0.12, tb + 0.28
            else:
                tk = {"kind": "wipe", "direction": "right" if i % 2 == 0 else "left", "color": pal.get("primary") if style in ("news", "corporate", "explainer") else "#000000"}
                a, b2 = tb - dt * 0.5, tb + dt * 0.5
            tl["layers"].append({"id": f"mx_{kind}{i}", "type": "transition", "start": round(max(0.0, a), 3), "end": round(min(dur, b2), 3), "x": W / 2, "y": H / 2, "z": 95, "parallax": 0,
                                 "enter": None, "exit": None, "anim": {}, "props": tk})
            ok = True
        if ok:
            A["tx"] = B["tx"] = kind
            done.append(kind)
            prev = kind
    return [f"transitions: {', '.join(done)}"] if done else []


# ----------------------------------------------------------------------------- 2. motion blur on fast entrances
FAST = {"slideUp", "slideDown", "slideLeft", "slideRight", "drop", "zoomIn", "rotateIn", "scaleIn"}


def motion_blur(tl, style):
    st = STYLES[style]
    if st["blur"] < 0.5:
        return []
    n = 0
    for l in tl["layers"]:
        if l["type"] in ("captions", "particles", "transition", "magic", "group") or _fullbleed(l, tl["width"]):
            continue
        en = l.get("enter") or {}
        if en.get("preset") in FAST and _num(en.get("dur"), 0.7) <= 0.65:
            t0 = _num(l["start"]) + _num(en.get("delay"))
            d = _num(en.get("dur"), 0.7)
            b = round((9 if en["preset"] in ("drop", "slideUp", "slideDown") else 7) * st["blur"], 1)
            if _set_track(l, "blur", [[t0, b], [t0 + d * 0.7, 0, "outQuad"]]):
                n += 1
    return [f"motion blur on {n} fast entrance(s)"] if n else []


# ----------------------------------------------------------------------------- 3. camera
def camera(tl, style):
    """The style's camera, only when the director gave no real camera move."""
    st = STYLES[style]
    cam = tl.get("camera") or []
    dur = tl["duration"]
    if len(cam) >= 3:
        return []
    a = st["cam"]
    e = st["cam_ease"]
    tl["camera"] = [[0.0, 1.0, 0, 0, 0, e], [round(dur * 0.55, 2), round(1 + a * 0.6, 3), 24, -18, 0, e], [round(dur, 2), round(1 + a, 3), -18, -34, 0, e]]
    return [f"{st['label']} camera drift"]


# ----------------------------------------------------------------------------- 4. quality pass
def quality(tl, style, assets):
    st = STYLES[style]
    W, H, dur = tl["width"], tl["height"], tl["duration"]
    lines = []
    pics = _pics(tl)
    # a) pictures with no movement of their own get a drift; identical drifts are varied (never the same speed and direction everywhere)
    lo, hi = st["kb"]
    seq = [(1, 0), (0, -1), (-1, 0), (0, 1)]
    seen = {}
    added = varied = 0
    for i, p in enumerate(pics):
        pr = p.setdefault("props", {})
        has_motion = bool(pr.get("kenBurns")) or (any((p.get("anim") or {}).get(k) for k in ("scale", "x", "y")) and not p.get("tx"))      # a short transition move is not a drift
        zin = (i % 2 == 0)
        amount = lo + (hi - lo) * (0.35 + 0.65 * ((i * 37) % 10) / 9.0)
        px, py = seq[i % 4]
        kb = {"from": 1.0 if zin else round(amount, 3), "to": round(amount, 3) if zin else 1.0, "panX": int(px * 26), "panY": int(py * 26)}
        if not has_motion:
            pr["kenBurns"] = kb
            added += 1
        else:
            k = pr.get("kenBurns")
            if k:
                sig = (round(_num(k.get("from"), 1), 2), round(_num(k.get("to"), 1), 2), int(_num(k.get("panX"))), int(_num(k.get("panY"))))
                seen[sig] = seen.get(sig, 0) + 1
                if seen[sig] >= 2:
                    pr["kenBurns"] = kb
                    varied += 1
                if style in ("luxury", "documentary", "corporate", "news"):
                    mx = max(_num(pr["kenBurns"].get("from"), 1), _num(pr["kenBurns"].get("to"), 1))
                    if mx > hi + 0.02:
                        f, t_ = _num(pr["kenBurns"].get("from"), 1), _num(pr["kenBurns"].get("to"), 1)
                        pr["kenBurns"]["from"], pr["kenBurns"]["to"] = (min(f, hi), min(t_, hi))
                        varied += 1
    if added:
        lines.append(f"{added} still picture(s) given a slow drift")
    if varied:
        lines.append(f"{varied} repeated or too strong drift(s) varied")
    # b) moves that leave the frame: a layer that rests mostly outside the screen is pulled back
    pulled = 0
    for l in tl["layers"]:
        if l["type"] not in ("text", "image", "shape", "icon", "counter") or _fullbleed(l, W) or _ambient(l, dur):
            continue
        anim = l.get("anim") or {}
        for name, lim in (("x", W), ("y", H)):
            ks = anim.get(name)
            if not ks:
                continue
            for k in ks:
                if k[1] < -0.35 * lim or k[1] > 1.35 * lim:
                    # a key far outside the screen is fine as an entrance (the first key), not as a place to rest
                    if k is ks[0] and len(ks) > 1:
                        continue
                    k[1] = max(0.06 * lim, min(0.94 * lim, k[1]))
                    pulled += 1
    if pulled:
        lines.append(f"{pulled} move(s) that left the frame pulled back")
    # c) hard cuts with nothing to soften them: a short crossfade
    soft = 0
    for A, B in zip(pics, pics[1:]):
        if B.get("tx") or B.get("enter"):
            continue
        near = [t for t in tl["layers"] if t["type"] == "transition" and abs((t["start"] + t["end"]) / 2 - B["start"]) < 0.5]
        if near:
            continue
        B["enter"] = {"preset": "fade", "dur": 0.2, "ease": "outQuad"}
        A["end"] = round(min(dur, max(A["end"], B["start"] + 0.2)), 3)
        soft += 1
    if soft:
        lines.append(f"{soft} hard cut(s) softened")
    # d) calm styles stay calm: no shaking or bouncing left in the entrances
    if not st["bold"]:
        calmed = 0
        for l in tl["layers"]:
            en = l.get("enter") or {}
            if en.get("preset") == "pop" and l["type"] in ("text",) and style in ("luxury", "documentary", "corporate", "news"):
                en["preset"] = "slideUp" if style in ("corporate", "news") else "fade"
                en.pop("ease", None)
                calmed += 1
            pr = l.get("props") or {}
            if pr.get("wiggle") and style in ("luxury", "documentary"):
                pr.pop("wiggle", None)
                calmed += 1
        if calmed:
            lines.append(f"{calmed} bouncy or shaky effect(s) calmed for the {st['label']} style")
    # e) report: the same text entrance used everywhere
    ens = [(l.get("enter") or {}).get("preset") for l in tl["layers"] if l["type"] == "text" and l.get("enter")]
    if len(ens) >= 5 and len(set(ens)) == 1:
        alts = {"high_energy": ["pop", "zoomIn", "slideUp", "drop"], "social": ["pop", "scaleIn", "slideUp"], "luxury": ["fade", "blurIn"], "documentary": ["fade", "slideUp"],
                "corporate": ["slideUp", "slideLeft", "fade"], "news": ["slideLeft", "wipe", "slideUp"], "cinematic": ["blurIn", "fade", "riseGlow"], "motivational": ["scaleIn", "zoomIn", "blurIn"],
                "explainer": ["pop", "slideUp", "fade"], "modern": ["slideUp", "scaleIn", "blurIn"]}[style]
        k = 0
        for l in tl["layers"]:
            if l["type"] == "text" and l.get("enter") and (l["enter"].get("preset") == ens[0]):
                k += 1
                if k % 2 == 0 and not (l.get("props") or {}).get("mode") in ("words", "chars", "typewriter"):
                    l["enter"]["preset"] = alts[(k // 2) % len(alts)]
        lines.append("text entrances varied (one effect was used everywhere)")
    return lines


# ----------------------------------------------------------------------------- 5. subjects
def subjects(tl, style, assets):
    """Cut-out people and products (transparent pictures) in front of a background picture: a different depth, a slow independent drift."""
    st = STYLES[style]
    W, H, dur = tl["width"], tl["height"], tl["duration"]
    pics = _pics(tl)
    n = 0
    for l in tl["layers"]:
        if l["type"] != "image" or _fullbleed(l, W) or _ambient(l, dur):
            continue
        a = (assets or {}).get((l.get("props") or {}).get("asset"), {})
        if not a.get("alpha") or _num((l.get("props") or {}).get("width")) < 0.28 * W:
            continue
        bg = [p for p in pics if p["start"] < l["end"] - 0.3 and p["end"] > l["start"] + 0.3]
        if not bg:
            continue
        if "parallax" not in l or l.get("parallax") in (None, 1, 1.0):
            l["parallax"] = round(1.0 + 0.2 * st["parallax"], 3)
        for p in bg:
            if p.get("parallax") in (None, 1, 1.0):
                p["parallax"] = round(1.0 - 0.14 * st["parallax"], 3)
        if style not in ("news", "corporate") and not (l.get("anim") or {}).get("y"):
            y0 = _num(l.get("y"), H / 2)
            amp = 9 * st["parallax"] + 3
            t0, t1 = l["start"], l["end"]
            if t1 - t0 > 1.2:
                _set_track(l, "y", [[t0, y0 + amp], [round((t0 + t1) / 2, 3), y0 - amp, "inOutQuad"], [t1, y0 + amp, "inOutQuad"]])
        n += 1
    return [f"{n} cut-out subject(s) given depth (parallax) and a slow drift"] if n else []


# ----------------------------------------------------------------------------- the department
def apply(tl, audio, assets, style=None):
    """Runs the whole department. Returns (timeline, report lines). Any failure returns the timeline as it was."""
    keep = copy.deepcopy(tl)
    try:
        style = style or CURRENT["name"]
        if style not in STYLES:
            style = "modern"
        lines = [f"motion style: {STYLES[style]['label']}" + (" (your choice)" if CURRENT.get("explicit") else "")]
        for fn in (lambda: camera(tl, style), lambda: transitions(tl, style, audio), lambda: motion_blur(tl, style), lambda: subjects(tl, style, assets), lambda: quality(tl, style, assets)):
            try:
                lines += fn()
            except Exception as e:  # noqa: BLE001
                print("motion step skipped:", str(e)[:120])
        return tl, lines
    except Exception as e:  # noqa: BLE001
        print("motion department skipped:", str(e)[:120])
        return keep, []

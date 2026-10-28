"""Timeline validation and clean-up.

The director (AI) writes a timeline as JSON. This module makes sure the renderer can play it:
unknown block types are dropped, times are clamped, missing assets are reported, text is sized so
it fits, and overlapping text is found. Nothing here invents creative content.
"""
import copy
import math
import re

ALLOWED_TYPES = {"image", "video", "text", "shape", "icon", "line", "particles", "counter", "captions", "transition"}
EASES = {"linear", "in", "out", "inOut", "inQuad", "outQuad", "inOutQuad", "outQuart", "inOutQuart", "outExpo", "inExpo",
         "inOutExpo", "outBack", "inBack", "outElastic", "spring"}
PRESETS = {"none", "fade", "slideUp", "slideDown", "slideLeft", "slideRight", "scaleIn", "zoomIn", "pop", "blurIn", "wipe",
           "rotateIn", "drop", "riseGlow", "draw"}
ICONS = {"shield", "check", "lock", "card", "bolt", "globe", "phone", "coin", "arrow", "star", "play", "wifi", "user",
         "chart", "heart", "mail", "clock", "home", "bell", "cart"}
FONTS = {"Inter", "Poppins", "Montserrat", "Space Grotesk", "Playfair Display", "Bebas Neue", "Oswald", "DM Sans", "Outfit", "Sora", "Anton"}
SIZES = {"9:16": (1080, 1920), "16:9": (1920, 1080), "1:1": (1080, 1080), "4:5": (1080, 1350)}
NARROW_FONTS = {"bebasneue", "anton", "oswald"}


def size_for(aspect):
    return SIZES.get(str(aspect or "9:16"), SIZES["9:16"])


def _num(v, default=None):
    try:
        f = float(v)
        if math.isnan(f) or math.isinf(f):
            return default
        return f
    except Exception:
        return default


def _ease(e):
    return e if e in EASES else "inOut"


def _clean_keys(keys, warn, where):
    out = []
    for k in keys or []:
        if not isinstance(k, (list, tuple)) or len(k) < 2:
            warn.append(f"{where}: bad keyframe dropped")
            continue
        t, v = _num(k[0]), k[1]
        if t is None:
            continue
        if isinstance(v, str):
            fv = _num(v)
            if fv is None:
                continue
            v = fv
        v = _num(v)
        if v is None:
            continue
        item = [round(max(0.0, t), 3), v]
        if len(k) > 2 and isinstance(k[2], str):
            item.append(_ease(k[2]))
        out.append(item)
    out.sort(key=lambda a: a[0])
    return out


def _clean_fx(fx, warn, where, default_dur):
    if not isinstance(fx, dict) or not fx.get("preset"):
        return None
    p = fx["preset"]
    if p not in PRESETS:
        warn.append(f"{where}: unknown preset '{p}' changed to fade")
        p = "fade"
    out = {"preset": p, "dur": min(4.0, max(0.05, _num(fx.get("dur"), default_dur)))}
    if fx.get("ease") in EASES:
        out["ease"] = fx["ease"]
    if _num(fx.get("distance")) is not None:
        out["distance"] = _num(fx["distance"])
    if _num(fx.get("delay")) is not None:
        out["delay"] = max(0.0, _num(fx["delay"]))
    return out


def text_box(layer, W):
    """Approximate size of a text layer in pixels (the renderer wraps lines at maxWidth)."""
    p = layer.get("props", {})
    text = str(p.get("text", ""))
    if layer["type"] == "counter":
        text = f"{p.get('prefix', '')}{int(p.get('to', 0)):,}{p.get('suffix', '')}"
    size = _num(p.get("size"), 72)
    maxw = _num(p.get("maxWidth"), W * 0.84)
    font = re.sub(r"[^a-z]", "", str(p.get("font", "Inter")).lower())
    cw = 0.42 if font in NARROW_FONTS else 0.56
    if p.get("uppercase"):
        cw += 0.08
    cw += (0.03 if _num(p.get("weight"), 700) >= 800 else 0.0) + (_num(p.get("letterSpacing"), 0) / max(size, 1))
    lines = text.split("\n") if layer["type"] == "text" else [text]
    est_lines = 0
    longest = 0.0
    for ln in lines:
        w = len(ln) * cw * size
        longest = max(longest, min(w, maxw))
        est_lines += max(1, math.ceil(w / maxw)) if w else 1
    height = est_lines * size * _num(p.get("lineHeight"), 1.12)
    pad = 0
    if p.get("plate"):
        pad = 48
    return longest + pad, height + pad, est_lines


def normalize(tl, assets, voice_len=None, tail=1.2):
    """Returns (clean_timeline, warnings). `assets` maps asset name -> info dict (kind, width, height...)."""
    warn = []
    tl = copy.deepcopy(tl or {})
    aspect = tl.pop("aspect", None)
    W, H = tl.get("width"), tl.get("height")
    if not (_num(W) and _num(H)):
        W, H = size_for(aspect)
    W, H = int(W), int(H)
    fps = int(_num(tl.get("fps"), 30))
    fps = 30 if fps not in (24, 25, 30, 50, 60) else fps
    duration = _num(tl.get("duration"), 12.0)
    if voice_len:
        duration = max(duration, voice_len + tail)
    duration = round(min(300.0, max(2.0, duration)), 2)
    out = {"version": 1, "width": W, "height": H, "fps": fps, "duration": duration}
    pal = tl.get("palette") if isinstance(tl.get("palette"), dict) else {}
    out["palette"] = {"primary": pal.get("primary", "#3b82f6"), "accent": pal.get("accent", "#f5c451"), "text": pal.get("text", "#ffffff")}
    bg = tl.get("background") if isinstance(tl.get("background"), dict) else {}
    bg = dict(bg)
    if bg.get("type") == "image" and bg.get("asset") not in assets:
        warn.append("background image missing, using gradient")
        bg["type"] = "gradient"
        bg.pop("asset", None)
    out["background"] = bg or {"type": "gradient", "colors": ["#06070d", "#10182f"]}
    cam = []
    for k in tl.get("camera") or []:
        if isinstance(k, (list, tuple)) and len(k) >= 4 and _num(k[0]) is not None:
            item = [max(0.0, _num(k[0])), min(1.8, max(0.8, _num(k[1], 1))), _num(k[2], 0), _num(k[3], 0)]
            item.append(_num(k[4], 0) if len(k) > 4 else 0)
            if len(k) > 5 and isinstance(k[5], str):
                item.append(_ease(k[5]))
            cam.append(item)
    cam.sort(key=lambda a: a[0])
    out["camera"] = cam

    by_stem = {}
    for name in assets:
        by_stem[re.sub(r"\.[A-Za-z0-9]+$", "", name).lower()] = name

    def find_asset(ref):
        if not ref:
            return None
        if ref in assets:
            return ref
        r = str(ref).lower()
        if r in by_stem:
            return by_stem[r]
        r2 = re.sub(r"\.[A-Za-z0-9]+$", "", r)
        if r2 in by_stem:
            return by_stem[r2]
        for stem, name in by_stem.items():
            if r2 and (r2 in stem or stem in r2):
                return name
        return None

    layers, seen = [], set()
    for i, l in enumerate(tl.get("layers") or []):
        if not isinstance(l, dict):
            continue
        typ = l.get("type")
        if typ not in ALLOWED_TYPES:
            warn.append(f"layer '{l.get('id', i)}': type '{typ}' is not supported, dropped")
            continue
        lid = str(l.get("id") or f"{typ}{i}")
        while lid in seen:
            lid += "_"
        seen.add(lid)
        start = min(duration - 0.1, max(0.0, _num(l.get("start"), 0.0)))
        end = _num(l.get("end"), duration)
        end = min(duration, end)
        if end <= start + 0.05:
            end = min(duration, start + 2.0)
        props = dict(l.get("props") or {})
        layer = {"id": lid, "type": typ, "start": round(start, 3), "end": round(end, 3), "props": props}
        for k in ("x", "y", "z", "parallax"):
            if _num(l.get(k)) is not None:
                layer[k] = _num(l[k])
        layer["enter"] = _clean_fx(l.get("enter"), warn, f"layer '{lid}' enter", 0.7)
        layer["exit"] = _clean_fx(l.get("exit"), warn, f"layer '{lid}' exit", 0.5)
        anim = {}
        for name, keys in (l.get("anim") or {}).items():
            ck = _clean_keys(keys, warn, f"layer '{lid}' anim.{name}")
            if ck:
                anim[name] = ck
        layer["anim"] = anim
        if typ in ("image", "video"):
            a = find_asset(props.get("asset"))
            if not a:
                warn.append(f"layer '{lid}': asset '{props.get('asset')}' not found, layer dropped")
                continue
            kind = assets[a].get("kind")
            if typ == "image" and kind != "image":
                warn.append(f"layer '{lid}': '{a}' is not a picture, layer dropped")
                continue
            if typ == "video" and kind != "video":
                warn.append(f"layer '{lid}': '{a}' is not a video, layer dropped")
                continue
            props["asset"] = a
            if not _num(props.get("width")):
                props["width"] = min(W * 0.8, _num(assets[a].get("width"), W * 0.8))
        elif typ in ("text", "counter"):
            size = _num(props.get("size"), 72)
            props["size"] = size
            props["text"] = str(props.get("text", ""))
            if props.get("font") and props["font"] not in FONTS:
                warn.append(f"layer '{lid}': font '{props['font']}' not available, using Inter")
                props["font"] = "Inter"
            # shrink so each explicit line fits the width (lines the director wrote stay as written)
            maxw = _num(props.get("maxWidth"), W * 0.84)
            props["maxWidth"] = maxw
            if typ == "text" and "\n" in props["text"]:
                for _ in range(12):
                    bw, _h, _n = text_box({"type": "text", "props": props}, W)
                    widest = max(len(s) for s in props["text"].split("\n"))
                    est = widest * (0.42 if re.sub(r"[^a-z]", "", str(props.get("font", "Inter")).lower()) in NARROW_FONTS else 0.56) * props["size"]
                    if est <= maxw or props["size"] <= 28:
                        break
                    props["size"] = round(props["size"] * 0.92)
        elif typ == "icon":
            if props.get("name") not in ICONS:
                warn.append(f"layer '{lid}': icon '{props.get('name')}' not in the library, using star")
                props["name"] = "star"
        elif typ == "line":
            pts = [[_num(p[0]), _num(p[1])] for p in (props.get("points") or []) if isinstance(p, (list, tuple)) and len(p) >= 2]
            pts = [p for p in pts if p[0] is not None and p[1] is not None]
            if len(pts) < 2:
                warn.append(f"layer '{lid}': a line needs at least 2 points, dropped")
                continue
            props["points"] = pts
        elif typ == "particles":
            props["count"] = int(min(260, max(1, _num(props.get("count"), 60))))
        elif typ == "captions":
            props["words"] = props.get("words") or []
        layers.append(layer)
    out["layers"] = layers
    return out, warn


def _box(layer, W, H, assets):
    typ, p = layer["type"], layer["props"]
    cx, cy = layer.get("x", W / 2), layer.get("y", H / 2)
    if typ in ("text", "counter"):
        w, h, _ = text_box(layer, W)
    elif typ == "image":
        a = assets.get(p["asset"], {})
        w = _num(p.get("width"), 600)
        ratio = (a.get("height", 1) / a.get("width", 1)) if a.get("width") else 1
        h = _num(p.get("height"), w * ratio)
    elif typ == "icon":
        w = h = _num(p.get("size"), 160)
    elif typ == "shape":
        w, h = _num(p.get("width"), 300), _num(p.get("height"), _num(p.get("width"), 300))
    else:
        return None
    return (cx - w / 2, cy - h / 2, cx + w / 2, cy + h / 2)


def _inter(a, b):
    w = min(a[2], b[2]) - max(a[0], b[0])
    h = min(a[3], b[3]) - max(a[1], b[1])
    return max(0, w) * max(0, h)


def check_layout(tl, assets):
    """Finds problems a viewer would notice: overlapping text, text running off screen, text over icons."""
    W, H = tl["width"], tl["height"]
    issues = []
    boxes = []
    for l in tl["layers"]:
        b = _box(l, W, H, assets)
        if b is None:
            continue
        boxes.append((l, b))
        if l["type"] in ("text", "counter"):
            if b[0] < -4 or b[2] > W + 4 or b[1] < -4 or b[3] > H + 4:
                issues.append(f"text '{l['id']}' runs outside the screen (x {int(b[0])}..{int(b[2])}, y {int(b[1])}..{int(b[3])}, screen {W}x{H})")
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (la, ba), (lb, bb) = boxes[i], boxes[j]
            both_text = la["type"] in ("text", "counter") and lb["type"] in ("text", "counter")
            text_icon = {la["type"], lb["type"]} & {"text", "counter"} and {la["type"], lb["type"]} & {"icon"}
            if not (both_text or text_icon):
                continue
            t0, t1 = max(la["start"], lb["start"]), min(la["end"], lb["end"])
            if t1 - t0 < 0.25:
                continue
            area = _inter(ba, bb)
            smaller = min((ba[2] - ba[0]) * (ba[3] - ba[1]), (bb[2] - bb[0]) * (bb[3] - bb[1])) or 1
            if area / smaller > 0.18:
                issues.append(f"'{la['id']}' and '{lb['id']}' overlap between {t0:.1f}s and {t1:.1f}s")
    return issues

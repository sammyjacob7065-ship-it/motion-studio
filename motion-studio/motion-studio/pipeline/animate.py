"""Animate department: the client sends a finished graphic (a flyer, a poster, a post, a banner, any design, even a flat raw picture) and a prompt;
the studio animates THAT graphic, exactly as it was sent.
  1. READ    Gemini looks at the graphic and lists its parts (headlines, texts, logo, product, buttons, shapes, pictures) with their boxes, and plans an animation for each
             from the client's prompt (what comes first, how it enters, how it lives afterwards, the camera). Without Gemini the studio reads the texts itself (OCR) and uses a standard plan.
  2. SPLIT   every part is lifted out of the picture as its own layer with its real pixels (glow, shadow, outline and anti-aliasing included), and the cleaner rebuilds the
             background under it, so what remains is a clean background plate. Layers are cut from the front to the back, so a part that sat behind another is lifted clean.
             At rest, layers over the plate give back the original graphic pixel for pixel; nothing is redrawn, re-typed or patched.
  3. MOVE    every layer is moved with one smooth transform per frame (slide, pop, zoom, drop, wipe, spin, float, pulse, shine) and the whole graphic gets a camera move.
  4. SOUND   sound effects that fit the mood on every entrance (and the client's music or voice file if one was sent).
Honest limits: parts that overlap each other heavily, or sit on a photograph, leave a rebuilt (guessed) background when they move; very thin or glassy parts get a soft edge."""
import json
import math
import os
import subprocess

import cv2
import numpy as np

import cleaner
import gemini

FPS = 30
Z_DEFAULT = {"text": 90, "button": 60, "logo": 50, "product": 50, "person": 40, "shape": 30, "decor": 20, "photo": 10}
KINDS = tuple(Z_DEFAULT)

READ_SYSTEM = """You are a motion designer reading a finished graphic design (flyer, poster, social post, banner) that will be animated, exactly as designed.
List its parts and plan the animation the client asked for. Reply JSON only:
{"duration":8,"mood":"calm|energetic|bold","camera":{"move":"push|pull|pan_left|pan_right|none","amount":0.06},
 "elements":[{"id":"e1","kind":"text|logo|person|product|button|shape|decor|photo","label":"short name","text":"exact words for a text (same line breaks as separate elements), else empty",
   "box_2d":[ymin,xmin,ymax,xmax],"z":90,
   "in":"fade|slide_up|slide_down|slide_left|slide_right|pop|zoom_in|drop|wipe|spin_in|slam|focus|none","split":"none|letters|words","delay":0.4,"dur":0.7,
   "idle":"none|float|pulse|sway|shine|breathe","out":"none|fade"}]}
Rules:
- box_2d are integers 0-1000 (fractions of picture height and width): the tight box of the part, including its glow or shadow. One element per text LINE or block that is one style. Do not list the plain background.
- ALWAYS list every person and every main subject as its own element (kind person or product), even when they are part of a photo or poster background: each one is animated on its own. Never leave people inside the background.
- kinds: person (a person or a main photographed subject, tight box around the whole figure), text (any words), logo (brand mark), product (a product / person / main object picture), button (a shape that holds a text: list the shape as button, its words as their own text), shape (lines, bars, badges, frames), decor (small ornaments, stickers, icons), photo (a picture inside the design that is not the background).
- z = front-to-back order, larger is in front. Text is in front of what it sits on.
- Follow the client's prompt for style and timing. Build a story: background first, then the main picture or product, then the headline, then smaller texts, then the call-to-action last. Delays are in seconds from the start, the last part must be in by 70% of the duration.
- Fit the animation to the design: bold headlines pop or slide, elegant thin texts fade or wipe, products zoom or drop, logos fade then shine, shapes wipe or slide. Do not use the same entrance for everything.
- idle is what a part does after it arrived (subtle only): people and products breathe or float, buttons pulse, logos shine, most texts none.
- People: use zoom_in, focus or fade (a small move only, they must not travel across the picture); they come before the headline. Give people idle breathe.
- Texts: be bold and sharp. Big headlines: split letters with pop or slam (kinetic type) or words with slide_up. Script or thin texts: wipe or focus. Small lines: split words with fade or slide_up. Do not use plain fade for everything.
- split is only for text: letters (each letter enters after the one before) or words."""

EFFECTS_IN = {"fade", "slide_up", "slide_down", "slide_left", "slide_right", "pop", "zoom_in", "drop", "wipe", "spin_in", "slam", "focus", "none"}
IDLES = {"none", "float", "pulse", "sway", "shine", "breathe"}


# ------------------------------------------------------------------ reading
def _jpeg(img, side=1600):
    h, w = img.shape[:2]
    s = min(1.0, side / max(h, w))
    sm = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
    return cv2.imencode(".jpg", sm, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def _num(v, lo, hi, d):
    try:
        return min(hi, max(lo, float(v)))
    except (TypeError, ValueError):
        return d


def read_layers(img, prompt):
    """Gemini's reading and plan. Returns dict or None."""
    try:
        txt = gemini.generate("The client's prompt: " + (prompt.strip() or "Animate it nicely, professional.") + "\n\nRead this graphic and plan the animation.", system=READ_SYSTEM,
                              images=[(_jpeg(img), "image/jpeg")], json_mode=True, temperature=0.4, max_tokens=8000, rounds=1, timeout=90, deadline=200)
        d = gemini.parse_json(txt)
        return d if isinstance(d, dict) and d.get("elements") else None
    except Exception as e:  # noqa: BLE001
        print("::warning::graphic reading by Gemini failed:", str(e)[:120])
        return None


def ocr_lines(img):
    """Texts without Gemini: Tesseract lines -> [{kind:text,text,box(px)}]."""
    import tempfile
    p = os.path.join(tempfile.mkdtemp(), "g.png")
    cv2.imwrite(p, img)
    try:
        r = subprocess.run(["tesseract", p, "stdout", "--psm", "11", "tsv"], capture_output=True, text=True, timeout=120)
    except Exception:  # noqa: BLE001
        return []
    rows, lines = r.stdout.splitlines()[1:], {}
    for ln in rows:
        c = ln.split("\t")
        if len(c) < 12 or not c[11].strip():
            continue
        try:
            conf = float(c[10])
        except ValueError:
            continue
        if conf < 45:
            continue
        key = (c[2], c[3], c[4])
        x, y, w, h = int(c[6]), int(c[7]), int(c[8]), int(c[9])
        o = lines.setdefault(key, {"t": [], "b": [x, y, x + w, y + h]})
        o["t"].append(c[11].strip())
        b = o["b"]
        o["b"] = [min(b[0], x), min(b[1], y), max(b[2], x + w), max(b[3], y + h)]
    out = []
    for o in lines.values():
        t = " ".join(o["t"])
        if len(t) >= 2 and sum(ch.isalnum() for ch in t) >= 2:
            out.append({"kind": "text", "text": t, "box": o["b"]})
    return out


def standard_plan(texts, W, H, prompt):
    """A professional default when Gemini is not available: the biggest text first, smaller ones after, one gentle camera push."""
    els = sorted(texts, key=lambda e: -(e["box"][3] - e["box"][1]))
    ins = ["pop", "slide_up", "fade", "slide_up", "fade", "wipe"]
    out = []
    for i, e in enumerate(els):
        out.append({"id": f"e{i + 1}", "kind": "text", "label": e["text"][:30], "text": e["text"], "box": e["box"], "z": 90 - i, "in": ins[i % len(ins)],
                    "delay": 0.5 + 0.45 * i, "dur": 0.7, "idle": "none", "out": "none"})
    return {"duration": 8, "mood": "energetic", "camera": {"move": "push", "amount": 0.05}, "elements": out}


def normalise(plan, W, H):
    """Validated elements with pixel boxes, sensible timing."""
    els = []
    for i, e in enumerate(plan.get("elements") or []):
        if not isinstance(e, dict):
            continue
        kind = str(e.get("kind", "decor")).lower()
        kind = kind if kind in KINDS else "decor"
        box = e.get("box")
        if not box:
            b = e.get("box_2d")
            try:
                y0, x0, y1, x1 = [float(v) / 1000.0 for v in b]
                box = [x0 * W, y0 * H, x1 * W, y1 * H]
            except (TypeError, ValueError):
                continue
        x0, y0, x1, y1 = [float(v) for v in box]
        x0, x1 = max(0, min(x0, x1)), min(W, max(x0, x1))
        y0, y1 = max(0, min(y0, y1)), min(H, max(y0, y1))
        if x1 - x0 < 6 or y1 - y0 < 6 or (x1 - x0) * (y1 - y0) > 0.92 * W * H:
            continue
        ein = str(e.get("in", "fade")).lower()
        idle = str(e.get("idle", "none")).lower()
        els.append({"id": str(e.get("id") or f"e{i + 1}"), "kind": kind, "label": str(e.get("label") or e.get("text") or kind)[:40], "text": str(e.get("text") or ""),
                    "box": [x0, y0, x1, y1], "z": _num(e.get("z"), 0, 200, Z_DEFAULT[kind]), "in": ein if ein in EFFECTS_IN else "fade",
                    "delay": _num(e.get("delay"), 0, 30, 0.4 * i), "dur": _num(e.get("dur"), 0.15, 3, 0.7), "idle": idle if idle in IDLES else "none",
                    "split": str(e.get("split", "none")).lower() if str(e.get("split", "none")).lower() in ("letters", "words") and kind == "text" else "none",
                    "out": "fade" if str(e.get("out")).lower() == "fade" else "none"})
    dur = _num(plan.get("duration"), 3, 30, 8)
    last = max([e["delay"] + e["dur"] for e in els] or [1])
    if last > dur * 0.72:                                          # everything must be in, with time to enjoy the finished graphic
        k = dur * 0.72 / last
        for e in els:
            e["delay"] *= k
    cam = plan.get("camera") or {}
    mv = str(cam.get("move", "push")).lower()
    return {"duration": dur, "mood": str(plan.get("mood", "energetic")).lower(), "camera": {"move": mv if mv in ("push", "pull", "pan_left", "pan_right", "none") else "push",
            "amount": _num(cam.get("amount"), 0, 0.15, 0.05)}, "elements": els}


def gemini_masks(img, elements):
    """Real outlines of people and products from Gemini's segmentation. Returns {element id: full-frame uint8 mask}; empty when Gemini is not available."""
    import base64
    want = [e for e in elements if e["kind"] in ("person", "product")]
    if not want:
        return {}
    H, W = img.shape[:2]
    names = "; ".join(f"{e['label']} (box_2d {[int(e['box'][1] / H * 1000), int(e['box'][0] / W * 1000), int(e['box'][3] / H * 1000), int(e['box'][2] / W * 1000)]})" for e in want)
    out = {}
    try:
        txt = gemini.generate("Give the segmentation masks for these objects of the picture: " + names + ". Output a JSON list where each entry contains the 2D bounding box in the key \"box_2d\", the segmentation mask in the key \"mask\", and the text label in the key \"label\". Cut the whole figure with its hair, hands and clothes, nothing of the background.",
                              images=[(_jpeg(img), "image/jpeg")], json_mode=True, temperature=0.0, max_tokens=30000, rounds=1, timeout=120, deadline=240)
        res = gemini.parse_json(txt)
    except Exception as ex:  # noqa: BLE001
        print("::warning::segmentation by Gemini failed:", str(ex)[:120])
        return {}
    for r in res if isinstance(res, list) else []:
        try:
            y0, x0, y1, x1 = [float(v) / 1000.0 for v in r["box_2d"]]
            bx0, by0, bx1, by1 = int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)
            b64 = str(r["mask"]).split(",")[-1]
            m = cv2.imdecode(np.frombuffer(base64.b64decode(b64), np.uint8), cv2.IMREAD_GRAYSCALE)
            if m is None or bx1 - bx0 < 8 or by1 - by0 < 8:
                continue
            m = (cv2.resize(m, (bx1 - bx0, by1 - by0), interpolation=cv2.INTER_LINEAR) > 127).astype(np.uint8)
            full = np.zeros((H, W), np.uint8)
            full[by0:by1, bx0:bx1] = m
            best, bi = 0.0, None
            for e in want:
                ex0, ey0, ex1, ey1 = e["box"]
                iw, ih = min(bx1, ex1) - max(bx0, ex0), min(by1, ey1) - max(by0, ey0)
                if iw > 0 and ih > 0:
                    iou = iw * ih / ((bx1 - bx0) * (by1 - by0) + (ex1 - ex0) * (ey1 - ey0) - iw * ih)
                    if iou > best:
                        best, bi = iou, e
            if bi is not None and best > 0.35 and bi["id"] not in out:
                out[bi["id"]] = full
        except Exception:  # noqa: BLE001
            continue
    return out


# ------------------------------------------------------------------ splitting
def _outline(img, box):
    """Outline mask of a part inside its box (GrabCut), uint8 in the image frame; the box itself when GrabCut is not convincing."""
    H, W = img.shape[:2]
    x0, y0, x1, y1 = [int(round(v)) for v in box]
    bw, bh = x1 - x0, y1 - y0
    px, py = int(bw * 0.1) + 3, int(bh * 0.1) + 3
    rx0, ry0, rx1, ry1 = max(0, x0 - px), max(0, y0 - py), min(W, x1 + px), min(H, y1 + py)
    roi = img[ry0:ry1, rx0:rx1]
    h, w = roi.shape[:2]
    s = min(1.0, 300.0 / max(w, h))
    small = cv2.resize(roi, (max(8, int(w * s)), max(8, int(h * s))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    rect = (max(1, int((x0 - rx0) * s)), max(1, int((y0 - ry0) * s)), max(4, int(bw * s)), max(4, int(bh * s)))
    rect = (rect[0], rect[1], min(rect[2], sw - rect[0] - 1), min(rect[3], sh - rect[1] - 1))
    m = np.zeros((sh, sw), np.uint8)
    ok = False
    try:
        bgm, fgm = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(small, m, rect, bgm, fgm, 4, cv2.GC_INIT_WITH_RECT)
        mm = ((m == 1) | (m == 3)).astype(np.uint8)
        frac = mm.sum() / max(1, rect[2] * rect[3])
        ok = 0.25 < frac < 0.985
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        mm = np.zeros((sh, sw), np.uint8)
        cv2.rectangle(mm, (rect[0], rect[1]), (rect[0] + rect[2], rect[1] + rect[3]), 1, -1)
    mm = cv2.morphologyEx(mm, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    n, lab, st, _ = cv2.connectedComponentsWithStats(mm)
    if n > 2:                                                       # holes and specks: keep the biggest piece plus pieces of real size
        keep = np.zeros_like(mm)
        big = st[1:, 4].max()
        for k in range(1, n):
            if st[k, 4] >= 0.12 * big:
                keep[lab == k] = 1
        mm = keep
    mm = cv2.resize(mm, (w, h), interpolation=cv2.INTER_LINEAR if s < 1 else cv2.INTER_NEAREST)
    full = np.zeros((H, W), np.uint8)
    full[ry0:ry1, rx0:rx1] = (mm > 0).astype(np.uint8)
    return full


def lift(plate, e, holes, masks=None):
    """Takes the part out of the plate (in place). Returns the layer: premultiplied float32 BGRA sprite + origin, or None."""
    H, W = plate.shape[:2]
    x0, y0, x1, y1 = e["box"]
    bw, bh = x1 - x0, y1 - y0
    if e["kind"] == "text":
        pad = int(max(bw, bh) * 0.04) + 4
        bx0, by0, bx1, by1 = max(0, int(x0) - pad), max(0, int(y0) - pad), min(W, int(x1) + pad), min(H, int(y1) + pad)
        th = by1 - by0
        m = int(th * 0.9) + 10
        rx0, ry0, rx1, ry1 = max(0, bx0 - m), max(0, by0 - m), min(W, bx1 + m), min(H, by1 + m)
        roi = plate[ry0:ry1, rx0:rx1].copy()
        inner = (bx0 - rx0, by0 - ry0, bx1 - rx0, by1 - ry0)
        clean, mask, q = cleaner.clean(roi, inner, margin=0.25, strokes=True)
        holes[ry0:ry1, rx0:rx1] |= (cv2.dilate(mask, np.ones((3, 3), np.uint8)) > 0).astype(np.uint8)
        d = np.linalg.norm(roi.astype(np.float32) - clean.astype(np.float32), axis=2)
        sel = d[mask > 0]
        dmax = float(np.percentile(sel, 92)) if sel.size else 0.0
        if dmax < 12:
            return None
        R, C = roi.astype(np.float32), clean.astype(np.float32)
        strong = (d > 0.8 * dmax) & (mask > 0)
        Ft = np.median(R[strong], axis=0) if strong.sum() > 5 else R[mask > 0].mean(axis=0)
        v, u = R - C, Ft[None, None, :] - C
        uu = np.maximum((u * u).sum(axis=2), 1.0)
        t = (v * u).sum(axis=2) / uu
        err = np.linalg.norm(v - t[..., None] * u, axis=2)
        lum = lambda x: x[..., 0] * 0.114 + x[..., 1] * 0.587 + x[..., 2] * 0.299
        light_text = lum(Ft[None, None, :]) > lum(C)
        other = np.where(light_text, 0.0, 255.0)[..., None] * np.ones(3, np.float32)       # the other kind of difference: a dark shadow behind light text (or a light glow behind dark text)
        lc = np.maximum(lum(C), 1.0)
        a_other = np.where(light_text, 1 - lum(R) / lc, (lum(R) - lum(C)) / np.maximum(255.0 - lum(C), 1.0))
        a_text = np.clip(t, 0, 1)
        is_text = t > 0
        a = np.where(is_text, a_text, np.clip(a_other, 0, 1))
        F = np.where(is_text[..., None], Ft[None, None, :], other)
        off = (err > 0.3 * np.sqrt(uu)) & (d > 0.3 * dmax)                        # a colour the two-colour model cannot make (an outline, a gradient text): kept as it is
        a = np.where(off, 1.0, a)
        F = np.where(off[..., None], R, F)
        a[d < max(5.0, 0.04 * dmax)] = 0
        a[cv2.dilate(mask, np.ones((5, 5), np.uint8)) == 0] = 0
        a[a < 0.03] = 0
        a = a.astype(np.float32)
        plate[ry0:ry1, rx0:rx1] = clean
        ys, xs = np.nonzero(a > 0.02)
        if not len(xs):
            return None
        cx0, cy0, cx1, cy1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
        F, a = F[cy0:cy1, cx0:cx1], a[cy0:cy1, cx0:cx1]
        return {"P": np.dstack([F * a[..., None], a]).astype(np.float32), "ox": rx0 + cx0, "oy": ry0 + cy0, "q": q}
    # an object: its own outline, the background rebuilt under it
    work = plate
    hb = holes[max(0, int(y0) - 4):int(y1) + 4, max(0, int(x0) - 4):int(x1) + 4]
    if hb.any():                                                    # text lifted from over this part left holes in it: filled from the part's own pixels first
        work = plate.copy()
        hm = cv2.dilate(holes, np.ones((3, 3), np.uint8))
        work = cv2.inpaint(work, (hm * 255).astype(np.uint8), 3, cv2.INPAINT_TELEA)
    full = (masks or {}).get(e["id"])
    if full is not None:
        full = cv2.morphologyEx(full, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    else:
        full = _outline(work, e["box"])
    big = e["kind"] == "person"
    if big and (masks or {}).get(e["id"]) is None:                    # no real outline of the person (Gemini mask missing): only a convincing cut is used, a box-shaped one is not
        e["nomask"] = True
        if full.sum() > 0.82 * max(1.0, (x1 - x0) * (y1 - y0)):
            return None
    ys, xs = np.nonzero(full)
    if not len(xs):
        return None
    ox0, oy0, ox1, oy1 = xs.min(), ys.min(), xs.max() + 1, ys.max() + 1
    m = int(max(ox1 - ox0, oy1 - oy0) * 0.25) + 12
    rx0, ry0, rx1, ry1 = max(0, ox0 - m), max(0, oy0 - m), min(W, ox1 + m), min(H, oy1 + m)
    roi = work[ry0:ry1, rx0:rx1].copy()
    fm = cv2.dilate(full[ry0:ry1, rx0:rx1], np.ones((5, 5), np.uint8), iterations=3 if big else 2)
    inner = (ox0 - rx0, oy0 - ry0, ox1 - rx0, oy1 - ry0)
    if big:
        clean, mask, q = cleaner.push_pull(roi, fm), fm, 0.0
    else:
        clean, mask, q = cleaner.clean(roi, inner, margin=0.1, force=fm)
    sel = cv2.dilate(mask, np.ones((9, 9), np.uint8)) > 0
    pv = plate[ry0:ry1, rx0:rx1]
    pv[sel] = clean[sel]
    a = full[ry0:ry1, rx0:rx1].astype(np.float32)
    a = cv2.GaussianBlur(cv2.erode(a, np.ones((3, 3), np.uint8)), (0, 0), 1.0)
    a = a[oy0 - ry0:oy1 - ry0, ox0 - rx0:ox1 - rx0]
    F = roi[oy0 - ry0:oy1 - ry0, ox0 - rx0:ox1 - rx0].astype(np.float32)
    return {"P": np.dstack([F * a[..., None], a]).astype(np.float32), "ox": ox0, "oy": oy0, "q": q}


def _pieces(L):
    """A text cut into letters or words (at the empty columns between them); each piece enters after the one before it."""
    e = L["e"]
    P = L["P"]
    h, w = P.shape[:2]
    core = (P[..., 3] > 0.4).any(axis=0)
    cols = np.nonzero(core)[0]
    if len(cols) < 4:
        return [L]
    rows = np.nonzero((P[..., 3] > 0.4).any(axis=1))[0]
    rh = max(8, rows.max() - rows.min() + 1)
    gmin = 1 if e["split"] == "letters" else max(4, int(rh * 0.3))
    cuts, start, prev = [], cols[0], cols[0]
    for c in cols[1:]:
        if c - prev - 1 >= gmin:
            cuts.append((start, prev + 1))
            start = c
        prev = c
    cuts.append((start, prev + 1))
    if len(cuts) < 2 or len(cuts) > 40:
        return [L]
    bounds = [0] + [(cuts[i][1] + cuts[i + 1][0]) // 2 for i in range(len(cuts) - 1)] + [w]
    stag = min(0.07 if e["split"] == "letters" else 0.16, 0.9 / len(cuts))
    out = []
    for i in range(len(cuts)):
        c0, c1 = bounds[i], bounds[i + 1]
        ee = dict(e, delay=e["delay"] + i * stag, dur=max(0.3, e["dur"] * 0.85), split="none")
        out.append({"P": P[:, c0:c1].copy(), "ox": L["ox"] + c0, "oy": L["oy"], "q": L["q"], "e": ee})
    return out


def split(img, elements, masks=None):
    """(plate, layers) : layers cut from the front to the back; each layer gets the element's data."""
    plate = img.copy()
    holes = np.zeros(img.shape[:2], np.uint8)
    layers = []
    for e in sorted(elements, key=lambda x: -x["z"]):
        try:
            L = lift(plate, e, holes, masks)
        except Exception as ex:  # noqa: BLE001
            print("::warning::part not lifted:", e["label"], str(ex)[:100])
            L = None
        if L is None:
            e["lifted"] = False
            continue
        e["lifted"] = True
        L["e"] = e
        layers.extend(_pieces(L) if e.get("split", "none") != "none" else [L])
    layers.sort(key=lambda L: L["e"]["z"])                         # back to front for drawing
    _sweep(plate, [L["e"]["box"] for L in layers])
    return plate, layers


def _sweep(plate, boxes):
    """Last look at the plate: thin slivers of a lifted part that the outline missed are rebuilt (only next to where a part was)."""
    H, W = plate.shape[:2]
    zone = np.zeros((H, W), np.uint8)
    for x0, y0, x1, y1 in boxes:
        zone[max(0, int(y0) - 14):int(y1) + 14, max(0, int(x0) - 14):int(x1) + 14] = 1
    ref = cv2.GaussianBlur(cv2.medianBlur(plate, 31), (0, 0), 6)
    diff = np.abs(plate.astype(np.int16) - ref.astype(np.int16)).max(axis=2)
    bad = ((diff > 28) & (zone > 0)).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(bad)
    keep = np.zeros_like(bad)
    for k in range(1, n):
        if st[k, 4] < 900:
            keep[lab == k] = 1
    if keep.any():
        plate[:] = cv2.inpaint(plate, cv2.dilate(keep, np.ones((5, 5), np.uint8)) * 255, 5, cv2.INPAINT_TELEA)


# ------------------------------------------------------------------ moving
def _out_cubic(p):
    return 1 - (1 - p) ** 3


def _out_back(p, k=1.7):
    return 1 + (k + 1) * (p - 1) ** 3 + k * (p - 1) ** 2


def _out_expo(p):
    return 1.0 if p >= 1 else 1 - 2 ** (-10 * p)


def _bounce(p):
    n, d = 7.5625, 2.75
    if p < 1 / d:
        return n * p * p
    if p < 2 / d:
        p -= 1.5 / d
        return n * p * p + 0.75
    if p < 2.5 / d:
        p -= 2.25 / d
        return n * p * p + 0.9375
    p -= 2.625 / d
    return n * p * p + 0.984375


def state(e, t, W, H):
    """Transform of one part at time t: dx, dy (original px), scale, rotation (deg), alpha, clip (0..1 of its width shown), shine (0..1 or -1)."""
    s = {"dx": 0.0, "dy": 0.0, "sc": 1.0, "rot": 0.0, "a": 1.0, "clip": 1.0, "shine": -1.0, "blur": 0.0}
    p = (t - e["delay"]) / e["dur"]
    if e["kind"] == "person":                                       # a person is on screen from the first frame (the picture behind is a soft wash); the entrance is a camera-like move
        p = max(0.0, p)
    if p <= 0 and e["in"] != "none" and e["kind"] != "person":
        s["a"] = 0.0
        return s
    p = min(1.0, max(0.0, p)) if e["in"] != "none" else 1.0
    k = e["in"]
    D = 0.09 * H
    if k == "fade":
        s["a"] = _out_cubic(p)
    elif k == "slide_up":
        s["a"], s["dy"] = _out_cubic(min(1, p * 1.6)), D * (1 - _out_expo(p))
    elif k == "slide_down":
        s["a"], s["dy"] = _out_cubic(min(1, p * 1.6)), -D * (1 - _out_expo(p))
    elif k == "slide_left":
        s["a"], s["dx"] = _out_cubic(min(1, p * 1.6)), 0.12 * W * (1 - _out_expo(p))
    elif k == "slide_right":
        s["a"], s["dx"] = _out_cubic(min(1, p * 1.6)), -0.12 * W * (1 - _out_expo(p))
    elif k == "pop":
        s["a"], s["sc"] = min(1, p * 3), 0.55 + 0.45 * _out_back(p)
    elif k == "zoom_in":
        s["a"], s["sc"] = _out_cubic(min(1, p * 1.5)), 1.35 - 0.35 * _out_cubic(p)
    elif k == "drop":
        s["a"], s["dy"] = min(1, p * 4), -0.5 * H * (1 - _bounce(p))
    elif k == "wipe":
        s["clip"] = _out_cubic(p)
    elif k == "slam":
        s["a"], s["sc"] = min(1, p * 5), 1 + 0.9 * (1 - _out_expo(p))
    elif k == "focus":
        s["a"], s["blur"] = min(1, p * 2.2), (0.0 if e.get("nomask") else 14.0 * (1 - _out_cubic(p)))
    elif k == "spin_in":
        s["a"], s["sc"], s["rot"] = min(1, p * 2.5), 0.5 + 0.5 * _out_back(p), -28 * (1 - _out_cubic(p))
    if e["kind"] == "person":
        s["a"], s["clip"] = 1.0, 1.0
    if t > e["delay"] + e["dur"]:                                   # alive after arriving
        u = t - (e["delay"] + e["dur"])
        if e["idle"] == "float":
            s["dy"] += 0.008 * H * math.sin(u * 2.2)
        elif e["idle"] == "pulse":
            s["sc"] *= 1 + 0.03 * math.sin(u * 4.0)
        elif e["idle"] == "breathe":
            s["sc"] *= 1 + 0.012 * math.sin(u * 1.6)
            s["dy"] += 0.004 * H * math.sin(u * 1.1)
        elif e["idle"] == "sway":
            s["rot"] += 1.6 * math.sin(u * 1.8)
        elif e["idle"] == "shine":
            cyc = (u % 2.6) / 0.9
            s["shine"] = cyc if cyc <= 1 else -1.0
    return s


def _matrix(L, st, S, cam, W, H, Wo, Ho):
    """3x3 matrix from sprite pixels to output pixels."""
    h, w = L["P"].shape[:2]
    cx, cy = L["ox"] + w / 2, L["oy"] + h / 2
    r = math.radians(st["rot"])
    c, sn = math.cos(r) * st["sc"], math.sin(r) * st["sc"]
    A = np.array([[c, -sn, cx + st["dx"] - (c * w / 2 - sn * h / 2)], [sn, c, cy + st["dy"] - (sn * w / 2 + c * h / 2)], [0, 0, 1]], np.float64)
    return _cam_matrix(S, cam, W, H, Wo, Ho) @ A


def _cam_matrix(S, cam, W, H, Wo, Ho):
    z, px, py = cam
    return np.array([[S * z, 0, Wo / 2 + px - S * z * W / 2], [0, S * z, Ho / 2 + py - S * z * H / 2], [0, 0, 1]], np.float64)


def _camera(plan_cam, t, T, W, H, S):
    amt, mv = plan_cam["amount"], plan_cam["move"]
    p = min(1.0, t / max(0.1, T))
    e = p * p * (3 - 2 * p)
    if mv == "push":
        return 1 + amt * e, 0.0, 0.0
    if mv == "pull":
        return 1 + amt * (1 - e), 0.0, 0.0
    if mv in ("pan_left", "pan_right"):
        sgn = -1 if mv == "pan_left" else 1
        return 1 + amt, sgn * amt * 0.5 * W * S * (e - 0.5) * 2, 0.0
    return 1.0, 0.0, 0.0


def _sprite_for(L, st):
    """Sprite with the wipe and the shine applied (in sprite space), as premultiplied BGRA."""
    P = L["P"]
    if st["clip"] >= 0.999 and st["shine"] < 0 and st.get("blur", 0) < 0.4:
        return P
    P = P.copy()
    if st.get("blur", 0) >= 0.4:                                    # focus pull: from blurred to sharp
        k = int(st["blur"] * 3) | 1
        P = cv2.GaussianBlur(cv2.copyMakeBorder(P, 20, 20, 20, 20, cv2.BORDER_CONSTANT, value=0), (k, k), st["blur"])[20:-20, 20:-20]
    h, w = P.shape[:2]
    if st["clip"] < 0.999:
        xs = np.arange(w, dtype=np.float32)
        edge = max(4.0, w * 0.04)
        m = np.clip((st["clip"] * (w + edge) - xs) / edge, 0, 1)
        P *= m[None, :, None]
    if st["shine"] >= 0:
        xs = np.arange(w, dtype=np.float32)[None, :] + 0.35 * np.arange(h, dtype=np.float32)[:, None]
        pos = -0.3 * (w + 0.35 * h) + st["shine"] * 1.6 * (w + 0.35 * h)
        band = np.exp(-((xs - pos) / max(6.0, w * 0.07)) ** 2)
        P[..., :3] = np.minimum(P[..., :3] + (P[..., 3:4] * 255.0) * band[..., None] * 0.55, 255.0 * P[..., 3:4])
    return P


def frame_at(plate, layers, plan, t, S, Wo, Ho):
    H, W = plate.shape[:2]
    T = plan["duration"]
    cam = _camera(plan["camera"], t, T, W, H, S)
    Mp = _cam_matrix(S, cam, W, H, Wo, Ho)[:2]
    frame = cv2.warpAffine(plate, Mp, (Wo, Ho), flags=cv2.INTER_CUBIC if S * cam[0] > 1 else cv2.INTER_AREA if S < 1 else cv2.INTER_LINEAR, borderMode=cv2.BORDER_REPLICATE).astype(np.float32)
    for L in layers:
        e = L["e"]
        st = state(e, t, W, H)
        al = st["a"]
        if e["out"] == "fade":
            if t > T - 0.35:
                al *= float(np.clip((T - t) / 0.35, 0, 1))
        if al <= 0.003 or st["clip"] <= 0.003:
            continue
        M = _matrix(L, st, S, cam, W, H, Wo, Ho)
        h, w = L["P"].shape[:2]
        corners = M @ np.array([[0, w, w, 0], [0, 0, h, h], [1, 1, 1, 1]], np.float64)
        bx0, by0 = max(0, int(math.floor(corners[0].min())) - 2), max(0, int(math.floor(corners[1].min())) - 2)
        bx1, by1 = min(Wo, int(math.ceil(corners[0].max())) + 2), min(Ho, int(math.ceil(corners[1].max())) + 2)
        if bx1 <= bx0 or by1 <= by0:
            continue
        T2 = np.array([[1, 0, -bx0], [0, 1, -by0], [0, 0, 1]], np.float64) @ M
        sc_tot = math.sqrt(abs(np.linalg.det(M[:2, :2])))
        pr = cv2.warpAffine(_sprite_for(L, st), T2[:2], (bx1 - bx0, by1 - by0), flags=cv2.INTER_CUBIC if sc_tot > 1 else cv2.INTER_LINEAR, borderMode=cv2.BORDER_CONSTANT, borderValue=0)
        a = np.clip(pr[..., 3:4], 0, 1) * al
        frame[by0:by1, bx0:bx1] = pr[..., :3] * al + (1 - a) * frame[by0:by1, bx0:bx1]
    return np.clip(frame, 0, 255).astype(np.uint8)


# ------------------------------------------------------------------ sound
def sound_items(plan, sfx):
    mood = plan.get("mood", "energetic")
    items = []
    for e in plan["elements"]:
        if not e.get("lifted"):
            continue
        k = e["in"]
        name = {"slide_up": "whoosh", "slide_down": "whoosh", "slide_left": "whoosh", "slide_right": "whoosh", "pop": "pop", "zoom_in": "pop", "drop": "hit" if mood == "bold" else "pop",
                "spin_in": "swoosh_up", "wipe": "swoosh_up", "slam": "hit" if mood == "bold" else "pop", "focus": "swoosh_up", "fade": "shimmer" if mood == "calm" else None}.get(k)
        if mood == "calm" and name in ("whoosh", "pop"):
            name = "shimmer"
        if name == "hit" and e["kind"] != "text":
            name = "pop"
        if name and name in sfx:
            items.append({"path": sfx[name], "start": max(0.0, e["delay"] + e["dur"] * 0.15), "volume": 0.5 if name != "hit" else 0.7, "role": "sfx"})
    for e in plan["elements"]:
        if e.get("lifted") and e["idle"] == "shine" and "sparkle" in sfx:
            items.append({"path": sfx["sparkle"], "start": e["delay"] + e["dur"] + 0.1, "volume": 0.35, "role": "sfx"})
    return items[:24]


# ------------------------------------------------------------------ the job
def target_scale(W, H):
    short = min(W, H)
    if short < 1080:
        return min(1080.0 / short, 2.5) if max(W, H) * min(1080.0 / short, 2.5) <= 2400 else 2400.0 / max(W, H)
    return min(1.0, 1920.0 / max(W, H))


def make(image_path, prompt, out_path, work, audio=None, progress=None, plan=None):
    """Animates the graphic. Returns a report dict: elements (with lifted True/False), duration, engine."""
    img = cv2.imread(image_path, cv2.IMREAD_COLOR)
    if img is None:
        from PIL import Image
        img = cv2.cvtColor(np.array(Image.open(image_path).convert("RGB")), cv2.COLOR_RGB2BGR)
    H, W = img.shape[:2]
    engine = "Gemini"
    raw = plan if plan is not None else read_layers(img, prompt)
    if raw is None:
        engine = "standard plan (texts read by OCR)"
        raw = standard_plan(ocr_lines(img), W, H, prompt)
    plan = normalise(raw, W, H)
    if not plan["elements"]:
        raise RuntimeError("I could not find any parts (texts, logo, product, shapes) in this graphic to animate. Send the graphic as a File (not Photo) so the quality stays original, or a clearer copy.")
    if progress:
        progress("split", f"{len(plan['elements'])} parts")
    import bgremove
    masks = bgremove.subject_masks(img, [{"id": e["id"], "label": e["label"], "box": e["box"]} for e in plan["elements"] if e["kind"] in ("person", "product")])
    plate, layers = split(img, plan["elements"], masks)
    if not layers:
        raise RuntimeError("I found the parts but could not lift any of them cleanly from the picture.")
    S = target_scale(W, H)
    Wo, Ho = int(round(W * S / 2)) * 2, int(round(H * S / 2)) * 2
    T = plan["duration"]
    n = int(T * FPS)
    silent = os.path.join(work, "anim_silent.mp4")
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{Wo}x{Ho}", "-r", str(FPS), "-i", "-", "-an", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-movflags", "+faststart", silent]
    pr = subprocess.Popen(cmd, stdin=subprocess.PIPE)
    for i in range(n):
        pr.stdin.write(frame_at(plate, layers, plan, i / FPS, S, Wo, Ho).tobytes())
        if progress and i % 30 == 0:
            progress("render", f"{i * 100 // n}%")
    pr.stdin.close()
    if pr.wait() != 0:
        raise RuntimeError("The video could not be written.")
    import mix
    items = []
    try:
        sfx = mix.make_sfx(os.path.join(work, "sfx"))
        items = sound_items(plan, sfx)
    except Exception as e:  # noqa: BLE001
        print("::warning::sound effects skipped:", str(e)[:100])
    if audio:
        items.append({"path": audio, "start": 0.0, "volume": 0.9, "role": "music", "loop": True, "dur": T})
    if items:
        mix.mix(silent, items, T, out_path)
    else:
        os.replace(silent, out_path)
    return {"elements": plan["elements"], "duration": T, "engine": engine, "mood": plan["mood"], "size": (Wo, Ho), "camera": plan["camera"]}

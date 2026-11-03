"""Logo and product swap inside the client's own video.
For every brand logo or product the video shows (found from the deep reading, whatever it is), the studio
  1. looks at sample frames (Gemini vision) and locates it: a box on every sample frame, 'not visible' where it is not on screen;
  2. follows it between the samples (smooth interpolation) and cuts its real outline out of every frame (GrabCut inside the box);
  3. paints the old logo/product away (inpainting) and puts the client's own logo/product picture in its place: same position, size, tilt and
     fade, product pictures bottom-aligned like the old product stood, the picture with the best proportions chosen from the client's pictures.
Nothing is specific to one brand or one video: what to find is the description from the reading, what to put is whatever the client sent.
Honest limits: a product that turns around in 3D, is covered by hands, liquid or condensation, or leaves frames fast, is followed less reliably, and a picture cannot turn
(the closest angle is used)."""
import io
import json
import math

import cv2
import numpy as np
from PIL import Image

import gemini

BATCH = 8
SAMPLE_S = 0.3


def elements_from(ref, duration):
    """The logos and products of the reading that belong to the original brand, with their time on screen (absolute seconds)."""
    out = []
    for si, sc in enumerate((ref or {}).get("scenes") or []):
        s0, s1 = float(sc.get("start") or 0), float(sc.get("end") or duration)
        for el in sc.get("elements") or []:
            if not isinstance(el, dict) or el.get("kind") not in ("logo", "product"):
                continue
            if el.get("brand_specific") is False:
                continue
            a, b = el.get("appears"), el.get("disappears")
            try:
                a, b = float(a), float(b)
            except (TypeError, ValueError):
                a, b = s0, s1
            if a < s0 - 0.01:                                  # times given inside the scene: made absolute
                a, b = s0 + a, s0 + b
            a, b = max(s0, min(a, s1)), max(s0, min(b, s1))
            if b - a < 0.15:
                a, b = s0, s1
            out.append({"kind": el["kind"], "desc": str(el.get("content") or el["kind"]), "role": el.get("role", ""), "scene": si + 1, "t0": a, "t1": b,
                        "position": el.get("position", ""), "id": f"{el['kind']}{len(out) + 1}"})
    return out


def merge_same(elements, gap=0.4):
    """The same logo shown in two scenes in a row is one element for the whole span (one track, no flicker at the cut)."""
    out = []
    for e in sorted(elements, key=lambda x: (x["kind"], x["desc"].lower(), x["t0"])):
        p = out[-1] if out else None
        if p and p["kind"] == e["kind"] and p["desc"].lower() == e["desc"].lower() and e["t0"] - p["t1"] <= gap:
            p["t1"] = max(p["t1"], e["t1"])
            continue
        out.append(dict(e))
    return sorted(out, key=lambda x: x["t0"])


DETECT = """These pictures (#0, #1 ...) are consecutive frames of an advert, in time order. Find: {desc} ({kind}).
For EVERY picture say whether it is visible and give its tight bounding box. Reply JSON only:
{{"frames":[{{"i":0,"visible":true,"box_2d":[ymin,xmin,ymax,xmax]}}]}}
Coordinates are integers from 0 to 1000 (fractions of the picture height and width). The box must include the whole {kind} and nothing else. If it is not visible or only a tiny part shows, visible is false."""


def detect(jpegs, desc, kind):
    """Boxes (normalised 0..1: x0,y0,x1,y1) or None per frame, from Gemini vision."""
    out = [None] * len(jpegs)
    for a in range(0, len(jpegs), BATCH):
        chunk = jpegs[a:a + BATCH]
        try:
            txt = gemini.generate(DETECT.format(desc=desc, kind=kind), images=list(reversed([(j, "image/jpeg") for j in chunk])), json_mode=True, temperature=0.0,
                                  max_tokens=4000, rounds=1, timeout=90, deadline=200)
            d = gemini.parse_json(txt)
        except Exception as e:  # noqa: BLE001
            print("::warning::object detection failed:", str(e)[:100])
            continue
        for r in d.get("frames") or []:
            try:
                i = int(r["i"])
                b = r.get("box_2d")
                if r.get("visible") and b and 0 <= i < len(chunk):
                    y0, x0, y1, x1 = [float(v) / 1000.0 for v in b]
                    if x1 - x0 > 0.01 and y1 - y0 > 0.01:
                        out[a + i] = (x0, y0, x1, y1)
            except (KeyError, TypeError, ValueError):
                continue
    return out


def interpolate(samples, idxs, nframes):
    """Per-frame boxes (pixels) from the sample boxes: linear between two visible samples, nothing outside the first/last visible one (plus half a gap)."""
    vis = [(f, b) for f, b in zip(idxs, samples) if b is not None]
    boxes = {}
    if not vis:
        return boxes
    for (fa, ba), (fb, bb) in zip(vis, vis[1:]):
        if fb - fa > 3 * (idxs[1] - idxs[0] if len(idxs) > 1 else 10):          # a long hole: the object left the screen
            boxes[fa] = ba
            continue
        for f in range(fa, fb):
            t = (f - fa) / max(1, fb - fa)
            boxes[f] = tuple(ba[k] * (1 - t) + bb[k] * t for k in range(4))
    boxes[vis[-1][0]] = vis[-1][1]
    gap = max(1, (idxs[1] - idxs[0]) // 2 if len(idxs) > 1 else 3)
    f0, f1 = vis[0][0], vis[-1][0]
    for k in range(1, gap + 1):
        boxes.setdefault(max(0, f0 - k), vis[0][1])
        if f1 + k < nframes:
            boxes.setdefault(f1 + k, vis[-1][1])
    # a light smoothing so the new picture does not jitter
    fs = sorted(boxes)
    arr = np.array([boxes[f] for f in fs])
    if len(arr) >= 5:
        ker = np.ones(5) / 5
        pad = np.pad(arr, ((2, 2), (0, 0)), mode="edge")
        arr = np.stack([np.convolve(pad[:, k], ker, mode="valid") for k in range(4)], axis=1)
    return {f: tuple(float(v) for v in arr[i]) for i, f in enumerate(fs)}


def _segment(fr, box, W, H):
    """Outline of the object inside the box (GrabCut). Returns (mask uint8 full-ROI, roi origin, angle) or a filled box when GrabCut is not convincing."""
    x0, y0, x1, y1 = box
    bw, bh = x1 - x0, y1 - y0
    px, py = int(bw * 0.12) + 2, int(bh * 0.12) + 2
    rx0, ry0, rx1, ry1 = max(0, int(x0) - px), max(0, int(y0) - py), min(W, int(x1) + px), min(H, int(y1) + py)
    roi = fr[ry0:ry1, rx0:rx1]
    h, w = roi.shape[:2]
    if w < 8 or h < 8:
        return None
    s = min(1.0, 256.0 / max(w, h))
    small = cv2.resize(roi, (max(8, int(w * s)), max(8, int(h * s))), interpolation=cv2.INTER_AREA)
    sh, sw = small.shape[:2]
    rect = (max(1, int((x0 - rx0) * s)), max(1, int((y0 - ry0) * s)), max(4, int(bw * s)), max(4, int(bh * s)))
    rect = (rect[0], rect[1], min(rect[2], sw - rect[0] - 1), min(rect[3], sh - rect[1] - 1))
    mask = np.zeros((sh, sw), np.uint8)
    ok = False
    try:
        bg, fg = np.zeros((1, 65), np.float64), np.zeros((1, 65), np.float64)
        cv2.grabCut(small, mask, rect, bg, fg, 3, cv2.GC_INIT_WITH_RECT)
        m = ((mask == 1) | (mask == 3)).astype(np.uint8)
        frac = m.sum() / max(1, rect[2] * rect[3])
        ok = 0.18 < frac < 0.97
    except Exception:  # noqa: BLE001
        ok = False
    if not ok:
        m = np.zeros((sh, sw), np.uint8)
        cv2.rectangle(m, (rect[0], rect[1]), (rect[0] + rect[2], rect[1] + rect[3]), 1, -1)
    m = cv2.morphologyEx(m, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    m = cv2.resize(m, (w, h), interpolation=cv2.INTER_NEAREST)
    angle = 0.0
    cnts, _ = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    if cnts:
        (cx, cy), (rw, rh), ang = cv2.minAreaRect(max(cnts, key=cv2.contourArea))
        a = ang if rw < rh else ang - 90                       # the angle of the long side away from vertical
        angle = float(((a + 45) % 90) - 45)
    # the old object is painted away completely: its outline plus the whole box (a little larger), so no edge of it is left behind
    gx0, gy0 = int(max(0, (x0 - rx0) - bw * 0.05)), int(max(0, (y0 - ry0) - bh * 0.05))
    gx1, gy1 = int(min(w, (x1 - rx0) + bw * 0.05)), int(min(h, (y1 - ry0) + bh * 0.05))
    m[gy0:gy1, gx0:gx1] = 1
    m = cv2.dilate(m, np.ones((5, 5), np.uint8), iterations=2)
    return m, (rx0, ry0), angle


def best_asset(assets, box):
    """The client's picture whose proportions are closest to the old object's box."""
    bw, bh = max(1, box[2] - box[0]), max(1, box[3] - box[1])
    want = bw / bh
    return min(assets, key=lambda a: abs(math.log(max(0.05, a["w"] / a["h"]) / want)))


class Swap:
    def __init__(self, element, boxes, assets, W, H, fade=6):
        self.e, self.boxes, self.assets, self.W, self.H = element, boxes, assets, W, H
        self.fs = sorted(boxes)
        self.fade = fade
        self._cache = {}

    def active(self, fi):
        return fi in self.boxes

    def _alpha(self, fi):
        if not self.fs:
            return 0.0
        d = min(fi - self.fs[0], self.fs[-1] - fi)
        return float(np.clip((d + 1) / self.fade, 0, 1))

    def apply(self, fr, fi):
        box = self.boxes.get(fi)
        if box is None:
            return fr
        seg = _segment(fr, box, self.W, self.H)
        if seg is None:
            return fr
        m, (rx0, ry0), angle = seg
        h, w = m.shape
        roi = fr[ry0:ry0 + h, rx0:rx0 + w]
        asset = best_asset(self.assets, box)
        bw, bh = box[2] - box[0], box[3] - box[1]
        if self.e["kind"] == "logo":
            k = min(bw / asset["w"], bh / asset["h"]) * 1.0
        else:
            k = bh / asset["h"] * 1.0
            if asset["w"] * k > bw * 1.35:
                k = bw * 1.35 / asset["w"]
        tw, th = max(2, int(asset["w"] * k)), max(2, int(asset["h"] * k))
        key = (id(asset), tw // 4, th // 4, int(angle * 2))
        pic = self._cache.get(key)
        if pic is None:
            pic = asset["img"].resize((tw, th), Image.LANCZOS)
            if abs(angle) > 3 and self.e["kind"] == "product":
                pic = pic.rotate(-angle, expand=True, resample=Image.BICUBIC)
            self._cache = {key: pic}
        cx = (box[0] + box[2]) / 2
        if self.e["kind"] == "product":                        # a product stands on its base: bottom aligned
            py = box[3] - pic.height
        else:
            py = (box[1] + box[3]) / 2 - pic.height / 2
        px = cx - pic.width / 2
        layer = Image.new("RGBA", (self.W, self.H), (0, 0, 0, 0))
        layer.paste(pic, (int(round(px)), int(round(py))), pic)
        la = np.array(layer.getchannel("A"), dtype=np.float32) / 255.0
        # 1. paint the old object away where the new picture does not cover it
        inpaint_mask = m.copy()
        cover = (la[ry0:ry0 + h, rx0:rx0 + w] > 0.5).astype(np.uint8)
        inpaint_mask = (inpaint_mask & (1 - cv2.dilate(cover, np.ones((3, 3), np.uint8)))) | (m & (1 - cover))
        alpha = self._alpha(fi)
        out = fr.copy()
        if inpaint_mask.sum() > 20:
            clean = cv2.inpaint(roi, (m * 255).astype(np.uint8), 5, cv2.INPAINT_TELEA)
            keep = (m > 0)[..., None]
            out[ry0:ry0 + h, rx0:rx0 + w] = np.where(keep, clean, roi)
        # 2. the new picture on top
        rgb = np.array(layer.convert("RGB"), dtype=np.float32)[..., ::-1]
        a = (la * alpha)[..., None]
        return (out * (1 - a) + rgb * a).astype(np.uint8)


def load_assets(paths):
    """RGBA pictures of the client's logo / product (a plain background is cut away when it is plain)."""
    out = []
    for p in paths:
        try:
            im = Image.open(p)
            im.load()
            im = im.convert("RGBA")
            if im.getchannel("A").getextrema()[0] >= 250:
                try:
                    import assets as A
                    cp = A.cutout(p)
                    if cp:
                        im = Image.open(cp).convert("RGBA")
                except Exception:  # noqa: BLE001
                    pass
            bb = im.getchannel("A").point(lambda v: 255 if v > 16 else 0).getbbox()
            if bb:
                im = im.crop(bb)
            out.append({"img": im, "w": im.width, "h": im.height, "path": p})
        except Exception as e:  # noqa: BLE001
            print("::warning::picture not usable for the swap:", p, str(e)[:80])
    return out

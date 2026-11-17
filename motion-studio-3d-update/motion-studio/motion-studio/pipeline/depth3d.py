"""3D department: turns ONE flat picture into real-looking depth, and a cut-out product into a turnable 3D object.
  depth    (layer type "depth")   the picture is cut into depth slices (far background ... nearest subject) with the hidden parts painted in, and the camera
                                  moves through them (orbit, push, drift ...): near things travel more than far things, the subject separates from the background. 2.5D parallax.
  solid3d  (layer type "solid3d") a cut-out product becomes a real turnable object: a thick slab (phone, box, card, shoe) or a round body (bottle, can, jar), with a rim,
                                  shading that follows the turn, a moving highlight and a plain back (or the back picture the client sent).
The director only writes the layer; this module makes the files the renderer needs (slices, back picture), checks them, and expands "spin" / "swing" into rotation keys.
Everything is optional and safe: if anything fails the layer falls back to a plain picture layer, never to a broken render.
Depth source, best first: a depth model (transformers 'depth-estimation', used only when installed and DEPTH_AI=1), otherwise the subject cut-out + the ground-plane rule
(lower in the frame = nearer, smoothed). Honest limits: a flat photo has no information behind the subject, so large moves reveal painted (guessed) background;
the studio keeps the move small (a few percent) and the plate larger than the frame so nothing shows."""
import os
import re

import cv2
import numpy as np
from PIL import Image

CYL_WORDS = re.compile(r"\b(bottle|can|jar|tube|cup|tin|drum|cylinder|flask|canister|tumbler|mug|glass|keg|barrel|shaker|spray|deodorant|candle)\b", re.I)


def _rgba(path):
    im = Image.open(path)
    return im.convert("RGBA")


def _subject_alpha(rgb, a0, subject=None):
    """Alpha (0-255 uint8, same size as the picture) of the main subject, or None when the picture has no separable subject.
    A picture that already is a cut-out gives its own alpha; otherwise the studio's remover department decides (plain background, Gemini, a model)."""
    if a0.min() < 250 and (a0 < 128).mean() > 0.03:
        return _clean_subject(a0)
    try:
        import bgremove
        rgba, rep = bgremove.remove(cv2.cvtColor(rgb, cv2.COLOR_RGB2BGR), subject=subject, allow_basic=False)
        if rgba is not None:
            ca = rgba[:, :, 3]
            cov = (ca > 128).mean()
            if 0.02 < cov < 0.9:
                return _clean_subject(ca)
    except Exception as e:  # noqa: BLE001
        print("::warning::depth: subject cut-out failed:", str(e)[:100])
    return None


def _clean_subject(a):
    """The subject mask without holes or specks. The biggest pieces are kept; the insides are filled, even a gap that touches the outside (a white label on a white
    background cuts a bottle in two): per row the object spans from its left to its right edge, and rows with nothing take the span of the rows around them."""
    m = (a > 128).astype(np.uint8)
    n, lab, st, _c = cv2.connectedComponentsWithStats(m, connectivity=8)
    if n > 1:
        big = max(st[1:, cv2.CC_STAT_AREA])
        keep = [i for i in range(1, n) if st[i, cv2.CC_STAT_AREA] >= 0.01 * big]
        m = np.isin(lab, keep).astype(np.uint8)
    cnts, _h = cv2.findContours(m, cv2.RETR_EXTERNAL, cv2.CHAIN_APPROX_SIMPLE)
    filled = np.zeros_like(m)
    cv2.drawContours(filled, cnts, -1, 1, thickness=cv2.FILLED)
    # row-span fill (objects that are one body per row: bottles, cans, boxes, phones, shoes, people); skipped when it would add too much
    h, w = m.shape
    rows = np.nonzero(m.any(axis=1))[0]
    span = filled.copy()
    if len(rows) > 3:
        y0, y1 = rows[0], rows[-1]
        xmin = np.full(h, -1.0); xmax = np.full(h, -1.0)
        for y in rows:
            xs = np.nonzero(m[y])[0]
            xmin[y], xmax[y] = xs[0], xs[-1]
        wd = np.where(xmin >= 0, xmax - xmin + 1, 0.0)
        k = max(3, int(0.45 * (y1 - y0)))
        for y in range(y0, y1 + 1):                            # rows far narrower than the body above AND below are broken (a label, text or a highlight took the outline away)
            up, dn = wd[max(y0, y - k):y].max(initial=0), wd[y + 1:y1 + 1][:k].max(initial=0)
            if up > 0 and dn > 0 and wd[y] < 0.55 * min(up, dn):
                xmin[y] = -1
        valid = np.nonzero(xmin >= 0)[0]
        ys = np.arange(y0, y1 + 1)
        lo = np.interp(ys, valid, xmin[valid]); hi = np.interp(ys, valid, xmax[valid])
        span = np.zeros_like(m)
        for y, l0, h0 in zip(ys, lo, hi):
            span[y, int(round(l0)):int(round(h0)) + 1] = 1
        if span.sum() > 2.2 * max(1, filled.sum()):
            span = filled.copy()
        span = np.maximum(span, filled)
    soft = cv2.GaussianBlur(span.astype(np.float32), (0, 0), 1.0)
    out = np.maximum(soft * 255.0 * (span > 0), np.where(m > 0, a.astype(np.float32), 0))
    return np.clip(out, 0, 255).astype(np.uint8)


def _fill_masked(rgb, hole):
    """Colours for a hidden area, taken only from the visible pixels around it (normalised blur at several sizes): smooth, no streaks, no ghost of the object."""
    h, w = hole.shape
    kd = max(11, int(0.03 * w)) | 1                             # keep well away from the object's own edge colours (a cream label must not bleed into the background)
    valid = (~cv2.dilate(hole.astype(np.uint8), np.ones((kd, kd), np.uint8)).astype(bool)).astype(np.float32)
    img = rgb.astype(np.float32)
    out = np.zeros_like(img)
    got = np.zeros((h, w), np.float32)
    for sg in (6, 18, 50, 130):
        k = int(sg * 3) | 1
        num = cv2.GaussianBlur(img * valid[:, :, None], (k, k), sg)
        den = cv2.GaussianBlur(valid, (k, k), sg)
        ok = (den > 0.04) & (got < 0.5)
        out[ok] = (num[ok] / den[ok, None])
        got[ok] = 1.0
    if (got < 0.5).any():
        out[got < 0.5] = img[valid > 0].mean(axis=0) if (valid > 0).any() else 128
    return out


def _ai_depth(rgb):
    """0..1 depth (1 = near) from a depth model when one is installed and wanted (DEPTH_AI=1), else None."""
    if os.environ.get("DEPTH_AI") != "1":
        return None
    try:
        from transformers import pipeline  # type: ignore
        pipe = _ai_depth.pipe = getattr(_ai_depth, "pipe", None) or pipeline("depth-estimation", model=os.environ.get("DEPTH_MODEL", "depth-anything/Depth-Anything-V2-Small-hf"))
        out = pipe(Image.fromarray(rgb))["depth"]
        d = np.array(out.resize((rgb.shape[1], rgb.shape[0]))).astype(np.float32)
        d = (d - d.min()) / max(1e-6, d.max() - d.min())
        return d
    except Exception as e:  # noqa: BLE001
        print("::warning::depth model not used:", str(e)[:100])
        return None


def depth_map(rgb, subj):
    """Depth 0 (far) .. 1 (near), smooth. The subject is always the nearest thing."""
    h, w = rgb.shape[:2]
    d = _ai_depth(rgb)
    if d is None:
        yy = np.linspace(0, 1, h, dtype=np.float32)[:, None] * np.ones((1, w), np.float32)
        d = 0.15 + 0.45 * yy                                    # ground plane: the lower, the nearer
        g = cv2.cvtColor(rgb, cv2.COLOR_RGB2GRAY).astype(np.float32)
        sharp = cv2.GaussianBlur(np.abs(cv2.Laplacian(g, cv2.CV_32F)), (0, 0), max(3, w / 80))
        d += 0.20 * (sharp / (sharp.max() + 1e-6))               # in-focus detail is usually nearer than a soft background
    if subj is not None:
        s = (subj.astype(np.float32) / 255.0)
        d = np.where(s > 0.5, 0.82 + 0.18 * (d - d.min()) / max(1e-6, d.max() - d.min()), np.minimum(d, 0.8))
    d = cv2.GaussianBlur(d.astype(np.float32), (0, 0), max(2, w / 150))
    return np.clip((d - d.min()) / max(1e-6, d.max() - d.min()), 0, 1)


def _inpaint(rgb, hole):
    """Paints the hidden part of a slice from the visible colours around it, blended back softly at the edge of the hidden area."""
    fill = _fill_masked(rgb, hole)
    kh = max(7, int(0.012 * hole.shape[1])) | 1
    soft = np.clip(cv2.GaussianBlur(cv2.dilate(hole.astype(np.uint8), np.ones((kh, kh), np.uint8)).astype(np.float32), (0, 0), 2.5) * 1.8, 0, 1)[:, :, None]
    return (rgb.astype(np.float32) * (1 - soft) + fill * soft).astype(np.uint8)


def make_depth_slices(path, out_base, n=4, subject=None):
    """Writes n PNG slices (far -> near). Returns [(file, depth 0..1)], aspect (height/width)."""
    im = Image.open(path).convert("RGBA")
    if max(im.size) > 1600:
        k = 1600 / max(im.size)
        im = im.resize((int(im.size[0] * k), int(im.size[1] * k)), Image.LANCZOS)
    arr = np.array(im)
    rgb, a0 = arr[:, :, :3], arr[:, :, 3]
    h, w = rgb.shape[:2]
    subj = _subject_alpha(rgb, a0, subject)
    n = max(2, min(6, int(n)))
    d = depth_map(rgb, subj)
    if subj is None and _ai_depth(rgb) is None:
        # no clear subject and no depth model: cutting by guessed depth would tear objects apart when the camera moves, so the picture stays ONE slice
        # (the move is then a camera-like orbit / push of the whole picture, honest 2D) and the report says so
        out = f"{out_base}_d0.png"
        Image.fromarray(np.dstack([rgb, np.where(a0 > 0, a0, 255).astype(np.uint8) if a0.min() < 250 else np.full((h, w), 255, np.uint8)]), "RGBA").save(out, "PNG")
        make_depth_slices.single = True
        return [(out, 0.5)], h / w
    make_depth_slices.single = False
    # bands: the subject is the top band; the rest is split by depth into n-1 bands of equal pixel count
    band = np.zeros((h, w), np.int32)
    if subj is not None:
        sub = subj > 128
        rest = d[~sub] if (~sub).any() else d.ravel()
        qs = np.quantile(rest, np.linspace(0, 1, n)[1:-1]) if n > 2 else []
        band = np.digitize(d, qs).astype(np.int32)
        band = np.where(sub, n - 1, np.minimum(band, n - 2))
    else:
        qs = np.quantile(d, np.linspace(0, 1, n + 1)[1:-1])
        band = np.digitize(d, qs).astype(np.int32)
    files = []
    for k in range(n):
        keep = band >= k                                        # this slice and everything nearer (nearer slices lie over it)
        hole = band > k                                         # what sits in front of this slice: painted out here so a move reveals background, not a ghost
        if k == 0:
            alpha = np.full((h, w), 255, np.uint8)
        else:
            alpha = cv2.GaussianBlur((keep.astype(np.float32)), (0, 0), 1.2)
            if k == n - 1 and subj is not None:
                alpha = np.minimum(alpha, 1.0) * 255.0 * 0 + subj.astype(np.float32)   # the top slice uses the real cut-out edge (hair, glass, soft shadows)
            else:
                alpha = alpha * 255.0
            alpha = np.clip(alpha, 0, 255).astype(np.uint8)
        col = rgb if k == n - 1 else _inpaint(rgb, hole)
        if a0.min() < 250:                                      # the picture itself had transparency: keep it
            alpha = (alpha.astype(np.float32) * (a0.astype(np.float32) / 255.0)).astype(np.uint8)
        out = f"{out_base}_d{k}.png"
        Image.fromarray(np.dstack([col, alpha]), "RGBA").save(out, "PNG")
        files.append((out, round(k / (n - 1), 3)))
    return files, h / w


def plain_back(path, out_path):
    """The back of an object seen from one side: the same outline, with each row painted in that row's average colour (no reversed text, no invented print)."""
    im = np.array(_rgba(path))
    rgb, a = im[:, :, :3].astype(np.float32), im[:, :, 3].astype(np.float32) / 255.0
    wgt = a[:, :, None]
    row = (rgb * wgt).sum(axis=1) / np.maximum(1e-3, wgt.sum(axis=1))          # average colour of each row
    glob = (rgb * wgt).sum(axis=(0, 1)) / max(1e-3, wgt.sum())
    ok = (a.sum(axis=1) > 2)[:, None]
    row = np.where(ok, row, glob[None, :])
    k = int(max(3, im.shape[0] / 20)) | 1
    row = cv2.GaussianBlur(row.reshape(-1, 1, 3).astype(np.float32), (1, k), 0).reshape(-1, 3)
    out = np.dstack([np.repeat(row[:, None, :], im.shape[1], axis=1), a * 255.0]).astype(np.uint8)
    Image.fromarray(out, "RGBA").save(out_path, "PNG")
    return out_path


def edge_color(path):
    """A rim colour for a slab: the colour of the outline pixels, made darker."""
    im = np.array(_rgba(path))
    a = im[:, :, 3]
    m = (a > 200).astype(np.uint8)
    ring = cv2.subtract(m, cv2.erode(m, np.ones((9, 9), np.uint8))) > 0
    px = im[:, :, :3][ring] if ring.any() else im[:, :, :3][m > 0]
    if len(px) == 0:
        return "#222222"
    c = np.median(px, axis=0) * 0.5
    return "#%02x%02x%02x" % tuple(int(v) for v in np.clip(c, 0, 255))


def _spin_keys(sp, start, end, key="rotateY"):
    """props.spin {turns, start, end, ease, dir} / props.swing {angle, start, end, cycles} -> rotation keys (absolute seconds)."""
    s0 = float(sp.get("start", start)); s1 = float(sp.get("end", end))
    if s1 <= s0:
        s1 = s0 + 1.0
    return s0, s1


def expand_motion(layer):
    """spin / swing / tilt shortcuts become keyframe tracks (only where the director did not write the track itself)."""
    p = layer.get("props") or {}
    anim = layer.setdefault("anim", {})
    st, en = float(layer.get("start", 0)), float(layer.get("end", 1))
    sp, sw = p.pop("spin", None), p.pop("swing", None)
    if isinstance(sp, dict) and "rotateY" not in anim:
        s0, s1 = _spin_keys(sp, st, en)
        turns = float(sp.get("turns", 1)) * (-1 if str(sp.get("dir", "right")).lower().startswith("l") else 1)
        anim["rotateY"] = [[round(s0, 3), float(sp.get("from", 0))], [round(s1, 3), float(sp.get("from", 0)) + 360.0 * turns, str(sp.get("ease", "inOutQuad"))]]
    if isinstance(sw, dict) and "rotateY" not in anim:
        s0, s1 = _spin_keys(sw, st, en)
        ang = float(sw.get("angle", 35)); cyc = max(1, int(sw.get("cycles", 2)))
        keys = [[round(s0, 3), 0.0]]
        for i in range(cyc):
            a0 = s0 + (s1 - s0) * (i + 0.5) / cyc
            keys.append([round(s0 + (s1 - s0) * (i + 0.25) / cyc, 3), ang if i % 2 == 0 else -ang, "inOutQuad"])
            keys.append([round(a0 + (s1 - s0) * 0.25 / cyc, 3), -ang if i % 2 == 0 else ang, "inOutQuad"])
        keys.append([round(s1, 3), 0.0, "inOutQuad"])
        anim["rotateY"] = keys
    if p.get("tilt") is not None and "rotateX" not in anim:
        t = float(p.pop("tilt") or 0)
        anim["rotateX"] = [[round(st, 3), t], [round(en, 3), t]]
    return layer


def prepare(layers, registry, paths, adir, work, analyze, cutout_fn=None, notes=None):
    """Makes the files for every depth / solid3d layer (also inside groups). A layer that cannot be built becomes a plain picture layer."""
    notes = notes if notes is not None else []

    def reg(path, origin):
        final, info, flags = analyze(path, work)
        nm = os.path.basename(final)
        info["flags"], info["origin"] = flags, origin
        registry[nm], paths[nm] = info, final
        return nm

    for l in layers:
        typ, p = l.get("type"), l.setdefault("props", {})
        if typ == "group":
            prepare(p.get("children") or [], registry, paths, adir, work, analyze, cutout_fn, notes)
            continue
        if typ not in ("depth", "solid3d"):
            continue
        try:
            name = p.get("asset")
            src = paths.get(name)
            if not src:
                raise RuntimeError(f"picture '{name}' not found")
            stem = os.path.splitext(os.path.basename(src))[0]
            if typ == "depth":
                if not p.get("layers"):
                    files, aspect = make_depth_slices(src, os.path.join(adir, stem), int(p.get("slices") or 4), p.get("subject"))
                    sl = []
                    for fpath, dep in files:
                        sl.append({"asset": reg(fpath, f"depth slice of {name}"), "depth": dep})
                    p["layers"], p["aspect"] = sl, round(aspect, 4)
                p["items"] = [s["asset"] for s in p["layers"]]
                p.setdefault("move", "orbit")
            else:
                a = registry.get(name) or {}
                if not a.get("alpha"):                           # a turnable object needs a clean outline
                    cp = cutout_fn(src) if cutout_fn else None
                    if not cp:
                        raise RuntimeError("could not cut the product out of its background")
                    name = reg(cp, f"cut-out of {name}")
                    src = paths[name]
                    p["asset"] = name
                a = registry.get(name) or {}
                if a.get("width") and a.get("height"):
                    p["aspect"] = round(a["height"] / a["width"], 4)
                what = str((registry.get(name) or {}).get("describe", {}).get("what", "")) + " " + str(p.get("shape", "")) + " " + str(p.get("hint", ""))
                if p.get("mode") not in ("slab", "cylinder"):
                    p["mode"] = "cylinder" if CYL_WORDS.search(what) else "slab"
                items = []
                if p.get("back") and paths.get(p["back"]):
                    items.append(p["back"])
                else:
                    p["back"] = reg(plain_back(src, os.path.join(adir, stem + "_back.png")), f"plain back of {name}")
                    items.append(p["back"])
                if p["mode"] == "slab" and not p.get("edgeColor"):
                    p["edgeColor"] = edge_color(src)
                p["items"] = items
                expand_motion(l)
        except Exception as e:  # noqa: BLE001
            msg = f"3D layer '{l.get('id')}' could not be built ({str(e)[:90]}): shown as a normal picture"
            print("::warning::" + msg)
            notes.append(msg)
            l["type"] = "image"
            keep = {k: v for k, v in p.items() if k in ("asset", "width", "height", "glow", "shadow", "kenBurns", "fit", "radius")}
            l["props"] = keep
            keep.setdefault("width", p.get("width") or 700)
    return layers

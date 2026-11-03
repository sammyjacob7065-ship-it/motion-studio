"""Background-remover department: one place that cuts a subject (a person, a product, a logo, any object) out of ANY picture, plain or busy background.
Used by the whole studio: product pictures that must float, people of a flyer, parts of an animation.
Methods, best first, and each one checked for a sane result:
  1. PLAIN   an even background (studio shot, white or light backdrop) is flood-filled from the edges: exact, white parts inside the subject stay.
  2. GEMINI  Gemini's segmentation of the named subject(s): it knows WHAT to keep (this person, that bottle), even in a crowded picture.
  3. MODEL   a trained background-removal model (rembg: isnet / u2net, installed on first use) for a fine, hair-accurate matte.
             When Gemini and the model are both there, the model's fine edge is kept only where Gemini says the subject is.
  4. GRABCUT the classic fallback inside the subject's box.
Then the edge is finished: holes inside the subject filled, specks removed, a 1-pixel soft edge, and the background colour that clings to the edge pixels is pushed out
(colour decontamination), so hair and clothes do not carry a coloured halo onto a new background.
Honest limits: a subject the same colour as its background, glass and smoke, and fine hair on a busy background are cut less perfectly; the report says which method was used."""
import base64
import os
import subprocess

import cv2
import numpy as np

_SESSION = {}


# ---------------------------------------------------------------- methods
def plain(img):
    """alpha uint8 or None. Only when the border of the picture is an even colour."""
    h, w = img.shape[:2]
    s = min(1.0, 800.0 / max(h, w))
    im = cv2.resize(img, (max(2, int(w * s)), max(2, int(h * s))), interpolation=cv2.INTER_AREA) if s < 1 else img.copy()
    hh, ww = im.shape[:2]
    border = np.concatenate([im[0], im[-1], im[:, 0], im[:, -1]]).astype(np.int16)
    med = np.median(border, axis=0)
    if (np.abs(border - med).max(axis=1) > 60).mean() > 0.22:
        return None
    dist = np.abs(im.astype(np.int16) - med).max(axis=2)
    cand = (dist < 44).astype(np.uint8)
    n, lab = cv2.connectedComponents(cand)
    edge_labels = set(np.unique(np.concatenate([lab[0], lab[-1], lab[:, 0], lab[:, -1]]))) - {0}
    bg = np.isin(lab, list(edge_labels)).astype(np.uint8)
    frac = bg.mean()
    if frac < 0.08 or frac > 0.93:
        return None
    a = ((1 - bg) * 255).astype(np.uint8)
    return cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR) if s < 1 else a


def _jpeg(img, side=1600):
    h, w = img.shape[:2]
    s = min(1.0, side / max(h, w))
    sm = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
    return cv2.imencode(".jpg", sm, [cv2.IMWRITE_JPEG_QUALITY, 90])[1].tobytes()


def gemini_masks(img, subjects):
    """subjects: list of (name, box_px or None). Returns a list of full-size uint8 masks (0/255) aligned with subjects (None when not found)."""
    import gemini
    H, W = img.shape[:2]
    parts = []
    for name, box in subjects:
        if box is not None:
            x0, y0, x1, y1 = box
            parts.append(f"{name} (box_2d {[int(y0 / H * 1000), int(x0 / W * 1000), int(y1 / H * 1000), int(x1 / W * 1000)]})")
        else:
            parts.append(name)
    out = [None] * len(subjects)
    try:
        txt = gemini.generate("Give the segmentation masks for these objects of the picture: " + "; ".join(parts) + ". Output a JSON list where each entry contains the 2D bounding box in the key \"box_2d\", "
                              "the segmentation mask in the key \"mask\", and the text label in the key \"label\". Cut the whole subject with its hair, hands, clothes and everything it holds, nothing of the background.",
                              images=[(_jpeg(img), "image/jpeg")], json_mode=True, temperature=0.0, max_tokens=30000, rounds=1, timeout=120, deadline=240)
        res = gemini.parse_json(txt)
    except Exception as e:  # noqa: BLE001
        print("::warning::segmentation by Gemini failed:", str(e)[:120])
        return out
    found = []
    for r in res if isinstance(res, list) else []:
        try:
            y0, x0, y1, x1 = [float(v) / 1000.0 for v in r["box_2d"]]
            bx0, by0, bx1, by1 = int(x0 * W), int(y0 * H), int(x1 * W), int(y1 * H)
            m = cv2.imdecode(np.frombuffer(base64.b64decode(str(r["mask"]).split(",")[-1]), np.uint8), cv2.IMREAD_GRAYSCALE)
            if m is None or bx1 - bx0 < 8 or by1 - by0 < 8:
                continue
            m = cv2.resize(m, (bx1 - bx0, by1 - by0), interpolation=cv2.INTER_LINEAR)
            full = np.zeros((H, W), np.uint8)
            full[by0:by1, bx0:bx1] = np.where(m > 127, 255, 0).astype(np.uint8)
            found.append(((bx0, by0, bx1, by1), full, str(r.get("label", "")).lower()))
        except Exception:  # noqa: BLE001
            continue
    used = set()
    for i, (name, box) in enumerate(subjects):
        best, bj = 0.0, None
        for j, (b, full, label) in enumerate(found):
            if j in used:
                continue
            score = 0.0
            if box is not None:
                iw, ih = min(b[2], box[2]) - max(b[0], box[0]), min(b[3], box[3]) - max(b[1], box[1])
                if iw > 0 and ih > 0:
                    score = iw * ih / ((b[2] - b[0]) * (b[3] - b[1]) + (box[2] - box[0]) * (box[3] - box[1]) - iw * ih)
            elif name.lower() in label or label in name.lower():
                score = 0.5
            if score > best:
                best, bj = score, j
        if bj is not None and best > 0.3:
            used.add(bj)
            out[i] = found[bj][1]
    if all(m is None for m in out) and len(found) == 1 and len(subjects) == 1:
        out[0] = found[0][1]
    return out


def model_alpha(img):
    """The fine matte of a trained model (rembg), or None when it cannot be installed here."""
    try:
        try:
            from rembg import new_session, remove  # type: ignore
        except ImportError:
            subprocess.run(["pip", "install", "-q", "--break-system-packages", "rembg", "onnxruntime"], check=True, timeout=900)
            from rembg import new_session, remove  # type: ignore
        from PIL import Image
        if "s" not in _SESSION:
            for name in ("isnet-general-use", "u2net"):
                try:
                    _SESSION["s"] = new_session(name)
                    break
                except Exception:  # noqa: BLE001
                    continue
        if "s" not in _SESSION:
            return None
        h, w = img.shape[:2]
        s = min(1.0, 1600.0 / max(h, w))
        sm = cv2.resize(img, (int(w * s), int(h * s)), interpolation=cv2.INTER_AREA) if s < 1 else img
        m = remove(Image.fromarray(cv2.cvtColor(sm, cv2.COLOR_BGR2RGB)), session=_SESSION["s"], only_mask=True)
        a = np.array(m.convert("L"))
        return cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR) if s < 1 else a
    except Exception as e:  # noqa: BLE001
        print("::warning::background-removal model not available:", str(e)[:120])
        return None


def grabcut(img, box=None):
    h, w = img.shape[:2]
    s = min(1.0, 400.0 / max(h, w))
    sm = cv2.resize(img, (max(8, int(w * s)), max(8, int(h * s))), interpolation=cv2.INTER_AREA)
    sh, sw = sm.shape[:2]
    if box is None:
        rect = (int(sw * 0.04), int(sh * 0.04), int(sw * 0.92), int(sh * 0.92))
    else:
        rect = (int(box[0] * s), int(box[1] * s), max(4, int((box[2] - box[0]) * s)), max(4, int((box[3] - box[1]) * s)))
    m = np.zeros((sh, sw), np.uint8)
    try:
        cv2.grabCut(sm, m, rect, np.zeros((1, 65)), np.zeros((1, 65)), 5, cv2.GC_INIT_WITH_RECT)
    except Exception:  # noqa: BLE001
        return None
    a = np.where((m == 1) | (m == 3), 255, 0).astype(np.uint8)
    return cv2.resize(a, (w, h), interpolation=cv2.INTER_LINEAR)


# ---------------------------------------------------------------- finishing
def _frac(a):
    return float((a > 127).mean())


def finish(img, alpha, min_piece=0.04):
    """Holes filled, specks removed, soft 1 px edge, background colour pushed out of the edge pixels. Returns RGBA uint8."""
    h, w = img.shape[:2]
    a = (alpha > 127).astype(np.uint8)
    n, lab, st, _ = cv2.connectedComponentsWithStats(a)
    if n > 2:
        big = st[1:, 4].max()
        keep = np.zeros_like(a)
        for k in range(1, n):
            if st[k, 4] >= min_piece * big:
                keep[lab == k] = 1
        a = keep
    inv = (1 - a).astype(np.uint8)                                 # holes: background that does not touch the border
    n2, lab2 = cv2.connectedComponents(inv)
    border = set(np.unique(np.concatenate([lab2[0], lab2[-1], lab2[:, 0], lab2[:, -1]])))
    for k in range(1, n2):
        if k not in border:
            a[lab2 == k] = 1
    soft = cv2.GaussianBlur(cv2.erode(a, np.ones((3, 3), np.uint8)).astype(np.float32), (0, 0), 1.0)
    # colour decontamination: in the edge band the colour comes from the inside of the subject
    inner = cv2.erode(a, np.ones((5, 5), np.uint8))
    band = ((soft > 0.02) & (inner == 0)).astype(np.uint8)
    rgb = img.copy()
    if band.any() and inner.any():                                # normalised blur of the subject's own inside colours, pushed into the edge band
        wgt = inner.astype(np.float32)
        num = cv2.GaussianBlur(img.astype(np.float32) * wgt[..., None], (0, 0), 3.0)
        den = cv2.GaussianBlur(wgt, (0, 0), 3.0)
        fill = num / np.maximum(den, 1e-3)[..., None]
        use = (cv2.dilate(band, np.ones((5, 5), np.uint8)) > 0) & (den > 0.02)
        rgb = np.where(use[..., None], fill, img.astype(np.float32)).clip(0, 255).astype(np.uint8)
    return np.dstack([rgb, np.clip(soft * 255, 0, 255).astype(np.uint8)])


# ---------------------------------------------------------------- the department
def remove(img, subject=None, box=None, use_gemini=True, allow_basic=True):
    """img: BGR uint8. subject: what to keep ('the man in the jacket', 'the bottle'); box: its box in pixels (x0,y0,x1,y1) if known.
    Returns (RGBA uint8, report dict with the method)."""
    H, W = img.shape[:2]
    rep = {"method": None}
    if box is None and subject is None:
        a = plain(img)
        if a is not None and 0.03 < _frac(a) < 0.92:
            rep["method"] = "plain background"
            return finish(img, a), rep
    gm = None
    if use_gemini:
        try:
            import gemini
            if gemini.available():
                gm = gemini_masks(img, [(subject or "the main subject", box)])[0]
        except Exception:  # noqa: BLE001
            gm = None
    if gm is not None and not (0.01 < _frac(gm) < 0.95):
        gm = None
    mm = model_alpha(img)
    if mm is not None and gm is not None:
        keepzone = cv2.dilate(gm, np.ones((15, 15), np.uint8))
        inter = ((mm > 127) & (gm > 127)).sum() / max(1.0, ((mm > 127) | (gm > 127)).sum())
        if inter > 0.55:                                           # the model and Gemini agree: the fine edge of the model, inside the area Gemini chose
            a = np.where(keepzone > 0, mm, 0).astype(np.uint8)
            rep["method"] = "Gemini + model"
            return finish(img, a), rep
        rep["method"] = "Gemini"
        return finish(img, gm), rep
    if gm is not None:
        rep["method"] = "Gemini"
        return finish(img, gm), rep
    if mm is not None:
        if box is not None:                                        # only the named subject, when its box is known
            zone = np.zeros((H, W), np.uint8)
            px, py = int((box[2] - box[0]) * 0.08), int((box[3] - box[1]) * 0.08)
            zone[max(0, int(box[1]) - py):int(box[3]) + py, max(0, int(box[0]) - px):int(box[2]) + px] = 255
            mm = np.minimum(mm, zone)
        if 0.01 < _frac(mm) < 0.97:
            rep["method"] = "model"
            return finish(img, mm), rep
    ga = grabcut(img, box) if allow_basic else None
    if ga is not None and 0.02 < _frac(ga) < 0.97:
        rep["method"] = "GrabCut (basic)"
        return finish(img, ga), rep
    rep["method"] = None
    return None, rep


def subject_masks(img, items):
    """For a list of {id, label, box(px)}: {id: full-size uint8 mask} using the department (people of a flyer, products of a design)."""
    out = {}
    H, W = img.shape[:2]
    gem = None
    try:
        import gemini
        if gemini.available():
            gem = gemini_masks(img, [(it["label"], tuple(it["box"])) for it in items])
    except Exception:  # noqa: BLE001
        gem = None
    mm = None
    for i, it in enumerate(items):
        x0, y0, x1, y1 = [int(v) for v in it["box"]]
        m = gem[i] if gem and gem[i] is not None and 0.002 < _frac(gem[i]) < 0.9 else None
        px, py = int((x1 - x0) * 0.1) + 4, int((y1 - y0) * 0.1) + 4
        cx0, cy0, cx1, cy1 = max(0, x0 - px), max(0, y0 - py), min(W, x1 + px), min(H, y1 + py)
        crop = img[cy0:cy1, cx0:cx1]
        fine = model_alpha(crop) if (m is not None or True) else None            # the model on the crop around this one subject
        if fine is not None:
            full = np.zeros((H, W), np.uint8)
            full[cy0:cy1, cx0:cx1] = fine
            if m is not None:
                zone = cv2.dilate(m, np.ones((15, 15), np.uint8))
                inter = ((full > 127) & (m > 127)).sum() / max(1.0, ((full > 127) | (m > 127)).sum())
                full = np.where(zone > 0, full, 0).astype(np.uint8) if inter > 0.55 else m
            if 0.002 < _frac(full) < 0.9:
                out[it["id"]] = (full > 127).astype(np.uint8)
                continue
        if m is not None:
            out[it["id"]] = (m > 127).astype(np.uint8)
    return out


def remove_file(path, out_path=None, subject=None, allow_basic=True):
    """File in, transparent PNG out (cropped to the subject). Returns the new path or None."""
    img = cv2.imread(path, cv2.IMREAD_COLOR)
    if img is None:
        return None
    rgba, rep = remove(img, subject=subject, allow_basic=allow_basic)
    if rgba is None:
        return None
    ys, xs = np.nonzero(rgba[..., 3] > 24)
    if not len(xs):
        return None
    pad = int(max(img.shape[:2]) * 0.01)
    H, W = img.shape[:2]
    rgba = rgba[max(0, ys.min() - pad):min(H, ys.max() + pad), max(0, xs.min() - pad):min(W, xs.max() + pad)]
    out = out_path or (os.path.splitext(path)[0] + "_cut.png")
    cv2.imwrite(out, rgba)
    print(f"background removed ({rep['method']}): {os.path.basename(out)}")
    return out

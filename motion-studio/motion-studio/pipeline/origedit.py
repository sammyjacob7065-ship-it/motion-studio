"""Edit-the-original: the client's own video stays (pictures, motion, music), only the texts he named are swapped.
For every text to swap (OLD -> NEW) the studio
  1. reads the video with OCR (RapidOCR when installed, Tesseract otherwise) on a sample of frames and finds where the OLD text is, frame by frame
     (a text that appears letter by letter is still found: a fragment of the old text counts);
  2. for every frame where the old text is visible: measures the text colour and its pixels, paints the old text away (inpainting from the surrounding background),
     and writes the NEW text in the same place, size, colour and weight, with the same visibility (fade in, fade out, left-to-right reveal, scale);
  3. keeps the video, the animation and the sound exactly as they were.
An item with NEW = '' or REMOVED only erases the old text (a watermark, a phone number).
Honest limits: text that is 3D, heavily glowing, over busy footage or a very decorative font is found less reliably and painted over less cleanly; the report says which items were not found."""
import difflib
import glob
import os
import re
import shutil
import subprocess
import tempfile

import cv2
import numpy as np
from PIL import Image, ImageDraw, ImageFont

LOG = []

_CONF = str.maketrans({"0": "O", "1": "I", "5": "S", "8": "B", "|": "I", "L": "I"})


def norm(s):
    return re.sub(r"[^A-Z0-9]", "", str(s).upper()).translate(_CONF)


# ---------------------------------------------------------------- what to swap
SKIP_ROLES = re.compile(r"voice|narrat|picture|photo|image|footage|product|logo|colou?r|music|sound|background", re.I)


def items_from(agreed):
    """[{old, new, remove}] from the agreed swaps and copy plan: only on-screen TEXT (pictures, logos, colours, voice are not texts)."""
    out, seen = [], set()
    rows = [dict(r, _swap=True) for r in (agreed.get("swaps") or []) if isinstance(r, dict)] + [r for r in (agreed.get("copy_plan") or []) if isinstance(r, dict)]
    for r in rows:
        if not r.get("_swap") and SKIP_ROLES.search(str(r.get("role", ""))):
            continue
        old, new = str(r.get("old") or "").strip(), str(r.get("new") if r.get("new") is not None else "").strip()
        if len(norm(old)) < 2:
            continue
        k = norm(old)
        if k in seen:
            continue
        seen.add(k)
        remove = (new == "" or new.upper() in ("REMOVED", "REMOVE", "DELETE", "NONE", "NOTHING"))
        out.append({"old": old, "new": "" if remove else new, "remove": remove, "key": k})
    return out


def colors_from(agreed):
    """[(from_hex, to_hex)] brand colour swaps."""
    c = agreed.get("colors") if isinstance(agreed.get("colors"), dict) else {}
    a = [x for x in (c.get("from") or []) if re.match(r"^#?[0-9a-fA-F]{6}$", str(x))]
    b = [x for x in (c.get("to") or []) if re.match(r"^#?[0-9a-fA-F]{6}$", str(x))]
    return [("#" + str(x).lstrip("#"), "#" + str(y).lstrip("#")) for x, y in zip(a, b)]


def _hsv(hexc):
    h = hexc.lstrip("#")
    bgr = np.float32([[[int(h[4:6], 16) / 255.0, int(h[2:4], 16) / 255.0, int(h[0:2], 16) / 255.0]]])
    return cv2.cvtColor(bgr, cv2.COLOR_BGR2HSV)[0, 0].astype(np.float32)            # H in degrees 0..360, S and V 0..1


def recolor(fr, pairs):
    """Moves the pixels of each original brand colour to the new brand colour (hue, saturation, brightness). Done in float so gradients stay smooth:
    the effect fades out with the distance (in hue) from the original colour, so no hard bands appear."""
    hsv = cv2.cvtColor(fr.astype(np.float32) / 255.0, cv2.COLOR_BGR2HSV)
    h, s, v = hsv[..., 0], hsv[..., 1], hsv[..., 2]
    for a, b in pairs:
        ha, hb = _hsv(a), _hsv(b)
        if ha[1] < 0.18:                                        # a white / grey / black brand colour has no hue to follow: skipped
            continue
        dh = (h - ha[0] + 180) % 360 - 180
        w = 0.5 * (1 + np.cos(np.pi * np.clip(np.abs(dh) / 45.0, 0, 1)))
        w = w * np.clip((s - 0.25 * ha[1]) / (0.25 * ha[1] + 1e-3), 0, 1) * np.clip((v - 0.06) / 0.12, 0, 1)
        h = (h + w * (((hb[0] - ha[0] + 180) % 360) - 180)) % 360
        s = np.clip(s * (1 + w * (hb[1] / max(ha[1], 0.05) - 1)), 0, 1)
        v = np.clip(v * (1 + w * 0.8 * (hb[2] / max(ha[2], 0.05) - 1)), 0, 1)
    out = cv2.cvtColor(np.stack([h, s, v], axis=-1).astype(np.float32), cv2.COLOR_HSV2BGR)
    return np.clip(out * 255.0 + 0.5, 0, 255).astype(np.uint8)


# ---------------------------------------------------------------- video io
def probe(path):
    r = subprocess.run(["ffprobe", "-v", "error", "-select_streams", "v:0", "-show_entries", "stream=avg_frame_rate,r_frame_rate:format=duration", "-of", "default=nw=1", path], capture_output=True, text=True)
    fps = 30.0
    for ln in r.stdout.splitlines():
        if ln.startswith("avg_frame_rate=") or ln.startswith("r_frame_rate="):
            a, _, b = ln.split("=")[1].partition("/")
            try:
                v = float(a) / float(b or 1)
                if 5 < v < 121:
                    fps = v
                    if ln.startswith("avg_frame_rate="):
                        break
            except (ValueError, ZeroDivisionError):
                pass
    tmp = tempfile.mkdtemp()
    png = os.path.join(tmp, "f.png")
    subprocess.run(["ffmpeg", "-y", "-v", "error", "-i", path, "-frames:v", "1", png], check=True)
    im = cv2.imread(png)
    shutil.rmtree(tmp, ignore_errors=True)
    H, W = im.shape[:2]
    return fps, W - W % 2, H - H % 2


def read_frames(path, fps, W, H):
    p = subprocess.Popen(["ffmpeg", "-v", "error", "-i", path, "-r", f"{fps:.3f}", "-vf", f"scale={W}:{H}", "-f", "rawvideo", "-pix_fmt", "bgr24", "-"], stdout=subprocess.PIPE, stderr=subprocess.DEVNULL)
    n = W * H * 3
    try:
        while True:
            buf = p.stdout.read(n)
            if len(buf) < n:
                break
            yield np.frombuffer(buf, np.uint8).reshape(H, W, 3).copy()
    finally:
        try:
            p.stdout.close()
        except Exception:  # noqa: BLE001
            pass
        p.wait()


class Writer:
    def __init__(self, src, out, fps, W, H):
        self.p = subprocess.Popen(["ffmpeg", "-y", "-v", "error", "-f", "rawvideo", "-pix_fmt", "bgr24", "-s", f"{W}x{H}", "-r", f"{fps:.3f}", "-i", "-", "-i", src,
                                   "-map", "0:v", "-map", "1:a:0?", "-c:v", "libx264", "-preset", "medium", "-crf", "16", "-pix_fmt", "yuv420p", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out], stdin=subprocess.PIPE)

    def write(self, fr):
        self.p.stdin.write(np.ascontiguousarray(fr).tobytes())

    def close(self):
        self.p.stdin.close()
        if self.p.wait() != 0:
            raise RuntimeError("ffmpeg could not write the video")


# ---------------------------------------------------------------- OCR
class OCR:
    """Returns line boxes: [(x0, y0, x1, y1, text)] for a BGR frame."""

    def __init__(self):
        self.rapid = None
        if os.environ.get("OCR_ENGINE", "auto") in ("auto", "rapidocr"):
            try:
                from rapidocr_onnxruntime import RapidOCR  # type: ignore
                self.rapid = RapidOCR()
            except Exception:  # noqa: BLE001
                self.rapid = None
        self.tess = bool(shutil.which("tesseract"))
        if not self.rapid and not self.tess:
            raise RuntimeError("no OCR engine (install tesseract-ocr or rapidocr-onnxruntime)")
        self.name = "rapidocr" if self.rapid else "tesseract"

    def lines(self, img):
        out = []
        if self.rapid is not None:
            try:
                res, _ = self.rapid(img)
                for box, text, conf in (res or []):
                    xs, ys = [p[0] for p in box], [p[1] for p in box]
                    out.append((int(min(xs)), int(min(ys)), int(max(xs)), int(max(ys)), str(text)))
                return out
            except Exception as e:  # noqa: BLE001
                LOG.append("rapidocr failed: " + str(e)[:80])
        if self.tess:
            for inv in (False, True):
                out += self._tess(img, inv)
        return out

    @staticmethod
    def _tess(img, inv):
        g = cv2.cvtColor(img, cv2.COLOR_BGR2GRAY)
        if inv:
            g = 255 - g
        tmp = tempfile.mkdtemp()
        f = os.path.join(tmp, "f.png")
        cv2.imwrite(f, g)
        r = subprocess.run(["tesseract", f, "stdout", "--psm", "11", "-l", "eng", "tsv"], capture_output=True, text=True, timeout=120)
        shutil.rmtree(tmp, ignore_errors=True)
        groups = {}
        for ln in r.stdout.splitlines()[1:]:
            c = ln.split("\t")
            if len(c) < 12 or c[0] != "5" or not c[11].strip():
                continue
            try:
                conf = float(c[10])
            except ValueError:
                continue
            if conf < 25:
                continue
            x, y, w, h = int(c[6]), int(c[7]), int(c[8]), int(c[9])
            groups.setdefault((c[2], c[3], c[4]), []).append((x, y, x + w, y + h, c[11]))
        out = []
        for ws in groups.values():
            ws.sort()
            out.append((min(w[0] for w in ws), min(w[1] for w in ws), max(w[2] for w in ws), max(w[3] for w in ws), " ".join(w[4] for w in ws)))
        return out


def _score(det, old):
    """How much of this detected text is a piece of the old text (a letter-by-letter reveal shows only a prefix)."""
    d, o = norm(det), old
    if len(d) < 2:
        return 0.0
    m = difflib.SequenceMatcher(None, o, d, autojunk=False).find_longest_match(0, len(o), 0, len(d))
    if m.size < 2:
        return 0.0
    return m.size / min(len(d), len(o)) if m.size >= min(len(d), len(o)) * 0.6 else 0.0


# ---------------------------------------------------------------- tracking
def find_items(path, items, fps, W, H, ocr, step_s=0.2, max_ocr=170, progress=None):
    """Returns {item index: {frame: (x0,y0,x1,y1, n_lines)}} on the OCR sample frames."""
    total = int(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", path], capture_output=True, text=True).stdout.strip() or 0) * fps)
    step = max(1, int(round(fps * step_s)))
    while total / step > max_ocr:
        step += 1
    hits = {i: {} for i in range(len(items))}
    for fi, fr in enumerate(read_frames(path, fps, W, H)):
        if fi % step:
            continue
        if progress and (fi // step) % 20 == 0:
            progress(fi, total)
        dets = ocr.lines(fr)
        per = {}
        for (x0, y0, x1, y1, t) in dets:
            if (y1 - y0) < 8:
                continue
            best, bi = 0.0, None
            for i, it in enumerate(items):
                s = _score(t, it["key"])
                if s > best + 1e-9 or (abs(s - best) < 1e-9 and bi is not None and len(it["key"]) > len(items[bi]["key"])):
                    best, bi = s, i
            if bi is not None and best >= 0.8:
                per.setdefault(bi, []).append((x0, y0, x1, y1))
        for i, bxs in per.items():
            bxs = _merge_lines(bxs)
            x0, y0 = min(b[0] for b in bxs), min(b[1] for b in bxs)
            x1, y1 = max(b[2] for b in bxs), max(b[3] for b in bxs)
            hits[i][fi] = (x0, y0, x1, y1, len(bxs))
    return hits, step


def _merge_lines(bxs):
    """Boxes of the same line (two OCR passes, words) become one; different lines stay apart."""
    bxs = sorted(bxs, key=lambda b: (b[1], b[0]))
    out = []
    for b in bxs:
        for k, o in enumerate(out):
            ov = min(o[3], b[3]) - max(o[1], b[1])
            if ov > 0.5 * min(o[3] - o[1], b[3] - b[1]):
                out[k] = (min(o[0], b[0]), min(o[1], b[1]), max(o[2], b[2]), max(o[3], b[3]))
                break
        else:
            out.append(b)
    return out


def track(hit, step, nframes):
    """Boxes for every frame between the first and the last detection (interpolated; a gap longer than 0.8 s stays empty)."""
    fr = sorted(hit)
    if not fr:
        return {}
    out = {}
    for a, b in zip(fr, fr[1:]):
        out[a] = hit[a][:4]
        if b - a <= max(step * 4, 24):
            for f in range(a + 1, b):
                t = (f - a) / (b - a)
                out[f] = tuple(int(round(hit[a][k] * (1 - t) + hit[b][k] * t)) for k in range(4))
    out[fr[-1]] = hit[fr[-1]][:4]
    lo, hi = fr[0], fr[-1]
    for f in range(max(0, lo - step), lo):
        out.setdefault(f, hit[lo][:4])
    for f in range(hi + 1, min(nframes, hi + step + 1)):
        out.setdefault(f, hit[hi][:4])
    return out


# ---------------------------------------------------------------- painting
def _pad(box, W, H):
    x0, y0, x1, y1 = box
    h = y1 - y0
    px, py = int(h * 0.35) + 4, int(h * 0.3) + 4
    return max(0, x0 - px), max(0, y0 - py), min(W, x1 + px), min(H, y1 + py)


def _bg_and_text(roi, inner):
    """Background colour (median of the band around the text) and text colour (the pixels farthest from it)."""
    m = np.ones(roi.shape[:2], bool)
    ix0, iy0, ix1, iy1 = inner
    m[iy0:iy1, ix0:ix1] = False
    ring = roi[m] if m.sum() > 50 else roi.reshape(-1, 3)
    bg = np.median(ring, axis=0)
    box = roi[iy0:iy1, ix0:ix1].reshape(-1, 3).astype(np.float32)
    d = np.linalg.norm(box - bg, axis=1)
    if len(d) == 0:
        return bg, np.array([255, 255, 255], float), 0
    thr = np.percentile(d, 85)
    far = box[d >= max(thr, 40)]
    if len(far) < 8:
        return bg, (np.array([255, 255, 255], float) if bg.mean() < 128 else np.array([20, 20, 20], float)), float(d.max())
    return bg, np.median(far, axis=0), float(d.max())


def _mask(roi, bg, tc, grow=2):
    """(mask of the old text pixels, opacity of the text 0..1). A pixel is text when it lies on the line from the background colour to the text colour
    (so a text that fades in or out is still found); the opacity is how far along that line the strong pixels are."""
    f = roi.astype(np.float32) - bg.astype(np.float32)
    u = (tc - bg).astype(np.float32)
    s2 = float(u @ u)
    if s2 < 100:
        return np.zeros(roi.shape[:2], np.uint8), 0.0
    t = (f @ u) / s2
    perp = np.linalg.norm(f - t[..., None] * u, axis=2)
    m = ((t > 0.22) & (perp < max(28.0, 0.45 * np.sqrt(s2)))).astype(np.uint8)
    op = float(np.clip(np.percentile(t[m > 0], 85), 0, 1)) if m.sum() >= 8 else 0.0
    if grow:
        m = cv2.dilate(m, np.ones((3, 3), np.uint8), iterations=grow)
    return m, op


FONT_DIRS = ["/usr/share/fonts", "/usr/local/share/fonts", os.path.expanduser("~/.fonts")]
HEAVY = ["Anton-Regular", "BebasNeue-Regular", "Poppins-Bold", "Montserrat-Bold", "Inter-Bold", "LiberationSans-Bold", "DejaVuSans-Bold"]
NORMAL = ["Poppins-SemiBold", "Montserrat-SemiBold", "Poppins-Medium", "Inter-SemiBold", "LiberationSans-Bold", "DejaVuSans-Bold"]
LIGHT = ["Poppins-Light", "Montserrat-Light", "Inter-Light", "LiberationSans-Regular", "DejaVuSans"]
CONDENSED = ["Anton-Regular", "BebasNeue-Regular", "LiberationSansNarrow-Bold", "Poppins-Bold"]


def font_file(names):
    for n in names:
        for d in FONT_DIRS + [os.environ.get("FONT_CACHE", "/tmp/fonts")]:
            hit = glob.glob(os.path.join(d, "**", n + ".ttf"), recursive=True) + glob.glob(os.path.join(d, "**", n + ".otf"), recursive=True)
            if hit:
                return hit[0]
    return None


_FONTS_TRIED = {"done": False}


def fetch_fonts():
    """Best effort: a few Google fonts for a closer match (the studio's runner can reach GitHub). Tried once; a failure stops it at once."""
    if _FONTS_TRIED["done"]:
        return
    _FONTS_TRIED["done"] = True
    cache = os.environ.get("FONT_CACHE", "/tmp/fonts")
    os.makedirs(cache, exist_ok=True)
    base = "https://raw.githubusercontent.com/google/fonts/main/ofl/"
    for rel in ("anton/Anton-Regular.ttf", "bebasneue/BebasNeue-Regular.ttf", "poppins/Poppins-Bold.ttf", "poppins/Poppins-SemiBold.ttf", "poppins/Poppins-Light.ttf"):
        dest = os.path.join(cache, os.path.basename(rel))
        if os.path.exists(dest):
            continue
        try:
            import requests
            r = requests.get(base + rel, timeout=10)
            if r.status_code == 200 and len(r.content) > 5000:
                open(dest, "wb").write(r.content)
        except Exception:  # noqa: BLE001
            return                                           # no network: the fonts on the machine are used


def pick_font(density, aspect, caps):
    if aspect < 0.42 and caps:
        names = CONDENSED
    elif density > 0.30:
        names = HEAVY
    elif density < 0.16:
        names = LIGHT
    else:
        names = NORMAL
    return font_file(names) or font_file(HEAVY + NORMAL + LIGHT)


def layout_lines(text, n):
    if n <= 1:
        return [text]
    parts = [p.strip() for p in re.split(r"\s*\|\s*|\n", text) if p.strip()]
    if len(parts) >= n:
        return parts[:n - 1] + [" ".join(parts[n - 1:])]
    words = text.split()
    if len(words) < n:
        return [text]
    size = len(words) / n
    return [" ".join(words[int(round(i * size)):int(round((i + 1) * size))]) for i in range(n)]


def render_text(text, color, box_w, box_h, nlines, font_path, align="center", max_w=None):
    """RGBA picture of the new text fitted into box_w x box_h (never larger than the box height, shrunk to fit the width)."""
    lines = layout_lines(text, nlines)
    size = max(10, int(box_h / max(1, len(lines)) / 0.68))
    while size > 10:
        f = ImageFont.truetype(font_path, size)
        ws = [f.getbbox(l)[2] - f.getbbox(l)[0] for l in lines]
        cap = f.getbbox("H")[3] - f.getbbox("H")[1]                    # the old box is measured on capital letters: compare cap heights
        if max(ws) <= min(box_w * 1.3, max_w or 1e9) and cap * len(lines) * 1.25 <= box_h * 1.08 + 4:
            break
        size -= 2
    f = ImageFont.truetype(font_path, size)
    asc, desc = f.getmetrics()
    lh = int((asc + desc) * 1.02)
    W = max(int(box_w), max(f.getbbox(l)[2] for l in lines)) + 8
    Hh = max(int(box_h), lh * len(lines)) + 8
    im = Image.new("RGBA", (W, Hh), (0, 0, 0, 0))
    d = ImageDraw.Draw(im)
    y = (Hh - lh * len(lines)) // 2
    for l in lines:
        w = f.getbbox(l)[2] - f.getbbox(l)[0]
        x = (W - w) // 2 if align == "center" else (0 if align == "left" else W - w)
        d.text((x - f.getbbox(l)[0], y), l, font=f, fill=tuple(int(round(c)) for c in color[::-1]) + (255,))
        y += lh
    return im


# ---------------------------------------------------------------- the job
def prepare_objects(src, fps, W, H, nframes, objects):
    """Finds every logo / product to swap on its sample frames and follows it. Returns [(object dict, Swap)]."""
    import objswap
    plans, want = [], {}
    for ob in objects:
        e = ob["element"]
        i0, i1 = int(e["t0"] * fps), min(nframes - 1, int(e["t1"] * fps))
        step = max(1, int(round(objswap.SAMPLE_S * fps)))
        while (i1 - i0) / step > 40:
            step += 1
        idxs = list(range(i0, i1 + 1, step)) or [i0]
        plans.append((ob, idxs))
        for i in idxs:
            want[i] = None
    if not want:
        return []
    last = max(want)
    for fi, fr in enumerate(read_frames(src, fps, W, H)):
        if fi in want:
            k = min(1.0, 640.0 / max(W, H))
            small = cv2.resize(fr, (int(W * k), int(H * k)), interpolation=cv2.INTER_AREA) if k < 1 else fr
            want[fi] = cv2.imencode('.jpg', small, [cv2.IMWRITE_JPEG_QUALITY, 85])[1].tobytes()
        if fi >= last:
            break
    out = []
    for ob, idxs in plans:
        e = ob["element"]
        norm_boxes = objswap.detect([want[i] for i in idxs], e["desc"], e["kind"])
        px = [None if b is None else (b[0] * W, b[1] * H, b[2] * W, b[3] * H) for b in norm_boxes]
        out.append((ob, objswap.Swap(e, objswap.interpolate(px, idxs, nframes), ob["assets"], W, H)))
    return out


def edit(src, out, items, progress=None, colors=None, objects=None):
    """Swaps the texts in `src` and writes `out`. Returns a report {item index: {'found': frames, 'old', 'new'}}."""
    fps, W, H = probe(src)
    ocr = OCR()
    fetch_fonts()
    hits, step = find_items(src, items, fps, W, H, ocr, progress=progress)
    nframes = int(float(subprocess.run(["ffprobe", "-v", "error", "-show_entries", "format=duration", "-of", "default=nw=1:nk=1", src], capture_output=True, text=True).stdout.strip() or 0) * fps) + 2
    tracks = {i: track(h, step, nframes) for i, h in hits.items() if h}
    report = {i: {"old": items[i]["old"], "new": items[i]["new"], "frames": len(tracks.get(i, {})), "found": bool(hits.get(i))} for i in range(len(items))}
    swaps = prepare_objects(src, fps, W, H, nframes, objects) if objects else []
    objrep = [{"desc": ob["element"]["desc"], "kind": ob["element"]["kind"], "scene": ob["element"].get("scene"), "frames": len(sw.boxes), "found": bool(sw.boxes)} for ob, sw in swaps]
    if not tracks and not colors and not any(r["found"] for r in objrep):
        return report, ocr.name, objrep
    # first sweep over the frames that have the text: text colour, pixel density and the full box of each item
    info = {}
    for fi, fr in enumerate(read_frames(src, fps, W, H)):
        for i, tr in tracks.items():
            if fi not in tr:
                continue
            x0, y0, x1, y1 = _pad(tr[fi], W, H)
            roi = fr[y0:y1, x0:x1]
            ib = (tr[fi][0] - x0, tr[fi][1] - y0, tr[fi][2] - x0, tr[fi][3] - y0)
            bg, tc, sep = _bg_and_text(roi, ib)
            d = info.setdefault(i, {"samples": []})
            area = max(1, (tr[fi][2] - tr[fi][0]) * (tr[fi][3] - tr[fi][1]))
            m, _op = _mask(roi, bg, tc, grow=0)
            d["samples"].append((fi, float(sep), tc, int(m.sum()) / area, area))
    for i, d in info.items():
        best = sorted(d["samples"], key=lambda s: -s[1])[:max(3, len(d["samples"]) // 5)]
        d["color"] = np.median(np.array([s[2] for s in best]), axis=0)
        d["density"] = float(np.percentile([s[3] for s in d["samples"]], 90))
        boxes = [tracks[i][s[0]] for s in d["samples"]]
        d["full"] = max(boxes, key=lambda b: (b[2] - b[0]) * (b[3] - b[1]))
        fh = d["full"][3] - d["full"][1]
        d["lines"] = max(hits[i][f][4] for f in hits[i])
        fw = d["full"][2] - d["full"][0]
        nch = max(3, len(items[i]["key"]))
        d["aspect"] = fw / max(1.0, d["lines"] * nch * fh / max(1, d["lines"]))
        d["caps"] = items[i]["old"] == items[i]["old"].upper()
        d["font"] = pick_font(d["density"], d["aspect"], d["caps"])
        if items[i]["new"] and d["font"]:
            txt = items[i]["new"].upper() if d["caps"] else items[i]["new"]
            d["canvas"] = render_text(txt, d["color"], d["full"][2] - d["full"][0], d["full"][3] - d["full"][1], d["lines"], d["font"], max_w=W * 0.9,
                                      align="center" if abs((d["full"][0] + d["full"][2]) / 2 - W / 2) < W * 0.08 else ("left" if d["full"][0] < W / 2 else "right"))
        dens = [s[3] for s in d["samples"]]
        d["dref"] = max(1e-4, float(np.percentile(dens, 90)))
    # second sweep: paint
    wr = Writer(src, out, fps, W, H)
    try:
        for fi, fr in enumerate(read_frames(src, fps, W, H)):
            for ob, sw in swaps:                                    # logos and products first, the texts on top
                if sw.active(fi):
                    fr = sw.apply(fr, fi)
            for i, tr in tracks.items():
                if fi not in tr or i not in info:
                    continue
                d = info[i]
                x0, y0, x1, y1 = _pad(tr[fi], W, H)
                roi = fr[y0:y1, x0:x1].copy()
                ib = (tr[fi][0] - x0, tr[fi][1] - y0, tr[fi][2] - x0, tr[fi][3] - y0)
                bg, _tc, _s = _bg_and_text(roi, ib)
                m, alpha = _mask(roi, bg, d["color"], grow=2)
                if alpha < 0.04:
                    continue
                clean = cv2.inpaint(roi, (m * 255).astype(np.uint8), 4, cv2.INPAINT_TELEA)
                roi = np.where(m[..., None] > 0, clean, roi)               # the old text is always painted away completely, whatever its opacity
                cv = d.get("canvas")
                if cv is not None:
                    fx0, fy0, fx1, fy1 = d["full"]
                    fw, fh = fx1 - fx0, fy1 - fy0
                    cx0, cy0, cx1, cy1 = tr[fi]
                    cw, ch = cx1 - cx0, cy1 - cy0
                    scale_anim = abs(ch / max(1, fh) - 1) > 0.18
                    big = cv
                    if scale_anim:
                        k = ch / max(1, fh)
                        big = cv.resize((max(2, int(cv.width * k)), max(2, int(cv.height * k))), Image.LANCZOS)
                        px = int(round((cx0 + cx1) / 2 - big.width / 2))
                        py = int(round((cy0 + cy1) / 2 - big.height / 2))
                        clip = None
                    else:
                        dx = int(round((cx0 + cx1) / 2 - (fx0 + fx1) / 2)) if cw >= 0.97 * fw else 0
                        dy = int(round((cy0 + cy1) / 2 - (fy0 + fy1) / 2))
                        px = int(round((fx0 + fx1) / 2 - big.width / 2)) + dx
                        py = int(round((fy0 + fy1) / 2 - big.height / 2)) + dy
                        clip = (cx0, cx1) if cw < 0.97 * fw else None
                    layer = Image.new("RGBA", (W, H), (0, 0, 0, 0))
                    layer.paste(big, (px, py), big)
                    la = np.array(layer.getchannel("A"), dtype=np.float32) / 255.0
                    if clip:
                        la[:, :max(0, clip[0])] = 0
                        la[:, min(W, clip[1] + 2):] = 0
                    # the new text may be wider than the old one: paint it on the frame, over the cleaned area
                    full_roi = fr.copy()
                    full_roi[y0:y1, x0:x1] = roi
                    rgb = np.array(layer.convert("RGB"), dtype=np.float32)[..., ::-1]
                    a = (la * alpha)[..., None]
                    fr = (full_roi * (1 - a) + rgb * a).astype(np.uint8)
                else:
                    fr[y0:y1, x0:x1] = roi
                    continue
            wr.write(recolor(fr, colors) if colors else fr)
    finally:
        wr.close()
    return report, ocr.name, objrep

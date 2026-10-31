"""Brings client files into a clean, predictable shape before rendering. Originals are never edited: work copies only."""
import base64
import colorsys
import json
import os
import re
import subprocess
import urllib.parse
from common import S, env
from PIL import Image, ImageOps

MAX_SIDE = 3000
IMG_EXT = {"jpg", "jpeg", "png", "webp", "gif", "bmp", "tif", "tiff", "heic", "svg"}
VID_EXT = {"mp4", "mov", "webm", "mkv", "avi", "m4v"}
AUD_EXT = {"mp3", "wav", "m4a", "ogg", "aac", "opus", "flac"}


def kind_of(name):
    e = name.rsplit(".", 1)[-1].lower() if "." in name else ""
    return "image" if e in IMG_EXT else "video" if e in VID_EXT else "audio" if e in AUD_EXT else "other"


def run(cmd, timeout=600):
    return subprocess.run(cmd, capture_output=True, text=True, timeout=timeout)


def probe(path):
    r = run(["ffprobe", "-v", "error", "-print_format", "json", "-show_streams", "-show_format", path], 60)
    try:
        return json.loads(r.stdout)
    except Exception:  # noqa: BLE001
        return {}


def duration_of(path):
    try:
        return float(probe(path).get("format", {}).get("duration", 0))
    except Exception:  # noqa: BLE001
        return 0.0


def dominant_colors(im, n=4):
    small = im.convert("RGB").resize((64, 64))
    q = small.quantize(colors=n, method=Image.Quantize.MEDIANCUT).convert("RGB")
    cols = sorted(q.getcolors(64 * 64), reverse=True)
    out = []
    for _c, rgb in cols[:n]:
        out.append("#%02x%02x%02x" % rgb)
    return out


def analyze_image(path, flags):
    im = Image.open(path)
    im = ImageOps.exif_transpose(im)
    has_alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
    w, h = im.size
    changed = False
    if max(w, h) > MAX_SIDE:
        s = MAX_SIDE / max(w, h)
        im = im.resize((int(w * s), int(h * s)), Image.LANCZOS)
        w, h = im.size
        changed = True
    if has_alpha and im.mode != "RGBA":
        im = im.convert("RGBA")
    if not has_alpha and im.mode != "RGB":
        im = im.convert("RGB")
    out = path
    if has_alpha:
        out = os.path.splitext(path)[0] + ".png"
        im.save(out, "PNG")
    else:
        if changed or path.lower().endswith((".webp", ".bmp", ".tif", ".tiff", ".gif")) or ImageOps.exif_transpose(Image.open(path)).size != Image.open(path).size:
            out = os.path.splitext(path)[0] + ".jpg"
            im.save(out, "JPEG", quality=94)
    if out != path and os.path.exists(path) and os.path.abspath(out) != os.path.abspath(path):
        os.remove(path)
    if min(w, h) < 500:
        flags.append("low resolution (%dx%d): it will look soft if shown large" % (w, h))
    return out, {"kind": "image", "width": w, "height": h, "alpha": bool(has_alpha), "colors": dominant_colors(im)}


def analyze_video(path, flags, workdir):
    """Re-encodes to a clean H.264 file (fixes phone rotation and HEVC) and extracts the sound as WAV."""
    info = probe(path)
    streams = info.get("streams", [])
    v = next((s for s in streams if s.get("codec_type") == "video"), None)
    if not v:
        flags.append("no video stream found")
        return path, {"kind": "video"}
    has_audio = any(s.get("codec_type") == "audio" for s in streams)
    base = os.path.splitext(path)[0]
    out = base + "_clean.mp4"
    r = run(["ffmpeg", "-y", "-i", path, "-vf", "scale='min(1920,iw)':'-2':force_original_aspect_ratio=decrease,scale=trunc(iw/2)*2:trunc(ih/2)*2,format=yuv420p", "-c:v", "libx264", "-preset", "veryfast", "-crf", "18", "-an", "-movflags", "+faststart", out], 1800)
    if r.returncode != 0 or not os.path.exists(out):
        flags.append("could not convert this video: " + r.stderr[-160:])
        return path, {"kind": "video"}
    audio = None
    if has_audio:
        audio = base + "_audio.wav"
        run(["ffmpeg", "-y", "-i", path, "-vn", "-ac", "2", "-ar", "48000", audio], 600)
        if not os.path.exists(audio):
            audio = None
    p2 = probe(out)
    v2 = next((s for s in p2.get("streams", []) if s.get("codec_type") == "video"), {})
    dur = float(p2.get("format", {}).get("duration", 0) or 0)
    if min(int(v2.get("width", 0)), int(v2.get("height", 0))) < 480:
        flags.append("low resolution video")
    return out, {"kind": "video", "width": int(v2.get("width", 0)), "height": int(v2.get("height", 0)), "duration": round(dur, 2), "audio": os.path.basename(audio) if audio else None}


def analyze(path, workdir):
    """Returns (final_path, info, flags)."""
    flags = []
    k = kind_of(path)
    try:
        if k == "image":
            if path.lower().endswith(".svg"):
                return path, {"kind": "image", "width": 1000, "height": 1000, "alpha": True, "colors": []}, ["svg is used as is"]
            out, info = analyze_image(path, flags)
        elif k == "video":
            out, info = analyze_video(path, flags, workdir)
        elif k == "audio":
            out, info = path, {"kind": "audio", "duration": round(duration_of(path), 2)}
        else:
            return path, {"kind": "other"}, ["file type not used"]
    except Exception as e:  # noqa: BLE001
        return path, {"kind": k}, [f"could not read this file: {str(e)[:120]}"]
    return out, info, flags


def direct_url(u):
    """Turns common share links into direct download links."""
    m = re.search(r"drive\.google\.com/file/d/([\w-]+)", u) or re.search(r"drive\.google\.com/open\?id=([\w-]+)", u)
    if m:
        return f"https://drive.google.com/uc?export=download&id={m.group(1)}"
    if "dropbox.com" in u:
        return re.sub(r"([?&])dl=0", r"\1dl=1", u) if "dl=" in u else u + ("&" if "?" in u else "?") + "dl=1"
    return u


def download_url(u, dest_dir, idx):
    """Downloads a media file from a link. Returns (path or None, note)."""
    try:
        r = S.get(direct_url(u), timeout=180, stream=True, allow_redirects=True, headers={"User-Agent": "Mozilla/5.0"})
        ct = r.headers.get("content-type", "").lower()
        if r.status_code != 200:
            return None, f"link gave {r.status_code}: {u[:60]}"
        if "text/html" in ct:
            return None, f"link is a web page, not a direct file: {u[:60]}"
        name = None
        cd = r.headers.get("content-disposition", "")
        m = re.search(r'filename\*?=(?:UTF-8\'\')?"?([^";]+)', cd)
        if m:
            name = urllib.parse.unquote(m.group(1))
        if not name:
            name = os.path.basename(urllib.parse.urlparse(u).path) or f"link{idx}"
        if kind_of(name) == "other":
            ext = {"image/jpeg": ".jpg", "image/png": ".png", "image/webp": ".webp", "video/mp4": ".mp4", "video/quicktime": ".mov", "audio/mpeg": ".mp3", "audio/wav": ".wav"}.get(ct.split(";")[0], "")
            if not ext:
                return None, f"not a picture, video or audio file: {u[:60]}"
            name += ext
        name = re.sub(r"[^A-Za-z0-9._-]+", "_", f"link{idx}_{name}")
        path = os.path.join(dest_dir, name)
        total = 0
        with open(path, "wb") as f:
            for chunk in r.iter_content(1 << 20):
                total += len(chunk)
                if total > 900 * 1024 * 1024:
                    return None, "file is too big (over 900 MB)"
                f.write(chunk)
        return path, ""
    except Exception as e:  # noqa: BLE001
        return None, f"could not download {u[:60]}: {str(e)[:80]}"


def fetch_stock(req, dest_dir, orientation):
    """Finds one licensed stock picture or video. req = {id, query, kind}. Returns (path or None, note)."""
    q, kind, rid = req.get("query", ""), req.get("kind", "image"), re.sub(r"[^A-Za-z0-9_-]", "", str(req.get("id", "stock")))
    pexels, pixabay = env("PEXELS_API_KEY"), env("PIXABAY_API_KEY")
    ori = {"9:16": "portrait", "16:9": "landscape", "1:1": "square", "4:5": "portrait"}.get(orientation, "portrait")
    try:
        if pexels:
            if kind == "video":
                r = S.get("https://api.pexels.com/videos/search", params={"query": q, "orientation": ori, "per_page": 12, "size": "medium"}, headers={"Authorization": pexels}, timeout=30)
                for v in r.json().get("videos", []):
                    files = [f for f in v.get("video_files", []) if f.get("file_type") == "video/mp4" and 720 <= int(f.get("width") or 0) <= 2200]
                    files.sort(key=lambda f: abs(int(f.get("width") or 0) - 1080))
                    if files:
                        return _save(files[0]["link"], dest_dir, f"{rid}.mp4"), ""
            else:
                r = S.get("https://api.pexels.com/v1/search", params={"query": q, "orientation": ori, "per_page": 15}, headers={"Authorization": pexels}, timeout=30)
                for p in r.json().get("photos", []):
                    if min(p.get("width", 0), p.get("height", 0)) >= 1000:
                        return _save(p["src"].get("large2x") or p["src"]["original"], dest_dir, f"{rid}.jpg"), ""
        if pixabay and kind != "video":
            po = {"portrait": "vertical", "landscape": "horizontal"}.get(ori, "all")
            r = S.get("https://pixabay.com/api/", params={"key": pixabay, "q": q, "image_type": "photo", "orientation": po, "per_page": 20, "safesearch": "true", "min_width": 1000}, timeout=30)
            for h in r.json().get("hits", []):
                if h.get("largeImageURL"):
                    return _save(h["largeImageURL"], dest_dir, f"{rid}.jpg"), ""
        if not pexels and not pixabay:
            return None, "no stock key set (PEXELS_API_KEY or PIXABAY_API_KEY)"
        return None, f"no good stock result for '{q}'"
    except Exception as e:  # noqa: BLE001
        return None, f"stock search failed: {str(e)[:100]}"


def _save(url, dest_dir, name):
    path = os.path.join(dest_dir, name)
    r = S.get(url, timeout=180, stream=True)
    r.raise_for_status()
    with open(path, "wb") as f:
        for chunk in r.iter_content(1 << 20):
            f.write(chunk)
    return path


def cutout(path):
    """Removes the background (optional, installs rembg on first use). Returns new PNG path or None."""
    try:
        try:
            from rembg import remove  # type: ignore
        except ImportError:
            subprocess.run(["pip", "install", "-q", "rembg", "onnxruntime"], check=True, timeout=900)
            from rembg import remove  # type: ignore
        out = os.path.splitext(path)[0] + "_cutout.png"
        with open(path, "rb") as f:
            data = remove(f.read())
        with open(out, "wb") as f:
            f.write(data)
        return out
    except Exception:  # noqa: BLE001
        return None


def describe_images(infos, paths, groq_chat):
    """Short description of each picture so the director knows what it is looking at (vision model, optional)."""
    from groq import parse_json
    model = env("VISION_MODEL", "meta-llama/llama-4-scout-17b-16e-instruct")
    ASK = ('Describe this picture for a video editor. Read any text printed on it (brand and product names). '
           'Reply JSON only: {"what":"one short sentence that includes the product name if it is a product, e.g. Immunosin herbal capsule box","product_name":"name printed on the product or empty","has_text":true/false,"is_logo":true/false,"has_person":true/false,"background":"transparent|plain|busy"}')
    try:
        import gemini
        use_gem = gemini.available()
    except Exception:  # noqa: BLE001
        gemini, use_gem = None, False
    for name, info in list(infos.items())[:16]:
        if info.get("kind") != "image" or name.endswith(".svg"):
            continue
        try:
            im = Image.open(paths[name]).convert("RGB")
            im.thumbnail((1024, 1024))
            import io
            buf = io.BytesIO()
            im.save(buf, "JPEG", quality=82)
            if use_gem:                                          # Gemini looks at the picture first (reads the product names well)
                try:
                    d = gemini.parse_json(gemini.generate(ASK, images=[(buf.getvalue(), "image/jpeg")], temperature=0.1, max_tokens=400, rounds=2))
                    if isinstance(d, dict) and d.get("what"):
                        if d.get("product_name") and str(d["product_name"]).lower() not in str(d["what"]).lower():
                            d["what"] = f"{d['what']} ({d['product_name']})"
                        info["describe"] = d
                        continue
                except Exception as e:  # noqa: BLE001
                    print("::warning::Gemini could not look at", name, str(e)[:80])
            b64 = base64.b64encode(buf.getvalue()).decode()
            msg = [{"role": "user", "content": [
                {"type": "text", "text": 'Describe this picture for a video editor. Reply JSON only: {"what":"one short sentence","has_text":true/false,"is_logo":true/false,"has_person":true/false,"background":"transparent|plain|busy"}'},
                {"type": "image_url", "image_url": {"url": "data:image/jpeg;base64," + b64}}]}]
            ans = groq_chat(msg, model=model, temperature=0.1, max_tokens=300, json_mode=False)
            info["describe"] = parse_json(ans)
        except Exception:  # noqa: BLE001
            continue


def cutout(path, out_path=None):
    """Makes a product picture float: when the picture sits on a plain, even background (a studio shot, a white or light backdrop), that background is
    removed (flood-filled from the edges, so white parts INSIDE the product stay) and the product is saved as a transparent PNG with soft edges.
    Returns the new path, or None when the background is not plain enough (the original is then used as it is)."""
    from PIL import ImageDraw, ImageFilter
    try:
        im0 = ImageOps.exif_transpose(Image.open(path))
        if im0.mode in ("RGBA", "LA") and im0.getchannel("A").getextrema()[0] < 250:
            return None                                       # already transparent
        im0 = im0.convert("RGB")
        W0, H0 = im0.size
        s = min(1.0, 900.0 / max(W0, H0))
        im = im0.resize((max(2, int(W0 * s)), max(2, int(H0 * s))), Image.LANCZOS) if s < 1 else im0.copy()
        w, h = im.size
        # is the border plain? sample 60 points around the edge
        pts = [(int(w * i / 20), 0) for i in range(20)] + [(int(w * i / 20), h - 1) for i in range(20)] + [(0, int(h * i / 20)) for i in range(20)] + [(w - 1, int(h * i / 20)) for i in range(20)]
        cols = [im.getpixel(p) for p in pts]
        med = tuple(sorted(c[k] for c in cols)[len(cols) // 2] for k in range(3))
        far = sum(1 for c in cols if max(abs(c[k] - med[k]) for k in range(3)) > 70)
        if far > len(cols) * 0.25:
            return None                                       # busy background: cannot be cut out this way
        mark = (255, 0, 255)
        work = im.copy()
        thresh = 46
        for p in pts[::3]:
            if work.getpixel(p) == mark:
                continue
            if max(abs(work.getpixel(p)[k] - med[k]) for k in range(3)) > 70:
                continue
            ImageDraw.floodfill(work, p, mark, thresh=thresh)
        mask = Image.new("L", (w, h), 255)                    # 255 = keep (product), 0 = background
        wp, mp = work.load(), mask.load()
        gone = 0
        for y in range(h):
            for x in range(w):
                if wp[x, y] == mark:
                    mp[x, y] = 0
                    gone += 1
        frac = gone / float(w * h)
        if frac < 0.08 or frac > 0.93:
            return None                                       # nothing removed, or the product itself was eaten
        mask = mask.filter(ImageFilter.MedianFilter(5)).filter(ImageFilter.MinFilter(3)).filter(ImageFilter.GaussianBlur(1.3))
        mask = mask.resize((W0, H0), Image.LANCZOS)
        rgba = im0.convert("RGBA")
        rgba.putalpha(mask)
        box = mask.point(lambda v: 255 if v > 24 else 0).getbbox()
        if box:
            pad = int(max(W0, H0) * 0.01)
            rgba = rgba.crop((max(0, box[0] - pad), max(0, box[1] - pad), min(W0, box[2] + pad), min(H0, box[3] + pad)))
        out = out_path or (os.path.splitext(path)[0] + "_cut.png")
        rgba.save(out, "PNG")
        return out
    except Exception as e:  # noqa: BLE001
        print("::warning::cut-out skipped:", str(e)[:120])
        return None

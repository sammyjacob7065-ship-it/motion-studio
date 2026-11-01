"""OPEN PICTURE search: real photos from Wikimedia Commons and Openverse (free, no key). Only pictures that are public domain, CC0 or CC BY are used
(a credit line is reported to the person). Used (1) when a scene says  USE PICTURE: search <words>  and (2) for a product piece of an animation
(PART / ANIMATION) when the brand site had no match: a real photo of the real thing, cut out by the studio. Every failure just means "use the AI picture"."""
import io
import json
import os
import re
import urllib.parse

from common import S, env
from PIL import Image, ImageOps

OPENVERSE = os.environ.get("OPENVERSE_URL", "https://api.openverse.org/v1/images/")
COMMONS = os.environ.get("COMMONS_URL", "https://commons.wikimedia.org/w/api.php")
UA = {"User-Agent": "MotionStudio/1.0 (ad video studio; contact via GitHub repo) python-requests"}
SEARCH_USE = re.compile(r"^\s*(?:search|web|find|wikimedia|commons|openverse)\b\s*[:\-]?\s*(.*)$", re.I)
OK_LICENSE = re.compile(r"^(?:cc0|cc[- ]?zero|public domain|pdm|pd\b|pd-|cc[- ]by(?![- ]?(?:sa|nc|nd))[- ]?\d)", re.I)


def search_words(use):
    """'search red sports car' -> 'red sports car'. Returns None when the text is not a search request."""
    m = SEARCH_USE.match(str(use or ""))
    return m.group(1).strip() if m else None


def _clean(s):
    return " ".join(re.sub(r"<[^>]+>", " ", str(s or "")).split())[:120]


def from_openverse(q, n=12):
    out = []
    try:
        r = S.get(OPENVERSE, params={"q": q, "license": "cc0,pdm,by", "page_size": n, "mature": "false", "category": "photograph"}, headers=UA, timeout=25)
        if r.status_code != 200:
            return out
        for x in r.json().get("results", []):
            if not x.get("url"):
                continue
            lic = str(x.get("license", "")).lower()
            out.append({"url": x["url"], "w": int(x.get("width") or 0), "h": int(x.get("height") or 0), "title": _clean(x.get("title")), "creator": _clean(x.get("creator")),
                        "license": ("CC " + lic.upper() + " " + str(x.get("license_version") or "")).strip() if lic not in ("cc0", "pdm") else lic.upper(),
                        "page": x.get("foreign_landing_url") or "", "source": "Openverse"})
    except Exception:  # noqa: BLE001
        pass
    return out


def from_commons(q, n=12):
    out = []
    try:
        r = S.get(COMMONS, params={"action": "query", "format": "json", "generator": "search", "gsrsearch": "filetype:bitmap " + q, "gsrnamespace": 6, "gsrlimit": n,
                                   "prop": "imageinfo", "iiprop": "url|size|mime|extmetadata", "iiurlwidth": 1800}, headers=UA, timeout=25)
        if r.status_code != 200:
            return out
        pages = (r.json().get("query") or {}).get("pages") or {}
        for pg in sorted(pages.values(), key=lambda p: p.get("index", 0)):
            ii = (pg.get("imageinfo") or [{}])[0]
            if ii.get("mime") not in ("image/jpeg", "image/png"):
                continue
            md = ii.get("extmetadata") or {}
            lic = _clean((md.get("LicenseShortName") or {}).get("value"))
            if not OK_LICENSE.match(lic):
                continue
            out.append({"url": ii.get("thumburl") or ii.get("url"), "w": int(ii.get("thumbwidth") or ii.get("width") or 0), "h": int(ii.get("thumbheight") or ii.get("height") or 0),
                        "title": _clean(pg.get("title", "")).replace("File:", ""), "creator": _clean((md.get("Artist") or {}).get("value")), "license": lic,
                        "page": ii.get("descriptionurl") or "", "source": "Wikimedia Commons"})
    except Exception:  # noqa: BLE001
        pass
    return out


def candidates(queries):
    seen, out = set(), []
    for q in queries:
        for c in from_commons(q) + from_openverse(q):
            key = re.sub(r"\W+", "", c["title"].lower())[:40] or c["url"]
            if key in seen or not c["url"]:
                continue
            seen.add(key)
            out.append(c)
    return out


def _download(c, dest_dir, i):
    try:
        r = S.get(c["url"], headers=UA, timeout=40)
        if r.status_code != 200 or len(r.content) < 8000 or len(r.content) > 25_000_000:
            return None
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(r.content)))
        im.load()
        if min(im.size) < 600 and max(im.size) < 1000:
            return None
        alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        path = os.path.join(dest_dir, f"open_cand_{i}.{'png' if alpha else 'jpg'}")
        im2 = im.convert("RGBA" if alpha else "RGB")
        if max(im2.size) > 2600:
            s = 2600 / max(im2.size)
            im2 = im2.resize((int(im2.size[0] * s), int(im2.size[1] * s)), Image.LANCZOS)
        im2.save(path, "PNG" if alpha else "JPEG", **({} if alpha else {"quality": 93}))
        return path
    except Exception:  # noqa: BLE001
        return None


def _thumb(path):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[3])
        im = bg
    im = im.convert("RGB")
    im.thumbnail((384, 384))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=72)
    return b.getvalue()


def make_queries(req, words=None):
    """2 short search phrases for a request. The writer's own words win; otherwise Gemini writes them; otherwise the request's query."""
    if words:
        return [words]
    base = str(req.get("query") or "").strip()
    try:
        import gemini
        if gemini.available():
            t = gemini.generate('Write 2 short photo-search phrases (2 to 4 plain words each, no adjectives like cinematic or photorealistic) to find a real photograph of the main thing described here: "'
                                + str(req.get("prompt") or base)[:300] + '". Reply JSON only: {"queries":["...","..."]}', json_mode=True, temperature=0.2, rounds=1)
            qs = [str(x).strip() for x in (gemini.parse_json(t).get("queries") or []) if str(x).strip()]
            if qs:
                return qs[:2]
    except Exception:  # noqa: BLE001
        pass
    return [base] if base else []


def find(req, dest_dir, name, words=None, cutout_needed=False):
    """Returns (path, credit line) or (None, why). The picture is saved in dest_dir. Never raises."""
    try:
        qs = make_queries(req, words)
        if not qs:
            return None, "no search words"
        cands = candidates(qs)[:10]
        if not cands:
            return None, "nothing found for " + " / ".join(qs)
        os.makedirs(dest_dir, exist_ok=True)
        got = []
        for i, c in enumerate(cands):
            p = _download(c, dest_dir, i)
            if p:
                got.append((c, p))
        if not got:
            return None, "found pictures but none was usable"
        pick = None
        try:
            import gemini
            if gemini.available():
                listing = "\n".join(f"#{i}: {c['title']} ({c['w']}x{c['h']})" for i, (c, _) in enumerate(got))
                prompt = ("Pictures are shown in order #0, #1, #2 ... They were found by searching the web for real photos.\n" + listing +
                          "\n\nChoose the ONE picture that best shows: " + str(req.get("prompt") or req.get("query"))[:400] +
                          ("\nIt will be cut out from its background, so prefer a single clean object on a plain or simple background, fully visible, nothing cropped." if cutout_needed else "") +
                          "\nIt must show the real, correct thing (right product or place), be sharp and well lit, with no watermark or text added over it, not a drawing, diagram or collage. "
                          'If none fits, answer null. Reply JSON only: {"pick": number or null}')
                t = gemini.generate(prompt, json_mode=True, images=list(reversed([(_thumb(p), "image/jpeg") for _, p in got])), temperature=0.1, rounds=2)
                d = gemini.parse_json(t)
                v = d.get("pick") if isinstance(d, dict) else None
                if isinstance(v, int) and 0 <= v < len(got):
                    pick = v
                else:
                    return None, "no picture fitted"
        except Exception as e:  # noqa: BLE001
            print("::warning::open picture choice by sight failed:", str(e)[:140])
        if pick is None:
            if not words:                                         # automatic use without a judge is too risky: the AI picture is safer
                return None, "no judge available"
            pick = max(range(len(got)), key=lambda i: got[i][0]["w"] * got[i][0]["h"])
        c, p = got[pick]
        final = os.path.join(dest_dir, name + os.path.splitext(p)[1])
        os.replace(p, final)
        for _, other in got:
            if os.path.exists(other):
                os.remove(other)
        who = c["creator"] or "unknown author"
        return final, f"{c['title'][:60]} by {who[:40]} ({c['license']}, {c['source']}) {c['page']}".strip()
    except Exception as e:  # noqa: BLE001
        return None, "open picture search failed: " + str(e)[:100]

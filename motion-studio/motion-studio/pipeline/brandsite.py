"""BRAND SITE getter. The script says  BRAND SITE: https://the-brand.com  and the studio reads that site, downloads the brand's own pictures
(product shots, logo, photos), throws away the tiny / blurry / duplicate ones, and gives each scene the picture that really shows what the scene asks for.
Scenes with no real match keep the normal AI picture. Nothing here can stop a job: every failure just means "use the AI picture".
Use it only for brands whose owner gave you the job."""
import io
import json
import os
import re
import urllib.parse
from html.parser import HTMLParser

from common import S, env
from PIL import Image, ImageOps

UA = {"User-Agent": "Mozilla/5.0 (Windows NT 10.0; Win64; x64) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/124.0 Safari/537.36",
      "Accept": "text/html,application/xhtml+xml,application/json,image/*,*/*;q=0.8", "Accept-Language": "en-US,en;q=0.9"}

SITE_LINE = re.compile(r"^[ \t]*(?:brand[ _-]?(?:site|website|web[ _-]?site)|picture[ _-]?site|image[ _-]?site)[ \t]*[:=][ \t]*(.+?)[ \t]*$", re.I | re.M)
URL_RE = re.compile(r"https?://[^\s,;]+|(?:[A-Za-z0-9-]+\.)+[A-Za-z]{2,}(?:/[^\s,;]*)?", re.I)
BAD_NAME = re.compile(r"sprite|favicon|icon|pixel|spacer|placeholder|loading|loader|avatar|flag|payment|badge|arrow|button|star|rating|emoji|tracking|captcha|1x1|blank|\bad[s]?\b", re.I)
GOOD_PAGE = re.compile(r"product|shop|store|drink|menu|collection|item|gallery|about|service|portfolio|work|catalog|range|flavou?r|buy|our", re.I)
BAD_PAGE = re.compile(r"login|signin|sign-in|register|cart|checkout|account|privacy|terms|cookie|policy|wp-admin|cdn-cgi|\.(pdf|zip|mp4|mp3|xml|json)$|^mailto:|^tel:|^javascript:", re.I)
MAX_PAGES, MAX_DOWNLOADS, MAX_KEEP = 8, 70, 30


def sites_in(text):
    """Returns (list of site urls, the script without the BRAND SITE lines)."""
    urls = []
    for m in SITE_LINE.finditer(str(text or "")):
        for u in URL_RE.findall(m.group(1)):
            u = u.rstrip(".)")
            if not re.match(r"https?://", u, re.I):
                u = "https://" + u
            if u not in urls:
                urls.append(u)
    return urls, SITE_LINE.sub("", str(text or "")).strip("\n") + "\n"


class _Page(HTMLParser):
    def __init__(self, base):
        super().__init__(convert_charrefs=True)
        self.base, self.imgs, self.links, self.title, self._in_title, self._ld, self.ld = base, [], [], "", False, False, []

    def _add(self, u, alt="", w=0, kind="img"):
        u = (u or "").strip()
        if not u or u.startswith("data:"):
            return
        self.imgs.append({"url": urllib.parse.urljoin(self.base, u), "alt": (alt or "").strip(), "w": int(w or 0), "kind": kind})

    def _srcset(self, s, alt):
        best = None
        for part in str(s or "").split(","):
            bits = part.strip().split()
            if not bits:
                continue
            w = 0
            if len(bits) > 1:
                m = re.match(r"(\d+(?:\.\d+)?)([wx])", bits[1])
                if m:
                    w = int(float(m.group(1)) * (1 if m.group(2) == "w" else 1000))
            if best is None or w >= best[1]:
                best = (bits[0], w)
        if best:
            self._add(best[0], alt, best[1])

    def handle_starttag(self, tag, attrs):
        a = {k.lower(): (v or "") for k, v in attrs}
        if tag == "meta":
            key = (a.get("property") or a.get("name") or a.get("itemprop") or "").lower()
            if key in ("og:image", "og:image:url", "og:image:secure_url", "twitter:image", "twitter:image:src", "image"):
                self._add(a.get("content"), kind="meta")
        elif tag == "link" and "image_src" in a.get("rel", "").lower():
            self._add(a.get("href"), kind="meta")
        elif tag in ("img", "source"):
            alt = a.get("alt") or a.get("title") or ""
            for k in ("data-srcset", "srcset", "data-lazy-srcset"):
                if a.get(k):
                    self._srcset(a[k], alt)
                    break
            else:
                for k in ("data-src", "data-lazy-src", "data-original", "data-full", "data-large_image", "src"):
                    if a.get(k):
                        self._add(a[k], alt, a.get("width") if str(a.get("width", "")).isdigit() else 0)
                        break
        elif tag == "a" and a.get("href"):
            self.links.append(urllib.parse.urljoin(self.base, a["href"]))
        elif tag == "title":
            self._in_title = True
        elif tag == "script" and "ld+json" in a.get("type", "").lower():
            self._ld = True
        for k in ("style", "data-bg", "data-background-image"):
            for m in re.finditer(r"url\(['\"]?([^'\")]+)['\"]?\)", a.get(k, "")):
                self._add(m.group(1), kind="bg")

    def handle_endtag(self, tag):
        if tag == "title":
            self._in_title = False
        if tag == "script":
            self._ld = False

    def handle_data(self, data):
        if self._in_title:
            self.title += data
        elif self._ld:
            self.ld.append(data)


def _ld_images(chunks, base):
    out = []
    for raw in chunks:
        try:
            data = json.loads(raw)
        except Exception:  # noqa: BLE001
            continue
        stack = [data]
        while stack:
            d = stack.pop()
            if isinstance(d, list):
                stack.extend(d)
            elif isinstance(d, dict):
                name = str(d.get("name") or "")
                for k in ("image", "logo", "thumbnailUrl"):
                    v = d.get(k)
                    for x in (v if isinstance(v, list) else [v]):
                        u = x.get("url") if isinstance(x, dict) else x
                        if isinstance(u, str) and u:
                            out.append({"url": urllib.parse.urljoin(base, u), "alt": name, "w": 0, "kind": "ld"})
                stack.extend(v for v in d.values() if isinstance(v, (dict, list)))
    return out


def _get(url, tries=2, timeout=20, as_json=False):
    for i in range(tries):
        try:
            r = S.get(url, headers={**UA, "Referer": url}, timeout=timeout)
            if r.status_code == 200:
                if as_json:
                    return r.json()
                if len(r.content) < 4_000_000:
                    return r.text
                return r.text[:4_000_000]
            if r.status_code in (403, 404, 410):
                return None
        except Exception:  # noqa: BLE001
            pass
    return None


def _same_host(a, b):
    ha, hb = urllib.parse.urlparse(a).netloc.lower().removeprefix("www."), urllib.parse.urlparse(b).netloc.lower().removeprefix("www.")
    return ha == hb


def _norm_key(u):
    p = urllib.parse.urlparse(u)
    path = p.path.lower()
    path = re.sub(r"[-_]\d{2,4}x\d{2,4}(?=\.\w+$)", "", path)
    path = re.sub(r"_(?:\d{2,4}x\d{0,4}|\d{0,4}x\d{2,4}|small|medium|large|grande|compact|thumb|pico|icon|master)(?=\.\w+$)", "", path)
    path = re.sub(r"-scaled(?=\.\w+$)", "", path)
    return p.netloc.lower().removeprefix("www.") + path


def _api_images(origin):
    """Shopify, WooCommerce and WordPress shops/sites publish their pictures with names: much better than guessing from the page."""
    out = []
    d = _get(origin + "/products.json?limit=60", tries=1, as_json=True)
    if isinstance(d, dict):
        for pr in (d.get("products") or [])[:60]:
            for im in (pr.get("images") or [])[:3]:
                if im.get("src"):
                    out.append({"url": im["src"], "alt": str(pr.get("title") or "") + " " + re.sub("<[^>]+>", " ", str(pr.get("body_html") or ""))[:120], "w": int(im.get("width") or 0), "kind": "shop"})
    d = _get(origin + "/wp-json/wc/store/products?per_page=40", tries=1, as_json=True)
    if isinstance(d, list):
        for pr in d[:40]:
            for im in (pr.get("images") or [])[:3]:
                if im.get("src"):
                    out.append({"url": im["src"], "alt": str(pr.get("name") or "") + " " + re.sub("<[^>]+>", " ", str(pr.get("short_description") or ""))[:120], "w": 0, "kind": "shop"})
    d = _get(origin + "/wp-json/wp/v2/media?per_page=40&media_type=image", tries=1, as_json=True)
    if isinstance(d, list):
        for m in d[:40]:
            if isinstance(m, dict) and m.get("source_url"):
                t = m.get("title") if isinstance(m.get("title"), dict) else {}
                out.append({"url": m["source_url"], "alt": str(m.get("alt_text") or t.get("rendered") or ""), "w": 0, "kind": "media"})
    return out


def collect_urls(site):
    """Reads the home page and the most useful inner pages. Returns a list of candidate picture dicts (best first) and a note."""
    origin = "{0.scheme}://{0.netloc}".format(urllib.parse.urlparse(site))
    cands, seen_pages, todo = [], set(), [site]
    html0 = None
    pages_read = 0
    while todo and pages_read < MAX_PAGES:
        url = todo.pop(0).split("#")[0]
        if url in seen_pages:
            continue
        seen_pages.add(url)
        html = _get(url)
        if not html:
            continue
        pages_read += 1
        pg = _Page(url)
        try:
            pg.feed(html)
        except Exception:  # noqa: BLE001
            pass
        title = " ".join(pg.title.split())[:80]
        for im in pg.imgs + _ld_images(pg.ld, url):
            im["ctx"] = title
            cands.append(im)
        if html0 is None:
            html0 = html
            links = [l.split("#")[0] for l in pg.links if _same_host(l, origin) and not BAD_PAGE.search(l)]
            links = list(dict.fromkeys(links))
            links.sort(key=lambda l: (0 if GOOD_PAGE.search(urllib.parse.urlparse(l).path) else 1, len(l)))
            todo.extend(links[: MAX_PAGES * 2])
    if pages_read < 3:                                              # few links (menus built by scripts): the sitemap lists the pages
        sm = _get(origin + "/sitemap.xml", tries=1)
        if sm:
            locs = [u for u in re.findall(r"<loc>\s*([^<\s]+)\s*</loc>", sm) if _same_host(u, origin) and not re.search(r"\.xml$", u)]
            locs.sort(key=lambda l: 0 if GOOD_PAGE.search(l) else 1)
            todo = [u for u in locs if u not in seen_pages][: MAX_PAGES]
            while todo and pages_read < MAX_PAGES:
                url = todo.pop(0)
                html = _get(url)
                if not html:
                    continue
                pages_read += 1
                pg = _Page(url)
                try:
                    pg.feed(html)
                except Exception:  # noqa: BLE001
                    pass
                for im in pg.imgs + _ld_images(pg.ld, url):
                    im["ctx"] = " ".join(pg.title.split())[:80]
                    cands.append(im)
    api = _api_images(origin)
    for im in api:
        im["ctx"] = ""
    allc = api + [c for c in cands if c["kind"] in ("meta", "ld")] + [c for c in cands if c["kind"] not in ("meta", "ld")]
    best, order = {}, []
    for c in allc:                                                  # one entry per picture (different sizes of the same picture count once)
        low = c["url"].lower().split("?")[0]
        if low.endswith((".svg", ".gif", ".ico")) or BAD_NAME.search(os.path.basename(low)) and "logo" not in low:
            continue
        k = _norm_key(c["url"])
        if k not in best:
            best[k] = c
            order.append(k)
        else:
            o = best[k]
            if c["w"] > o["w"]:
                best[k] = {**c, "alt": o["alt"] or c["alt"], "ctx": o["ctx"]}
            elif not o["alt"] and c["alt"]:
                o["alt"] = c["alt"]
    return [best[k] for k in order], f"{pages_read} pages read, {len(order)} picture links"


def _ahash(im):
    g = im.convert("L").resize((8, 8))
    px = list(g.getdata())
    avg = sum(px) / 64
    return sum(1 << i for i, v in enumerate(px) if v >= avg)


def download_good(cands, dest_dir, limit=MAX_KEEP, prefix="brandsrc"):
    """Downloads candidates, keeps only usable ones (big enough, not banners, not duplicates). Returns a list of dicts with path/alt/w/h/logo."""
    os.makedirs(dest_dir, exist_ok=True)
    kept, hashes, tried = [], [], 0
    for c in cands:
        if len(kept) >= limit or tried >= MAX_DOWNLOADS:
            break
        tried += 1
        try:
            r = S.get(c["url"], headers={**UA, "Referer": urllib.parse.urljoin(c["url"], "/")}, timeout=25)
            is_logo_url = "logo" in (c["url"] + " " + str(c.get("alt", ""))).lower()
            if r.status_code != 200 or len(r.content) < (500 if is_logo_url else 3000) or len(r.content) > 20_000_000:
                continue
            im = ImageOps.exif_transpose(Image.open(io.BytesIO(r.content)))
            im.load()
        except Exception:  # noqa: BLE001
            continue
        w, h = im.size
        text = (c.get("alt", "") + " " + os.path.basename(c["url"].split("?")[0])).lower()
        logo = "logo" in text or "brand-mark" in text or "wordmark" in text
        if logo:
            if max(w, h) < 200:
                continue
        else:
            if min(w, h) < 450 or max(w, h) < 700:
                continue
            if max(w, h) / max(1, min(w, h)) > 3.2:                  # a thin banner
                continue
        try:
            hh = _ahash(im)
        except Exception:  # noqa: BLE001
            continue
        if any(bin(hh ^ o).count("1") <= 4 for o in hashes):
            continue
        hashes.append(hh)
        alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        ext = "png" if alpha else "jpg"
        path = os.path.join(dest_dir, f"{prefix}_{len(kept) + 1:02d}.{ext}")
        im2 = im.convert("RGBA" if alpha else "RGB")
        if max(w, h) > 2600:
            s = 2600 / max(w, h)
            im2 = im2.resize((int(w * s), int(h * s)), Image.LANCZOS)
        im2.save(path, "PNG" if alpha else "JPEG", **({} if alpha else {"quality": 93}))
        kept.append({"path": path, "url": c["url"], "alt": " ".join(str(c.get("alt", "")).split())[:160], "ctx": c.get("ctx", ""), "w": w, "h": h, "logo": logo, "alpha": bool(alpha)})
    return kept


def _tokens(s):
    stop = {"the", "a", "an", "of", "and", "in", "on", "with", "for", "to", "photo", "photorealistic", "picture", "image", "shot", "close", "up", "no", "text", "logo", "logos", "vertical", "cinematic", "light", "background", "dark", "premium"}
    return {w for w in re.findall(r"[a-z0-9]{3,}", str(s).lower()) if w not in stop}


def _text_match(cands, reqs):
    """Fallback when the vision model is not available: words in the scene against the picture's name and caption."""
    out, used = {}, {}
    for r in reqs:
        want = _tokens(" ".join(str(r.get(k, "")) for k in ("query", "prompt", "use")))
        best, bs = None, 0
        for i, c in enumerate(cands):
            if used.get(i, 0) >= 2:
                continue
            sc = len(want & _tokens(c["alt"] + " " + c["ctx"] + " " + os.path.basename(c["url"].split("?")[0])))
            if c["logo"] and re.search(r"\blogo\b|\bwordmark\b", str(r.get("prompt", "")) + str(r.get("use", "")), re.I):
                sc += 3
            if sc > bs:
                best, bs = i, sc
        if best is not None and bs >= 2:
            out[r["id"]] = best
            used[best] = used.get(best, 0) + 1
    return out


def _thumb(path, side=384):
    im = Image.open(path)
    if im.mode in ("RGBA", "LA", "P"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        im = im.convert("RGBA")
        bg.paste(im, mask=im.split()[3])
        im = bg
    im = im.convert("RGB")
    im.thumbnail((side, side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=72)
    return b.getvalue()


def match(cands, reqs):
    """cands = kept pictures, reqs = the scene picture requests. Returns {request id: index in cands}. Only REAL matches: the scene is about the brand's own
    product / logo / place / people. Generic scenes (a man at a desk, a city street) get nothing and keep their AI picture."""
    if not cands or not reqs:
        return {}
    todo = [r for r in reqs if str(r.get("use", "")).strip().lower() not in ("ai", "none", "generate", "no", "ai picture")]
    if not todo:
        return {}
    cl = cands[:24]
    try:
        import gemini
        if not gemini.available():
            raise RuntimeError("no gemini")
        listing = "\n".join(f"#{i}: {c['w']}x{c['h']}{' [logo]' if c['logo'] else ''} | caption: {c['alt'] or '-'} | page: {c['ctx'] or '-'}" for i, c in enumerate(cl))
        scenes = "\n".join(f"- id {r['id']}: must show: {str(r.get('prompt') or r.get('query'))[:380]}" + (f" | the writer asked for this picture: {r['use']}" if r.get("use") else "") for r in todo)
        prompt = ("You choose real pictures taken from a brand's own website for the scenes of an ad.\nThe pictures are shown in order #0, #1, #2 ... (listed below with their captions).\n"
                  f"PICTURES:\n{listing}\n\nSCENES:\n{scenes}\n\n"
                  "Rules: pick a picture for a scene ONLY when it truly shows what the scene needs: the brand's own product (the real can/bottle/pack/item), its logo, its shop, its team or its real work. "
                  "A scene that is a generic story picture (a person, a street, a mood, an object that is not the brand's product) gets pick null. A scene where the writer asked for a picture must get the picture that fits that request if any exists. "
                  "The product shown must be the one the scene is about. Prefer a clean, sharp, well-lit, fully visible picture. The same picture may serve at most two scenes. "
                  'Reply JSON only: {"matches":[{"id":"scene id","pick":number or null,"why":"short"}]}')
        parts_images = [(_thumb(c["path"]), "image/jpeg") for c in cl]
        # gemini.generate puts each image before the text (inserted at position 0): send them reversed so they arrive in order #0, #1, ...
        txt = gemini.generate(prompt, json_mode=True, images=list(reversed(parts_images)), temperature=0.1, rounds=2)
        data = gemini.parse_json(txt)
        res, used = {}, {}
        ids = {str(r["id"]) for r in todo}
        for m in (data.get("matches") if isinstance(data, dict) else data) or []:
            k, pick = str(m.get("id")), m.get("pick")
            if k in ids and isinstance(pick, int) and 0 <= pick < len(cl) and used.get(pick, 0) < 2:
                res[k] = pick
                used[pick] = used.get(pick, 0) + 1
        return res
    except Exception as e:  # noqa: BLE001
        print("::warning::brand picture matching by sight failed, using captions instead:", str(e)[:160])
        return _text_match(cl, todo)


def fetch_direct(url, dest_dir, name):
    """A picture link written by the client in the script (USE PICTURE: https://...). Returns a path or None."""
    try:
        r = S.get(url, headers={**UA, "Referer": urllib.parse.urljoin(url, "/")}, timeout=30)
        if r.status_code != 200:
            return None
        im = ImageOps.exif_transpose(Image.open(io.BytesIO(r.content)))
        im.load()
        alpha = im.mode in ("RGBA", "LA") or (im.mode == "P" and "transparency" in im.info)
        path = os.path.join(dest_dir, f"{name}.{'png' if alpha else 'jpg'}")
        im.convert("RGBA" if alpha else "RGB").save(path, "PNG" if alpha else "JPEG", **({} if alpha else {"quality": 93}))
        return path
    except Exception:  # noqa: BLE001
        return None


def get(sites, dest_dir):
    """Reads the site(s). Returns (kept pictures, short report for the person)."""
    kept, notes = [], []
    for s in sites[:3]:
        host = urllib.parse.urlparse(s).netloc
        try:
            cands, note = collect_urls(s)
            got = download_good(cands, dest_dir, limit=MAX_KEEP - len(kept), prefix=f"brandsrc{len(kept)}")
            kept.extend(got)
            notes.append(f"{host}: {note}, {len(got)} good pictures kept")
        except Exception as e:  # noqa: BLE001
            notes.append(f"{host}: could not be read ({str(e)[:80]})")
    return kept, "; ".join(notes)

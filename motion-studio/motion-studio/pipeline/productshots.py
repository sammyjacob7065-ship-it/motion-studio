"""Product shots: the studio's 'product brain'.
The client sends ONE photo of a product (a shoe, a phone back, a bottle ...) and the reference video needs many different shots of it
(front, three-quarter, top, close-up, two products, a different side ...). This step:
  1. studies the photo(s): what the product is, which side is shown, what must stay identical, and how the hidden sides must look (by design logic);
  2. plans a shot list that fits the reference scenes (or the script);
  3. makes each missing angle with an AI image-editing model that is given the real photo(s) as the model to copy;
  4. checks every result against the real photo (same product? same colours, shape, logo?) and throws away the ones that drifted;
  5. for angles that could not be made, builds an honest fallback from the real photo itself (close-up crop, tilted view).
Views the client supplied himself (front AND back, for example) are never replaced: the real photo is used for that view.
Everything is optional: with no Gemini image model available, the fallback shots from the real photo are still made."""
import base64
import io
import json
import os
import re

from PIL import Image, ImageOps

from common import S, env

try:
    import gemini
except Exception:  # noqa: BLE001
    gemini = None

BASE = "https://generativelanguage.googleapis.com/v1beta/models/"
DEFAULT_IMAGE_MODELS = "gemini-2.5-flash-image,gemini-3.1-flash-image-preview,gemini-3-pro-image-preview"
_BLOCKED = {}          # image model -> why (quota 0 / no access): skipped for the rest of the job
LOG = []               # what happened, for the Telegram note


def max_shots():
    try:
        return max(2, min(14, int(env("PRODUCT_SHOTS_MAX", "8"))))
    except ValueError:
        return 8


def wanted(prompt, ref, registry):
    """True when the job should get extra product shots: a style reference with scenes (or a line 'PRODUCT SHOTS' / 'different angles' in the brief) and at least one product photo."""
    if env("PRODUCT_SHOTS", "auto").lower() in ("off", "0", "no", "false"):
        return False
    if not product_photos(registry):
        return False
    if env("PRODUCT_SHOTS", "auto").lower() in ("on", "1", "yes", "true"):
        return True
    if isinstance(ref, dict) and ref.get("scenes"):
        return True
    return bool(re.search(r"\bPRODUCT\s+SHOTS?\b|\b(?:different|many|multiple|all|several)\s+angles?\b|\b360\b|\bturn(?:s|ing)?\s+around\b|\bfrom\s+(?:every|all)\s+(?:side|angle)", str(prompt or ""), re.I))


def product_photos(registry):
    """The client's own photos of a product: images that are not a logo and do not show a person."""
    out = []
    for n, a in (registry or {}).items():
        if a.get("kind") != "image" or a.get("generated_shot") or str(n).lower().endswith(".svg"):
            continue
        if "supplied" not in str(a.get("origin", "")) and "client" not in str(a.get("origin", "")):
            continue
        d = a.get("describe") or {}
        if d.get("is_logo") or d.get("has_person"):
            continue
        if min(int(a.get("width") or 0), int(a.get("height") or 0)) < 200:
            continue
        out.append(n)
    return out[:4]


def _jpeg(path, side=1024, quality=85):
    im = ImageOps.exif_transpose(Image.open(path))
    if im.mode in ("RGBA", "LA"):
        bg = Image.new("RGB", im.size, (255, 255, 255))
        bg.paste(im, mask=im.getchannel("A"))
        im = bg
    im = im.convert("RGB")
    im.thumbnail((side, side))
    b = io.BytesIO()
    im.save(b, "JPEG", quality=quality)
    return b.getvalue()


def _ask(prompt, imgs, **kw):
    # gemini.generate puts each image BEFORE the text, inserting at position 0: send them reversed so they arrive as #0, #1 ...
    return gemini.parse_json(gemini.generate(prompt, images=list(reversed([(b, "image/jpeg") for b in imgs])), temperature=kw.get("temperature", 0.2), max_tokens=kw.get("max_tokens", 3000), rounds=2))


# ---------------------------------------------------------------- 1. study the product
PROFILE_ASK = """You are a product photographer and designer. The pictures (#0, #1 ...) are the client's own photos of ONE product, in the order given. Names in order: {names}.
Study them and reply JSON only:
{{"product":"what it is, with the brand/model if printed on it",
 "category":"shoe|phone|bottle|can|box|bag|watch|clothing|cosmetic|other",
 "views":[{{"photo":"file name","view":"front|back|left side|right side|top|bottom|three-quarter|detail|other","clean":true/false}}],
 "must_keep":"the exact things every new picture must keep: shape, proportions, colours, materials, logo and text positions, buttons, camera layout ...",
 "hidden_sides":"how the sides that are NOT visible must look, worked out by design logic (the other side of a shoe mirrors the visible one with the same pattern; the front of a phone is one full screen with thin bezels and a small camera hole; the back of a bottle carries the same label design continued; a box has the same artwork on its other faces). Never invent a new logo or new text that is not visible.",
 "has_text_or_logo":true/false,
 "flat":true/false,
 "background":"what the background is (plain white, busy, ...)"}}"""


def study(names, paths):
    imgs = [_jpeg(paths[n]) for n in names]
    d = _ask(PROFILE_ASK.format(names=", ".join(names)), imgs)
    if not isinstance(d, dict):
        raise RuntimeError("no profile")
    d.setdefault("views", [])
    return d


# ---------------------------------------------------------------- 2. the shot list
PLAN_ASK = """You are the director of photography for a product advert. Product profile:
{profile}

The client supplied these photos (view of each): {have}
A video must be built that needs {n} different pictures of this SAME product. {scenes_text}
Make a shot list of exactly {n} shots, each a DIFFERENT, useful camera view for the scene it serves (examples: hero front view, three-quarter left, three-quarter right, side profile, top-down, low angle looking up, close-up macro of a detail, back view, two products side by side, product slightly tilted floating, product lying on its side). Do not repeat a view.
A shot whose view the client already supplied (same side, same angle) must use that photo: "source":"supplied:<file name>". Every other shot is "source":"generate".
Reply JSON only: {{"shots":[{{"id":"shot1","view":"short name of the angle","scene":<scene number it serves or null>,"source":"supplied:<name>|generate","prompt":"ONE sentence for the image model: what angle, what camera height, how the product is placed (upright, tilted, floating), nothing about the background"}}]}}"""


def plan_shots(profile, have, n, ref_scenes, prompt=""):
    scenes_text = ""
    if ref_scenes:
        lines = [f"{i + 1}. {s.get('what', '')} | motion: {s.get('motion', '')}" for i, s in enumerate(ref_scenes[:30])]
        scenes_text = "The reference video has these scenes (use them to choose the views; pick the scenes where the product is shown):\n" + "\n".join(lines)
    elif prompt:
        scenes_text = "Client brief (for the mood): " + str(prompt)[:800]
    ask = PLAN_ASK.format(profile=json.dumps({k: profile.get(k) for k in ("product", "category", "must_keep", "hidden_sides", "flat")}, ensure_ascii=False), have=json.dumps(have, ensure_ascii=False), n=n, scenes_text=scenes_text)
    d = gemini.parse_json(gemini.generate(ask, temperature=0.4, max_tokens=4000, rounds=2))
    shots = [s for s in (d.get("shots") or []) if isinstance(s, dict) and s.get("view")]
    seen, out = set(), []
    for s in shots:
        k = str(s["view"]).lower().strip()
        if k in seen:
            continue
        seen.add(k)
        s["id"] = re.sub(r"[^A-Za-z0-9_-]", "", str(s.get("id") or f"shot{len(out) + 1}")) or f"shot{len(out) + 1}"
        out.append(s)
    return out[:n]


# ---------------------------------------------------------------- 3. make an angle with an image-editing model
def image_models():
    chosen = [m.strip() for m in env("GEMINI_IMAGE_MODELS", "").split(",") if m.strip()]
    return chosen or [m for m in DEFAULT_IMAGE_MODELS.split(",") if m]


GEN_RULES = ("The pictures are real photos of ONE product. Make a NEW photo of EXACTLY this product: same shape and proportions, same colours, same materials, same logo and text where they are visible, same details. "
             "Do not redesign it, do not change its colours, do not add any logo, brand or text that is not on the real product. "
             "Sides that are not visible in the photos must follow the design logic of the visible side: {hidden} "
             "Product to keep identical: {keep}. "
             "Camera view for this new photo: {view}. "
             "Background: a plain, even, light grey-white studio background with a soft shadow under the product, nothing else in the picture, no hands, no people, no props, no text, no watermark. "
             "Professional product photography, sharp, clean, high detail.")


def _gemini_edit(refs, text):
    """Gemini image model. Returns image bytes or None (raises RuntimeError with the reason when it cannot)."""
    ks = gemini.keys() if gemini else []
    if not ks:
        raise RuntimeError("no Gemini key")
    parts = [{"inline_data": {"mime_type": "image/jpeg", "data": base64.b64encode(b).decode()}} for b in refs] + [{"text": text}]
    body = {"contents": [{"role": "user", "parts": parts}], "generationConfig": {"responseModalities": ["IMAGE", "TEXT"], "temperature": 0.6}}
    last = "no image model answered"
    for m in image_models():
        if m in _BLOCKED:
            last = _BLOCKED[m]
            continue
        for key in ks:
            try:
                r = S.post(BASE + m + ":generateContent", headers={"x-goog-api-key": key, "Content-Type": "application/json"}, data=json.dumps(body), timeout=240)
            except Exception as e:  # noqa: BLE001
                last = str(e)[:100]
                continue
            if r.status_code == 200:
                for c in (r.json().get("candidates") or [])[:1]:
                    for p in (c.get("content") or {}).get("parts") or []:
                        d = p.get("inlineData") or p.get("inline_data")
                        if d and d.get("data"):
                            return base64.b64decode(d["data"])
                last = f"{m}: no picture in answer"
                break
            last = f"{m}: {r.status_code} {r.text[:120]}"
            if r.status_code in (400, 403, 404) or (r.status_code == 429 and re.search(r"limit:\s*0|free.?tier", r.text, re.I)):
                _BLOCKED[m] = last                       # not available on this key: do not try it again in this job
                break
            if r.status_code == 429:
                continue                                   # another key
            break
    raise RuntimeError(last)


def _agnes_edit(refs, text):
    """Agnes image 2.1 flash in image-to-image mode (free keys of the studio). The real photos go in as data URIs in extra_body.image."""
    import requests
    try:
        import imagegen
        keys = imagegen._agnes_keys()
    except Exception:  # noqa: BLE001
        keys = []
    if not keys:
        raise RuntimeError("no Agnes key")
    uris = ["data:image/jpeg;base64," + base64.b64encode(b).decode() for b in refs[:3]]
    last = "Agnes failed"
    for n in range(len(keys)):
        key = keys[n % len(keys)]
        try:
            r = requests.post("https://apihub.agnes-ai.com/v1/images/generations", headers={"Authorization": "Bearer " + key, "Content-Type": "application/json"},
                              json={"model": env("AGNES_EDIT_MODEL", "agnes-image-2.1-flash"), "prompt": text[:1800], "size": "1K", "ratio": "1:1", "extra_body": {"image": uris, "response_format": "b64_json"}}, timeout=360)
            if r.status_code >= 400:
                last = f"agnes {r.status_code} {r.text[:100]}"
                continue
            d = (r.json().get("data") or [{}])[0]
            if d.get("b64_json"):
                return base64.b64decode(d["b64_json"])
            if d.get("url"):
                return requests.get(d["url"], timeout=90).content
            last = "agnes: no picture in answer"
        except Exception as e:  # noqa: BLE001
            last = "agnes " + str(e)[:100]
    raise RuntimeError(last)


def _cloudflare_edit(refs, text):
    """Cloudflare FLUX.2 klein (reference-image editing, up to 4 input pictures, each smaller than 512x512). Multipart form."""
    import requests
    try:
        import imagegen
        acc = env("CLOUDFLARE_ACCOUNT_ID") or getattr(imagegen.K, "CLOUDFLARE_ACCOUNT", "")
        tok = env("CLOUDFLARE_API_TOKEN") or getattr(imagegen.K, "CLOUDFLARE_TOKEN", "")
    except Exception:  # noqa: BLE001
        acc, tok = env("CLOUDFLARE_ACCOUNT_ID"), env("CLOUDFLARE_API_TOKEN")
    if not acc or not tok:
        raise RuntimeError("no Cloudflare key")
    files = {"prompt": (None, text[:1800]), "width": (None, "1024"), "height": (None, "1024")}
    for i, b in enumerate(refs[:4]):
        im = Image.open(io.BytesIO(b)).convert("RGB")
        im.thumbnail((500, 500))                               # the model accepts input pictures smaller than 512x512
        o = io.BytesIO()
        im.save(o, "JPEG", quality=90)
        files[f"input_image_{i}"] = (f"ref{i}.jpg", o.getvalue(), "image/jpeg")
    r = requests.post(f"https://api.cloudflare.com/client/v4/accounts/{acc}/ai/run/{env('CF_EDIT_MODEL', '@cf/black-forest-labs/flux-2-klein-9b')}", headers={"Authorization": "Bearer " + tok}, files=files, timeout=180)
    if r.status_code >= 400:
        raise RuntimeError(f"cloudflare {r.status_code} {r.text[:100]}")
    if r.headers.get("content-type", "").startswith("image"):
        return r.content
    j = r.json()
    if j.get("success") is False:
        raise RuntimeError("cloudflare " + str(j.get("errors"))[:120])
    res = j.get("result") or {}
    return base64.b64decode(res.get("image") or j.get("image") or "")


EDITORS = {"gemini": _gemini_edit, "agnes": _agnes_edit, "cloudflare": _cloudflare_edit}
_DEAD = {}            # provider -> why: a provider without a key / credit is skipped for the rest of the job


def providers():
    order = [x.strip().lower() for x in env("PRODUCT_SHOT_PROVIDERS", "gemini,agnes,cloudflare").split(",") if x.strip()]
    return [x for x in order if x in EDITORS]


def _gen_image(refs, text, short=None, skip=()):
    """Makes one picture from the real photos. Tries the providers in order (Gemini image, Agnes image-to-image, Cloudflare FLUX.2 edit).
    Returns (image bytes, provider name) or (None, None). Providers listed in skip are not used (a provider whose picture was just rejected)."""
    for name in providers():
        if name in _DEAD or name in skip:
            continue
        try:
            b = EDITORS[name](refs, text if name == "gemini" else (short or text))
            if b and len(b) > 1500 and (b[:3] == b"\xff\xd8\xff" or b[:4] == b"\x89PNG" or b[:4] == b"RIFF"):
                return b, name
            LOG.append(f"{name}: broken picture")
        except Exception as e:  # noqa: BLE001
            why = str(e)[:140]
            LOG.append(why)
            if re.search(r"no \w+ key|401|402|403|unauthor|quota|credit|balance|limit:\s*0", why, re.I):
                _DEAD[name] = why
    return None, None


# ---------------------------------------------------------------- 4. the check
VERIFY_ASK = """Picture #0 and the following ones are the REAL product photos. The LAST picture is a new AI-made picture that must show the SAME product from this view: {view}.
Judge strictly. Reply JSON only: {{"same_product":true/false,"score":0-10,"problems":"what differs (shape, colour, logo, text, parts, extra objects, hands, text added) or empty","right_view":true/false}}.
Same product means the same shape, proportions, colours, materials, logo/text where visible. Invented new logos or text, changed colours or a different model = false."""


def verify(real_jpegs, candidate_jpeg, view):
    try:
        d = _ask(VERIFY_ASK.format(view=view), real_jpegs + [candidate_jpeg], temperature=0.0, max_tokens=500)
        ok = bool(d.get("same_product")) and float(d.get("score") or 0) >= float(env("PRODUCT_SHOT_MIN_SCORE", "7")) and d.get("right_view") is not False
        return ok, str(d.get("problems") or "")
    except Exception as e:  # noqa: BLE001
        return False, "check failed: " + str(e)[:80]


# ---------------------------------------------------------------- 5. fallback shots built from the real photo
def _persp(im, side, k=0.16):
    """A tilted view of a flat picture: one vertical edge is made shorter (perspective), the empty corners stay transparent."""
    im = im.convert("RGBA")
    w, h = im.size
    d = int(h * k)
    src = [(0, 0), (w, 0), (w, h), (0, h)]
    dst = [(0, d), (w, 0), (w, h), (0, h - d)] if side == "left" else [(0, 0), (w, d), (w, h - d), (0, h)]
    # PIL wants the coefficients that map output -> input
    import numpy as np
    A, B = [], []
    for (x, y), (u, v) in zip(dst, src):
        A += [[x, y, 1, 0, 0, 0, -u * x, -u * y], [0, 0, 0, x, y, 1, -v * x, -v * y]]
        B += [u, v]
    coef = np.linalg.solve(np.array(A, float), np.array(B, float))
    return im.transform((w, h), Image.PERSPECTIVE, tuple(coef), Image.BICUBIC)


def fallback(path, view, dest):
    """Makes an honest variant from the real photo. Returns the saved path or None. 'view' decides: a close-up crop, or a tilted left / right view."""
    v = str(view).lower()
    try:
        im = ImageOps.exif_transpose(Image.open(path)).convert("RGBA")
        W, H = im.size
        if re.search(r"macro|close|detail|zoom", v):
            cw, ch = int(W * 0.55), int(H * 0.55)
            x0, y0 = (W - cw) // 2, (H - ch) // 2
            out = im.crop((x0, y0, x0 + cw, y0 + ch))
            if min(out.size) < 900:
                out = out.resize((out.width * 2, out.height * 2), Image.LANCZOS)
        elif re.search(r"left", v) or re.search(r"three-quarter|3/4|angle|tilt|float", v):
            out = _persp(im, "left")
        elif re.search(r"right", v):
            out = _persp(im, "right")
        else:
            return None
        out.save(dest)
        return dest
    except Exception as e:  # noqa: BLE001
        print("::warning::fallback shot failed:", str(e)[:100])
        return None


# ---------------------------------------------------------------- the whole step
def make(registry, paths, adir, work, prompt, ref, analyze, tg=None, n=None):
    """Adds the shots to registry / paths (names like product_shot1.png). Returns the list of new names. Never raises."""
    import assets as A
    new = []
    try:
        if not gemini or not gemini.available():
            if tg:
                tg.send("📸 Product shots: no Gemini key, so I used your photo as it is.")
            return new
        names = product_photos(registry)
        ref_scenes = (ref or {}).get("scenes") if isinstance(ref, dict) else None
        count = n or min(max_shots(), max(3, len(ref_scenes or []) or 6))
        profile = study(names, paths)
        have = [{"photo": v.get("photo"), "view": v.get("view")} for v in profile.get("views", []) if v.get("photo") in names] or [{"photo": names[0], "view": "unknown"}]
        shots = plan_shots(profile, have, count, ref_scenes, prompt)
        real = [_jpeg(paths[x]) for x in names]
        made_ai = made_fb = used_real = 0
        by = {}
        for i, s in enumerate(shots):
            src = str(s.get("source", "generate"))
            nm = f"product_shot{i + 1}.png"
            dest = os.path.join(adir, nm)
            ok_path, how = None, ""
            if src.startswith("supplied:") and src.split(":", 1)[1] in names:
                sup = src.split(":", 1)[1]
                registry[sup]["shot"] = s["view"]               # the client's own photo already is this view: it is named for the director, not copied
                registry[sup]["scene_for"] = s.get("scene")
                used_real += 1
                new.append(sup)
                continue
            text = GEN_RULES.format(hidden=str(profile.get("hidden_sides", ""))[:500], keep=str(profile.get("must_keep", ""))[:500], view=str(s.get("prompt") or s["view"])[:300])
            short = (f"Make a new photo of EXACTLY the product in the reference pictures: same shape, colours, materials, logo and text, nothing invented. View: {str(s.get('prompt') or s['view'])[:200]}. "
                     f"Keep identical: {str(profile.get('must_keep', ''))[:300]}. Hidden sides follow the visible design: {str(profile.get('hidden_sides', ''))[:300]}. "
                     "Plain light grey-white studio background, soft shadow, no hands, no people, no props, no text added, product photography, sharp.")
            skip, tried = [], 0
            while tried < 3 and not ok_path:
                tried += 1
                raw, who = _gen_image(real, text + (" PREVIOUS TRY WAS REJECTED BECAUSE: " + how if how else ""), short=short + (" Fix: " + how if how else ""), skip=skip)
                if not raw:
                    break
                good, how = verify(real, _to_jpeg(raw), s["view"])
                if good:
                    open(dest, "wb").write(_to_png(raw))
                    ok_path = dest
                    by[who] = by.get(who, 0) + 1
                else:
                    LOG.append(f"{who}: picture rejected ({how[:60]})")
                    skip.append(who)                    # the next try uses the next provider
            if ok_path:
                made_ai += 1
                origin = "AI shot made from the client's photo"
            else:
                fb = fallback(paths[names[0]], s["view"], dest)
                if not fb:
                    continue
                ok_path, origin = fb, "the client's photo, framed for this view"
                made_fb += 1
            final, info, flags = analyze(ok_path, work)
            info["flags"], info["origin"], info["shot"], info["scene_for"], info["generated_shot"] = flags, origin, s["view"], s.get("scene"), True
            info["describe"] = {"what": f"{profile.get('product', 'the product')} - {s['view']}", "is_logo": False, "has_person": False}
            k = os.path.basename(final)
            registry[k], paths[k] = info, final
            new.append(k)
        if tg:
            tg.send(f"📸 Product shots for {profile.get('product', 'your product')}: {len(shots)} planned, {made_ai} made by AI from your photo and checked" + (" (" + ", ".join(f"{k} {v}" for k, v in by.items()) + ")" if by else "") + f", {made_fb} built from your real photo, {used_real} are your own photos."
                    + (("\nWhy some AI shots were not used: " + " | ".join(dict.fromkeys(LOG))[:400]) if LOG and made_fb else ""))
    except Exception as e:  # noqa: BLE001
        print("::warning::product shots skipped:", str(e)[:200])
        if tg:
            tg.send("📸 Product shots skipped (" + str(e)[:120] + "). Your photo is used as it is.")
    return new


def _to_jpeg(b):
    im = Image.open(io.BytesIO(b)).convert("RGB")
    im.thumbnail((1024, 1024))
    o = io.BytesIO()
    im.save(o, "JPEG", quality=85)
    return o.getvalue()


def _to_png(b):
    o = io.BytesIO()
    Image.open(io.BytesIO(b)).convert("RGB").save(o, "PNG")
    return o.getvalue()


def director_text(registry):
    """What the director must be told: which shots exist and which scene each one is for."""
    rows = []
    for n, a in registry.items():
        if a.get("shot"):
            sc = f" (made for reference scene {a['scene_for']})" if a.get("scene_for") else ""
            rows.append(f"- {n}: {a['shot']}{sc}")
    if not rows:
        return ""
    return ("PRODUCT SHOTS (the same product from different views, ready to use as pictures; use a DIFFERENT shot in each scene that shows the product, in the order of the scenes, and never make a new AI picture of the product when a shot fits):\n" + "\n".join(rows) + "\n")

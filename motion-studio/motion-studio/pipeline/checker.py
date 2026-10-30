"""The sync checker and polish department.
After the director has written the timeline, this module checks it against the real voice:
  1. every text / price counter is moved to the second the voice says its words (the voice wins over the brief's seconds),
  2. pictures, icons and shapes that belong to a text move with it,
  3. every sound effect moves with the graphic it belongs to,
  4. overlaps made by the moves are trimmed, picture changes get a flash, ambient dust and a slow camera push are added if missing.
It never removes content and it never raises: if anything goes wrong the timeline is returned as it was."""
import copy
import math
import re

import timeline as T

STOP = set("a an the and or to of in on at for from with is are was be your you our my it this that now wait every do not no we i me so as by up us can all".split())
ONES = "zero one two three four five six seven eight nine ten eleven twelve thirteen fourteen fifteen sixteen seventeen eighteen nineteen".split()
TENS = "_ _ twenty thirty forty fifty sixty seventy eighty ninety".split()


GENERIC = set("modern beautiful luxury luxurious bright high quality photo photos picture pictures image images nice new good great big large front inside outside view views background stock professional real happy smiling".split())
SYN = {
    "house": "house houses home homes property properties duplex villa", "home": "home homes house houses property duplex villa",
    "estate": "estate gated compound community secure security safe", "gated": "gated estate compound secure security safe gate",
    "gate": "gate gated entrance estate", "entrance": "entrance gate gated estate",
    "road": "road roads street streets drive", "street": "street streets road roads",
    "light": "light lights electricity power lamp", "electricity": "electricity light lights power",
    "water": "water borehole tap", "pool": "pool swimming", "swimming": "swimming pool",
    "family": "family families children kids parents", "kitchen": "kitchen cooking", "garden": "garden gardens green lawn",
    "price": "price prices cost naira million cheap affordable", "money": "money naira million pay payment installments",
    "key": "key keys", "room": "room living lounge sitting bedroom", "city": "city lagos lekki", "lagos": "lagos lekki city",
}


def _groups(text):
    """Keywords of a picture description as groups of words that mean the same (house = homes = property ...)."""
    out = []
    for t in _tok(text):
        if t in STOP or t in GENERIC or len(t) < 3:
            continue
        stem = t[:-1] if t.endswith("s") and len(t) > 3 else t
        out.append(tuple(sorted(set([t, stem] + SYN.get(stem, SYN.get(t, "")).split()))))
    seen, uniq = set(), []
    for g in out:
        if g not in seen:
            seen.add(g)
            uniq.append(g)
    return uniq[:6]


def phrase_for(query, voice_text):
    """The part of the voice-over a picture query is about (by keywords), or ''."""
    groups = _groups(query)
    if not groups:
        return ""
    best, best_score = "", 0
    for ph in re.split(r"(?<=[.!?,;:])\s+", str(voice_text or "")):
        toks = _tok(ph)
        score = sum(1 for g in groups if any(_same(t, v) for t in toks for v in g))
        if score > best_score:
            best, best_score = ph.strip(), score
    return best


def _tok(s):
    return [t for t in re.sub(r"[^a-z0-9 ]", " ", str(s).lower().replace("\n", " ")).split() if t]


def _same(a, b):
    return a == b or (len(a) >= 3 and len(b) >= 3 and (a.startswith(b) or b.startswith(a)))


def _below_1000(n):
    out = []
    if n >= 100:
        out += [ONES[n // 100], "hundred"]
        n %= 100
    if n >= 20:
        out.append(TENS[n // 10])
        n %= 10
        if n:
            out.append(ONES[n])
    elif n > 0 or not out:
        out.append(ONES[n])
    return out


def num_words(n):
    """15000000 -> ['fifteen', 'million'] (what a voice says for a number)."""
    n = int(n)
    if n == 0:
        return ["zero"]
    out = []
    for size, name in ((10 ** 9, "billion"), (10 ** 6, "million"), (1000, "thousand")):
        if n >= size:
            out += _below_1000(n // size) + [name]
            n %= size
    if n:
        out += _below_1000(n)
    return out


def _spoken(words, voice_start):
    return [(_tok(w["w"])[0] if _tok(w["w"]) else "", float(w["s"]) + voice_start, float(w["e"]) + voice_start) for w in words]


def _find_trigger(sw, kws, old_start, need=None):
    """Index of the spoken word where the voice starts saying these keywords (closest to the old start)."""
    if not kws:
        return None
    kws = [(k,) if isinstance(k, str) else tuple(k) for k in kws]
    need = need or max(1, math.ceil(0.6 * len(kws)))
    best = None
    for i in range(len(sw)):
        if not sw[i][0] or not any(_same(sw[i][0], v) for g in kws for v in g):
            continue
        window = sw[i:i + len(kws) + 3]
        got = {g for g in kws for t, _s, _e in window if t and any(_same(t, v) for v in g)}
        if len(got) < need:
            continue
        score = (-len(got), abs(sw[i][1] - old_start))
        if best is None or score < best[0]:
            best = (score, i)
    return best[1] if best else None


def _shift(layer, d):
    layer["start"] = round(max(0.0, layer["start"] + d), 3)
    layer["end"] = round(layer["end"] + d, 3)
    for name, keys in (layer.get("anim") or {}).items():
        for k in keys:
            try:
                k[0] = round(float(k[0]) + d, 3)
            except Exception:  # noqa: BLE001
                pass


def _is_ambient(l, dur):
    return l["type"] in ("particles", "captions", "transition") or (l["start"] <= 0.01 and l["end"] >= dur - 0.05)


def _fullbleed(l, W):
    return l["type"] == "image" and float((l.get("props") or {}).get("width") or 0) >= 0.9 * W


def _warp(t, anchors):
    """Where a moment of the old plan lands in the new one, from the matched anchors (old, new), moving smoothly between them."""
    if not anchors:
        return t
    if t <= anchors[0][0]:
        return t + (anchors[0][1] - anchors[0][0]) * (t / anchors[0][0] if anchors[0][0] > 0 else 1.0)
    for (o0, n0), (o1, n1) in zip(anchors, anchors[1:]):
        if t <= o1:
            return n0 + (n1 - n0) * ((t - o0) / (o1 - o0) if o1 > o0 else 0.0)
    return t + (anchors[-1][1] - anchors[-1][0])


def _leave_with_picture(layers, W, dur):
    """Every graphic leaves with the picture of its scene (the words of "24/7 SECURITY" must not stay after the gate picture is gone). Returns how many were cut short."""
    pics = sorted([l for l in layers if _fullbleed(l, W) and not _is_ambient(l, dur)], key=lambda x: x["start"])
    left = 0
    if len(pics) >= 2:
        for l in layers:
            if l["type"] not in ("text", "counter", "icon", "shape", "line") or _is_ambient(l, dur) or _fullbleed(l, W):
                continue
            owner = None
            for k, pic in enumerate(pics):
                if pic["start"] - 0.05 <= l["start"] < (pics[k + 1]["start"] if k + 1 < len(pics) else 1e9):
                    owner = k
            if owner is None or owner >= len(pics) - 1:
                continue                                   # before the first picture, or in the last scene (the logo / call to action stays)
            wend = round(pics[owner + 1]["start"] + 0.15, 3)
            if l["end"] > wend + 0.05:
                l["end"] = max(wend, round(l["start"] + 0.8, 3))
                if not l.get("exit"):
                    l["exit"] = {"preset": "fade", "dur": 0.3}
                left += 1
    return left


def sync(tl, audio, words, voice_start, assets, trim=True):
    report = []
    if not words:
        return tl, audio, report
    dur, W = tl["duration"], tl["width"]
    sw = _spoken(words, voice_start)
    layers = tl["layers"]
    old = {l["id"]: (l["start"], l["end"]) for l in layers}
    new_start = {}                                   # matched layers: id -> the second the voice says them
    # 1) text and counters follow the words
    for l in layers:
        if l["type"] not in ("text", "counter", "image") or _is_ambient(l, dur):
            continue
        p = l.get("props") or {}
        if l["type"] == "image":
            info = (assets or {}).get(p.get("asset"), {}) or {}
            said = info.get("phrase") or info.get("query") or ""
            groups = _groups(said)
            i = _find_trigger(sw, groups, l["start"], (1 if len(groups) <= 2 else None))
            if i is not None:
                new_start[l["id"]] = (max(0.0, sw[i][1] - 0.3), f"picture '{str(info.get('query') or said)[:24]}'", sw[i])
            continue
        if l["type"] == "counter":
            try:
                kws = num_words(float(p.get("to", 0)))
            except Exception:  # noqa: BLE001
                kws = []
            lead, need, label = 0.55, 1, f"{p.get('prefix', '')}{p.get('to', '')}{p.get('suffix', '')}"
        else:
            kws = [t for t in _tok(p.get("text", "")) if t not in STOP][:6]
            lead, need, label = 0.25, (1 if len(kws) <= 2 else None), str(p.get("text", "")).replace("\n", " ")
        i = _find_trigger(sw, kws, l["start"], need)
        if i is None:
            continue
        new_start[l["id"]] = (max(0.0, sw[i][1] - lead), label, sw[i])
    # anchors for the smooth time map (must keep the order of events)
    anchors, last_new = [], -1.0
    for o, n in sorted((old[k][0], v[0]) for k, v in new_start.items()):
        if n >= last_new - 0.05 and (not anchors or o > anchors[-1][0]):
            anchors.append((o, n))
            last_new = n
    delta = {}
    for l in layers:
        if _is_ambient(l, dur):
            continue
        o = old[l["id"]][0]
        if l["id"] in new_start:
            d = new_start[l["id"]][0] - o
        else:
            near = [(abs(ao - o), an - ao) for ao, an in anchors if abs(ao - o) <= (1.6 if l["type"] not in ("text", "counter") else 1.2)]
            d = min(near)[1] if near else _warp(o, anchors) - o
        if abs(d) >= 0.08:
            delta[l["id"]] = d
    for l in layers:
        if l["id"] in delta:
            _shift(l, delta[l["id"]])
            l["end"] = round(min(dur, l["end"]), 3)
            if l["end"] <= l["start"] + 0.3:
                l["end"] = round(min(dur, l["start"] + 1.5), 3)
    for k, (n, label, w) in new_start.items():
        d = n - old[k][0]
        if abs(d) >= 0.12:
            report.append((abs(d), f"'{label[:28]}' {old[k][0]:.1f}s -> {n:.1f}s (voice says \"{w[0]}\" at {w[1]:.1f}s)"))
    # 3) picture sequence: no gaps, no long overlaps
    pics = sorted([l for l in layers if _fullbleed(l, W) and not _is_ambient(l, dur)], key=lambda x: x["start"])
    for a, b in zip(pics, pics[1:]):
        a["end"] = round(min(dur, max(a["start"] + 0.5, b["start"] + 0.3)), 3)
    left = _leave_with_picture(layers, W, dur)
    if left:
        report.append((0.0, f"{left} graphics now leave with their picture"))
    # 4) sound effects follow their graphic (or the time map)
    moved_audio = 0
    for a in audio or []:
        try:
            s0 = float(a.get("start", 0))
        except Exception:  # noqa: BLE001
            continue
        cands = [(abs(old[l["id"]][0] - s0), l) for l in layers if l["id"] in old and l["type"] in ("text", "counter", "image", "icon", "shape") and not _is_ambient(l, dur)]
        cands = [c for c in cands if c[0] <= 0.9]
        if cands:
            l = min(cands, key=lambda c: c[0])[1]
            d = l["start"] - old[l["id"]][0]
        else:
            d = _warp(s0, anchors) - s0
        if abs(d) >= 0.08:
            a["start"] = round(max(0.0, s0 + d), 3)
            moved_audio += 1
    # 5) overlaps made by the moves (text that did not overlap before)
    boxes = []
    for l in layers:
        if l["type"] in ("text", "counter"):
            b = T._box(l, tl["width"], tl["height"], assets)
            if b is not None:
                boxes.append((l, b))
    for i in range(len(boxes)):
        for j in range(i + 1, len(boxes)):
            (la, ba), (lb, bb) = boxes[i], boxes[j]
            if la["start"] > lb["start"]:
                la, lb, ba, bb = lb, la, bb, ba
            if min(la["end"], lb["end"]) - max(la["start"], lb["start"]) < 0.2:
                continue
            oa, ob = old[la["id"]], old[lb["id"]]
            if min(oa[1], ob[1]) - max(oa[0], ob[0]) >= 0.2:
                continue                              # they already overlapped in the director's plan: not caused by the moves
            small = min((ba[2] - ba[0]) * (ba[3] - ba[1]), (bb[2] - bb[0]) * (bb[3] - bb[1])) or 1
            if T._inter(ba, bb) / small > 0.18 and lb["start"] + 0.05 >= la["start"] + 0.5:
                la["end"] = round(lb["start"] + 0.05, 3)
    # 6) the video ends when the voice is done (plus a short hold), not long after
    voice_end = sw[-1][2]
    target = round(voice_end + 2.0, 2)
    if trim and tl["duration"] > target + 2.5:
        old_dur = tl["duration"]
        content_end = max([l["end"] for l in layers if not _is_ambient(l, dur)] or [0.0])
        tl["duration"] = target
        for l in layers:
            if l["end"] >= content_end - 0.01 or l["end"] >= old_dur - 0.05:
                l["end"] = target
            l["end"] = round(min(target, l["end"]), 3)
            l["start"] = round(min(l["start"], target - 0.2), 3)
        tl["camera"] = [[min(k[0], target)] + list(k[1:]) for k in (tl.get("camera") or [])]
        report.append((0.0, f"the voice finishes at {voice_end:.1f}s, so the video now ends at {target:.1f}s (was {old_dur:.0f}s)"))
    report.sort(reverse=True)
    lines = [r[1] for r in report[:5]]
    if delta or moved_audio:
        lines.insert(0, f"{len(delta)} graphics and {moved_audio} sounds were moved to match the voice")
    return tl, audio, lines


def _move_y(layer, dy):
    layer["y"] = round(float(layer.get("y", 0)) + dy, 1)
    for k in (layer.get("anim") or {}).get("y", []) or []:
        try:
            k[1] = round(float(k[1]) + dy, 1)
        except Exception:  # noqa: BLE001
            pass


def declutter(tl, assets):
    """Nothing may sit on top of anything else: text vs captions, text vs text, text vs icons. A text that is in the way slides up or down
    (with the plate / line / icon that belongs to it) to the nearest free place. Returns the list of what was moved."""
    W, H = tl["width"], tl["height"]
    layers = tl["layers"]
    zones = []
    for l in layers:
        if l["type"] == "captions" and (l.get("props") or {}).get("words"):
            size = float((l["props"].get("size")) or 74)
            cy = float(l["props"].get("y") or H * 0.72)
            half = size * 1.25 + 14
            zones.append((l, (W * 0.07, cy - half, W * 0.93, cy + half)))

    def box(l):
        return T._box(l, W, H, assets)

    def clash(l, b, others):
        for o, ob in others:
            if o is l:
                continue
            if min(l["end"], o["end"]) - max(l["start"], o["start"]) < 0.25:
                continue
            small = min((b[2] - b[0]) * (b[3] - b[1]), (ob[2] - ob[0]) * (ob[3] - ob[1])) or 1
            if T._inter(b, ob) / small > 0.06:
                return True
        return False

    def solids():
        out = list(zones)
        for o in layers:
            if o["type"] in ("text", "counter", "icon"):
                ob = box(o)
                if ob:
                    out.append((o, ob))
        return out

    moved = []
    for l in sorted([x for x in layers if x["type"] in ("text", "counter")], key=lambda x: x["start"]):
        b = box(l)
        if not b:
            continue
        others = solids()
        if not clash(l, b, others):
            continue
        near_zone = any(z is not l and min(l["end"], z["end"]) - max(l["start"], z["start"]) >= 0.25 and T._inter(b, zb) > 0 for z, zb in zones)
        order = [-1, 1] if near_zone else [1, -1]
        done = False
        for step in range(30, 900, 30):
            for sgn in order:
                dy = sgn * step
                nb = (b[0], b[1] + dy, b[2], b[3] + dy)
                if nb[1] < H * 0.05 or nb[3] > H * 0.95:
                    continue
                if clash(l, nb, others):
                    continue
                # the plate / line / icon that belongs to this text moves with it
                for m in layers:
                    if m is l or m["type"] not in ("shape", "line", "icon") or _fullbleed(m, W):
                        continue
                    if min(l["end"], m["end"]) - max(l["start"], m["start"]) < 0.2:
                        continue
                    if b[0] - 80 <= m.get("x", -1e9) <= b[2] + 80 and b[1] - 80 <= m.get("y", -1e9) <= b[3] + 80:
                        _move_y(m, dy)
                _move_y(l, dy)
                moved.append(f"'{str((l.get('props') or {}).get('text') or l['id'])[:22]}' moved {'up' if dy < 0 else 'down'} {abs(dy)}px (was on top of other text/captions)")
                done = True
                break
            if done:
                break
    return moved


def handoff(tl, assets=None):
    """A label must be gone the moment the next label arrives. Labels in the top half are cut at the start of the next one (their plate / icon / line goes with them).
    Returns a list of what was shortened."""
    W, H, dur = tl["width"], tl["height"], tl["duration"]
    layers = tl["layers"]
    labels = sorted([l for l in layers if l["type"] in ("text", "counter") and l.get("id") != "watermark" and not _is_ambient(l, dur) and float(l.get("y", H / 2)) < H * 0.5], key=lambda x: x["start"])
    done = []
    for i, l in enumerate(labels):
        nxt = [m for m in labels[i + 1:] if m["start"] > l["start"] + 0.3]
        if not nxt:
            continue
        n = min(nxt, key=lambda x: x["start"])
        if l["end"] <= n["start"] + 0.02:
            continue
        old = l["end"]
        l["end"] = round(max(l["start"] + 0.5, n["start"]), 3)
        for m in layers:
            if m is l or m["type"] not in ("shape", "line", "icon") or _fullbleed(m, W) or _is_ambient(m, dur):
                continue
            if abs(m["start"] - l["start"]) < 0.5 and abs(m["end"] - old) < 0.6:
                m["end"] = min(m["end"], l["end"])
        done.append(f"{str((l.get('props') or {}).get('text', l['id']))[:22]} now leaves at {l['end']:.1f}s")
    return done


_COLORS = {"white": "#ffffff", "black": "#000000", "gold": "#f5c451", "green": "#1ed760", "navy": "#0a2a6b", "blue": "#2f7df6", "red": "#e5322d", "orange": "#ff8a00", "grey": "#bdbdbd", "gray": "#bdbdbd", "silver": "#c9c9c9"}


def watermark(tl, spec):
    """A brand name for the whole video. spec = 'NAME' or 'NAME | option | option' where an option is a position (top, bottom, top left, top right, bottom left,
    bottom right, centre), a size (small, medium, large), a colour (white, gold, navy, ... or #hex) or a strength (30%, 80%). Default: small, white, 50%, bottom centre.
    Returns True when added."""
    parts = [x.strip() for x in re.split(r"[|;]", str(spec or "")) if x.strip()]
    if not parts or any(l.get("id") == "watermark" for l in tl["layers"]):
        return False
    text = parts[0][:40]
    W, H, dur = tl["width"], tl["height"], tl["duration"]
    pos, size, color, op = "bottom", 30, "#ffffff", 0.5
    for o in (x.lower() for x in parts[1:]):
        m = re.fullmatch(r"(\d{1,3})\s*%", o)
        if m:
            op = max(0.1, min(1.0, int(m.group(1)) / 100))
        elif re.fullmatch(r"#[0-9a-f]{6}", o):
            color = o
        elif o in _COLORS:
            color = _COLORS[o]
        elif o in ("small", "medium", "large", "big"):
            size = {"small": 30, "medium": 44, "large": 60, "big": 60}[o]
        else:
            pos = o
    xs = W * 0.17 if "left" in pos else (W * 0.83 if "right" in pos else W / 2)
    ys = H * 0.06 if "top" in pos else (H * 0.5 if pos.startswith(("centre", "center", "middle")) else H * 0.94)
    if "left" in pos or "right" in pos:
        xs = W * (0.2 if "left" in pos else 0.8)
    tl["layers"].append({"id": "watermark", "type": "text", "start": 0.0, "end": dur, "x": round(xs), "y": round(ys), "z": 99, "parallax": 0, "enter": None, "exit": None,
                         "anim": {"opacity": [[0.0, op], [round(dur, 2), op]]},
                         "props": {"text": text, "size": size, "weight": 600, "letterSpacing": 7, "color": color, "font": "Montserrat", "mode": "block", "shadow": {"y": 2, "blur": 6, "opacity": 0.6}}})
    return True


def sound_design(tl, audio):
    """Makes the sound track active: a counting sound while a number rolls (and a hit when it lands), a whoosh at every picture change,
    a pop when a label appears, a shimmer on the last scene. Only adds a sound where the director put none close by."""
    dur, W = tl["duration"], tl["width"]
    layers = tl["layers"]
    ev = [a for a in (audio or []) if isinstance(a, dict)]
    added = {"counting": 0, "whoosh": 0, "pop": 0, "shimmer": 0}

    def near(t, w=0.3, names=None):
        for a in ev:
            try:
                if abs(float(a.get("start", 0)) - t) <= w and (names is None or a.get("sfx") in names):
                    return True
            except Exception:  # noqa: BLE001
                pass
        return False

    def add(name, t, vol, **kw):
        ev.append({"role": "sfx", "sfx": name, "start": round(max(0.0, t), 3), "volume": vol, **kw})

    for l in layers:
        if l["type"] != "counter":
            continue
        p = l.get("props") or {}
        d = float(p.get("countDur") or 1.6)
        t0 = l["start"] + float(p.get("delay") or 0)
        ev[:] = [a for a in ev if not (a.get("sfx") in ("tick", "click") and t0 - 0.2 <= float(a.get("start", -9)) <= t0 + d + 0.1)]   # one counting sound, not many single ticks
        add("roll", t0, 0.45, dur=round(min(d + 0.1, 1.7), 2))
        if not near(t0 + d, 0.3, ("hit",)):
            add("hit", t0 + d, 0.7)
        added["counting"] += 1
    pics = sorted([l for l in layers if _fullbleed(l, W) and not _is_ambient(l, dur)], key=lambda x: x["start"])
    for k, pic in enumerate(pics[1:], 1):
        if not near(pic["start"] - 0.05, 0.35, ("whoosh", "swoosh_up", "hit", "riser")):
            add("whoosh", pic["start"] - 0.05, 0.32)
            added["whoosh"] += 1
    for l in layers:
        if l["type"] not in ("text", "icon", "shape") or _is_ambient(l, dur) or _fullbleed(l, W) or l["start"] < 0.2:
            continue
        if l["type"] == "shape" and float((l.get("props") or {}).get("width") or 0) < 120:
            continue
        if not near(l["start"], 0.3):
            add("pop", l["start"], 0.35)
            added["pop"] += 1
    if len(pics) >= 2 and not near(pics[-1]["start"], 0.6, ("shimmer", "sparkle")):
        add("shimmer", pics[-1]["start"] + 0.3, 0.4)
        added["shimmer"] += 1
    ev.sort(key=lambda a: float(a.get("start", 0)))
    return ev, {k: v for k, v in added.items() if v}


def polish(tl):
    """Small safe touches that make the video livelier. Only adds; never removes."""
    dur, W, H = tl["duration"], tl["width"], tl["height"]
    layers = tl["layers"]
    added = []
    acc = (tl.get("palette") or {}).get("accent", "#f5c451")
    if not any(l["type"] == "particles" for l in layers):
        layers.append({"id": "auto_dust", "type": "particles", "start": 0.0, "end": dur, "x": W / 2, "y": H / 2, "z": 2, "parallax": 0.5, "enter": None, "exit": None, "anim": {},
                       "props": {"mode": "float", "count": 70, "area": [W, H], "colors": [acc, "#ffffff"], "size": [3, 8], "speed": 60, "life": 6, "direction": -90, "opacity": 0.5, "glow": True, "seed": 7}})
        added.append("floating dust")
    pics = sorted([l for l in layers if _fullbleed(l, W) and not _is_ambient(l, dur)], key=lambda x: x["start"])
    trans = [l for l in layers if l["type"] == "transition"]
    n = 0
    for p in pics[1:]:
        if any(abs(((t["start"] + t["end"]) / 2) - p["start"]) < 0.5 for t in trans):
            continue
        n += 1
        layers.append({"id": f"auto_flash{n}", "type": "transition", "start": round(max(0.0, p["start"] - 0.12), 3), "end": round(min(dur, p["start"] + 0.28), 3), "x": W / 2, "y": H / 2, "z": 95,
                       "parallax": 0, "enter": None, "exit": None, "anim": {}, "props": {"kind": "flash", "color": "#ffffff", "intensity": 0.5}})
    if n:
        added.append(f"{n} flash cut(s)")
    if len(tl.get("camera") or []) < 3:
        tl["camera"] = [[0.0, 1.0, 0, 0, 0, "inOutQuad"], [round(dur * 0.5, 2), 1.05, 20, -15, 0, "inOutQuad"], [round(dur, 2), 1.09, -20, -30, 0, "inOutQuad"]]
        added.append("slow camera push")
    return tl, added


def beat_sync(tl, audio, info, assets=None):
    """Music-driven video (no voice): pictures cut on the beat (about every 2 s or on every bar), the graphics of a scene move with their picture,
    other graphics and sounds snap to the nearest beat. Returns report lines."""
    W, dur = tl["width"], tl["duration"]
    layers = tl["layers"]
    beats = [b for b in info.get("beats", []) if b <= dur - 0.4]
    period = float(info.get("period") or 0.5)
    if len(beats) < 4:
        return []
    group = max(1, int(math.ceil(1.8 / period)))
    if group > 1 and group % 2:
        group += 1                                          # whole bars
    grid = beats[::group]
    pics = sorted([l for l in layers if _fullbleed(l, W) and not _is_ambient(l, dur)], key=lambda x: x["start"])
    old_starts = [p["start"] for p in pics]
    owner_of = {}
    for l in layers:
        if l["type"] in ("text", "counter", "icon", "shape", "line") and not _is_ambient(l, dur) and not _fullbleed(l, W):
            for k, st in enumerate(old_starts):
                if st - 0.05 <= l["start"] < (old_starts[k + 1] if k + 1 < len(old_starts) else 1e9):
                    owner_of[l["id"]] = k
    used, deltas, cut = set(), {}, 0
    for k, pic in enumerate(pics):
        if k == 0:
            deltas[k] = 0.0
            continue
        cand = [g for g in grid if g not in used]
        if not cand:
            deltas[k] = 0.0
            continue
        g = min(cand, key=lambda x: abs(x - pic["start"]))
        if abs(g - pic["start"]) <= max(1.2, group * period * 0.75):
            used.add(g)
            deltas[k] = g - pic["start"]
            if abs(deltas[k]) >= 0.08:
                cut += 1
        else:
            deltas[k] = 0.0
    for k, pic in enumerate(pics):
        d = deltas.get(k, 0.0)
        if d:
            pic["start"] = round(max(0.0, pic["start"] + d), 3)
    for l in layers:
        k = owner_of.get(l["id"])
        d = deltas.get(k, 0.0) if k is not None else 0.0
        if d:
            _shift(l, d)
    for a, b in zip(pics, pics[1:]):
        a["end"] = round(min(dur, max(a["start"] + 0.5, b["start"] + 0.3)), 3)
    snapped = 0
    for l in layers:
        if l["id"] in owner_of or l["type"] not in ("text", "counter", "icon", "shape", "line") or _is_ambient(l, dur) or _fullbleed(l, W) or l["start"] < 0.2:
            continue
        b = min(beats, key=lambda x: abs(x - l["start"]))
        if 0.02 < abs(b - l["start"]) <= 0.25:
            _shift(l, b - l["start"])
            snapped += 1
    for a in audio or []:
        try:
            s0 = float(a.get("start", 0))
        except Exception:  # noqa: BLE001
            continue
        if a.get("role", "sfx") != "sfx":
            continue
        hooked = next((k for k, st in enumerate(old_starts) if abs(s0 - st) <= 0.35 and deltas.get(k)), None)
        if hooked is not None:                              # a sound that belongs to a picture change moves with that picture
            a["start"] = round(max(0.0, s0 + deltas[hooked]), 3)
            continue
        pool = (info.get("hits") or []) if a.get("sfx") in ("hit", "riser") else beats
        if pool:
            b = min(pool, key=lambda x: abs(x - s0))
            if 0.02 < abs(b - s0) <= 0.2:
                a["start"] = round(b, 3)
    lines = []
    if cut or snapped:
        lines.append(f"{cut} picture cuts and {snapped} graphics were put on the beat ({info.get('bpm', 0):.0f} BPM)")
    left = _leave_with_picture(layers, W, dur)
    if left:
        lines.append(f"{left} graphics now leave with their picture")
    return lines


def finalize(tl, audio, words, voice_start, assets, beat_info=None, trim=True):
    """Returns (timeline, audio, report lines). Any failure returns the inputs unchanged.
    words = what is spoken (voice-over or the talking video); beat_info = the beat of the music (used when nobody speaks)."""
    keep_tl, keep_audio = copy.deepcopy(tl), copy.deepcopy(audio)
    try:
        if words:
            tl, audio, lines = sync(tl, audio, words, voice_start, assets, trim=trim)
        elif beat_info:
            lines = beat_sync(tl, audio, beat_info, assets)
        else:
            lines = []
            if _leave_with_picture(tl["layers"], tl["width"], tl["duration"]):
                lines.append("graphics now leave with their picture")
        tl, added = polish(tl)
        if added:
            lines.append("added: " + ", ".join(added))
        try:
            audio, snd = sound_design(tl, audio)
            if snd:
                lines.append("sounds added: " + ", ".join(f"{k} x{v}" for k, v in snd.items()))
        except Exception as e:  # noqa: BLE001
            print("sound design skipped:", e)
        try:
            fixed = declutter(tl, assets)
            if fixed:
                lines.append("no overlaps: " + "; ".join(fixed[:4]))
        except Exception as e:  # noqa: BLE001
            print("declutter skipped:", e)
        return tl, audio, lines
    except Exception as e:  # noqa: BLE001
        print("sync check skipped:", e)
        return keep_tl, keep_audio, []

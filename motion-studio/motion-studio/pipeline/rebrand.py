"""Rebrand department (the old reference department, grown up).
The client sends any motion video (a Coca-Cola ad, an Opay ad, a club promo ...) and wants the SAME design and motion for HIS brand.
  1. deep reading: Gemini watches the video and lists, scene by scene, every ELEMENT (text, logo, product, person, shape, footage) with its exact style,
     position, timing and animation, and marks which elements belong to the ORIGINAL brand;
  2. the creative director (chat): asks what the client wants (swap only some things, or rebrand for his brand), asks for a short brand summary,
     then writes a COPY PLAN (old -> new) like an award-winning copywriter: same job, same length, same rhythm, fresh words for his brand;
  3. a safety check: no word of the original brand may stay in the new brief or in the final timeline;
  4. the studio rebuilds every scene with the same elements, styles, positions and animation, with the new copy, colours, logo and pictures.
Used by reference.py (reading and chat) and run.py (instructions for the director, final scrub)."""
import json
import re

import gemini
import groq

DEEP_SYSTEM = ("You are a senior motion designer and brand strategist who takes a finished advert apart so that a studio can rebuild it EXACTLY for another brand. "
               "Be precise and complete. Write what you see, scene by scene, element by element. Answer ONLY with JSON.")
DEEP_SCHEMA = ('{"summary":"2 sentences: what the video is and how it feels","aspect":"9:16|16:9|1:1","pace":"slow|medium|fast","style":"look: colours, type, effects, camera in one sentence",'
               '"music":"none|calm|upbeat|cinematic...","voiceover":true,'
               '"brand":{"name":"the brand the video is made for, exactly as written/spoken","product":"the product or service","names":["every spelling, nickname or product name of the ORIGINAL brand seen or heard"],'
               '"slogans":["every slogan or tagline of the original brand"],"colors":[{"role":"main|accent|background|text","hex":"#rrggbb","name":"red"}],"logo":"how the logo looks, where it appears (scene numbers)","industry":"drink|bank|telecom|fashion|club|..."},'
               '"voice":{"text":"everything that is said, word for word, or empty","tone":"voice tone","words":60},'
               '"scenes":[{"start":0.0,"end":3.0,"what":"what is shown (kind of picture/shot)","motion":"camera move: direction, speed, amount","transition":"how it changes to the next","background":"colour/gradient/footage","effects":"particles, glow, shockwave, light leaks...",'
               '"text_on_screen":"all the text of this scene in one line, as written",'
               '"elements":[{"kind":"text|logo|product|person|footage|shape|icon|ui|number","content":"the exact words or what it is","role":"headline|subline|slogan|brand name|price|offer|date|schedule|address|phone|call to action|label|number|decor",'
               '"brand_specific":true,"position":"top-left|top|centre|lower third|bottom ...","size":"huge|big|medium|small","font":"bold sans caps | serif | script | handwriting | condensed ...","color":"#rrggbb or name",'
               '"animation":"how it enters, moves and leaves: e.g. letters slam in one by one from the left with a scale-up, 0.4 s, ease-out; then a light sweep","appears":0.2,"disappears":2.8}]}],'
               '"needs":{"pictures":6,"voice_script_words":60,"logo":true,"texts":["brand name","phone number"]},"notes":"anything else worth keeping the same (signature moves, rhythm, sound design)"}')


def deep_by_gemini(path, f, said, fact_text):
    video = open(path, "rb").read()
    if len(video) > 19 * 1024 * 1024:
        raise RuntimeError("video too big for Gemini inline")
    ans = gemini.parse_json(gemini.generate(fact_text + "Watch the video carefully (twice if needed) and fill this JSON. Scenes in order, times in seconds. List EVERY visible text and logo as an element.\n" + DEEP_SCHEMA,
                                            system=DEEP_SYSTEM, video=video, temperature=0.2, rounds=2))
    if not isinstance(ans, dict) or not isinstance(ans.get("scenes"), list) or not ans["scenes"]:
        raise RuntimeError("answer had no scenes")
    ans["deep"] = True
    return ans


# ---------------------------------------------------------------- what belongs to the original brand
def old_terms(spec):
    """The words of the ORIGINAL brand: names (hard: replaced by the studio itself), slogans and brand-specific texts (soft: reported)."""
    b = spec.get("brand") if isinstance(spec.get("brand"), dict) else {}
    names = [str(x).strip() for x in ([b.get("name")] + list(b.get("names") or [])) if x and len(str(x).strip()) >= 2]
    soft = [str(x).strip() for x in (b.get("slogans") or []) if x and len(str(x).strip()) >= 4]
    for sc in spec.get("scenes") or []:
        for el in sc.get("elements") or []:
            if isinstance(el, dict) and el.get("brand_specific") and el.get("kind") in ("text", "number") and 3 <= len(str(el.get("content", ""))) <= 60:
                soft.append(str(el["content"]).strip())
    uniq = lambda xs: list(dict.fromkeys(x for x in xs if x))  # noqa: E731
    return {"names": uniq(names), "texts": uniq(soft)}


def _found(term, text):
    pat = r"(?<![A-Za-z0-9])" + re.escape(term) + r"(?![A-Za-z0-9])"
    return re.search(pat, text, re.I) is not None


def leftovers(terms, text, allowed=()):
    """Which original-brand names or slogans are still written in this text (outside the allowed ones, e.g. a word that is also the new brand)."""
    low_allowed = [a.lower() for a in allowed if a]
    out = []
    for t in (terms.get("names") or []) + (terms.get("texts") or []):
        if any(t.lower() in a or a in t.lower() for a in low_allowed):
            continue
        if _found(t, text or ""):
            out.append(t)
    return out


def scrub(tl, terms, new_name, allowed=()):
    """Final safety net on the timeline: an original brand NAME inside a text is replaced by the new brand name; a leftover slogan/brand text is only reported.
    Returns (names replaced, slogans found)."""
    replaced, found = [], []
    names = [n for n in (terms.get("names") or []) if not any(n.lower() in (a or "").lower() or (a or "").lower() in n.lower() for a in allowed if a)]

    def walk(layers):
        for l in layers or []:
            p = l.get("props") or {}
            if isinstance(p.get("text"), str):
                s = p["text"]
                for n in names:
                    pat = re.compile(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", re.I)
                    if pat.search(s):
                        s = pat.sub(new_name.upper() if s.isupper() else new_name, s) if new_name else s
                        replaced.append(n)
                p["text"] = s
                for t in terms.get("texts") or []:
                    if _found(t, s) and t not in found:
                        found.append(t)
            if l.get("type") == "group":
                walk(p.get("children"))
    walk(tl.get("layers"))
    return replaced, found


# ---------------------------------------------------------------- the first message: what I found
def inventory_text(spec, level):
    b = spec.get("brand") if isinstance(spec.get("brand"), dict) else {}
    head = {"gemini": "✅ I watched your video and took it apart.", "groq": "✅ I read your video (backup reader, from sampled frames and speech).",
            "facts": "✅ Video saved. I could only measure it (cuts, length, colours), not look inside."}[level]
    lines = [head, ""]
    if b.get("name"):
        lines.append(f"It is an advert for {b['name']}" + (f" ({b['product']})" if b.get("product") else "") + f". {spec.get('summary', '')}")
    else:
        lines.append(str(spec.get("summary", "")))
    lines.append(f"Structure: {len(spec['scenes'])} scenes, {spec['duration']:.0f}s, {spec.get('aspect', '9:16')}, pace {spec.get('pace', '?')}.")
    texts = []
    for i, sc in enumerate(spec["scenes"][:30]):
        for el in sc.get("elements") or []:
            if isinstance(el, dict) and el.get("kind") == "text" and str(el.get("content", "")).strip():
                texts.append(f"scene {i + 1}: {str(el['content']).strip()[:50]}")
    if texts:
        lines.append("\nTexts I found:\n" + "\n".join("- " + t for t in texts[:14]) + ("\n- ..." if len(texts) > 14 else ""))
    if b.get("logo"):
        lines.append("Logo: " + str(b["logo"])[:140])
    if (spec.get("voice") or {}).get("text"):
        lines.append("Voice-over: yes (about %s words)." % (spec["voice"].get("words") or len(str(spec["voice"]["text"]).split())))
    lines.append("")
    lines.append("Now tell me what you want:\n"
                 "A) SWAP ONLY: tell me what to change (for example the name and the schedule) and everything else stays the same.\n"
                 "B) REBRAND: tell me your brand in a few lines (what you sell, who buys it, the mood, your slogan and colours if you have them, your country). I will write the new words for you, creatively, and show you the plan before I build.\n\n"
                 "Then send your logo and your product pictures as Files (one picture is enough, I make the other angles; if the other side looks different, send both sides).")
    return "\n".join(lines)[:3800]


# ---------------------------------------------------------------- the creative director (chat)
CHAT_SYSTEM = ("You are the creative director of an international motion-graphics ad studio, talking with a client on Telegram. The client sent a finished video he loves (the MODEL) and wants the SAME design and motion REBRANDED for HIS brand. "
               "You know the model only through the reading below (scenes, elements, texts, colours). Plain words, short paragraphs, no markdown symbols (no asterisks, no #). Be warm, sharp and professional. "
               "THE FLOW. "
               "1) If you do not yet know what he wants: ask him A) SWAP ONLY (he tells you what to change, everything else stays) or B) REBRAND (he gives a short brand summary: what he sells, who buys it, mood, slogan, colours, country and language). Ask only what is missing, never the same thing twice. "
               "2) When you know enough, write the COPY PLAN as a short numbered list. Every brand-specific text, voice line, picture and colour of the model gets one line: 'scene 2 headline: OLD -> NEW'. Keep it compact. "
               "3) Ask him to approve or to change items by number. Accept changes ('change 3 to ...') and update the plan. "
               "4) When he approves or sends /make, set ready true and write the brief. "
               "HOW TO WRITE THE NEW WORDS (this is your craft, be an award-winning copywriter): "
               "understand the JOB of each original line (hook, benefit, proof, offer, call to action, slogan) and write a NEW line that does the same job for HIS brand and product. "
               "Match the length and rhythm of the original (same number of words, within one or two) so it fits the same animation and timing. "
               "Use real insight about his product and his audience, one clear idea, vivid and specific words, no cliches, no literal translation of the original. "
               "Use the local flavour of his country when it fits his mood (local expressions, places, culture; pidgin or a local language only if the brand is local and informal, and only when it reads naturally). "
               "For the single most important line (the hero line or slogan) give TWO options and let him choose. "
               "Never reuse the original brand's slogan, name or trademarked phrases. Never invent facts: no prices, discounts, percentages, rankings, health claims, phone numbers or addresses unless he gave them; if a scene needs one (a price, a date, a phone number), ask for it. "
               "Colours: map the original brand colours to his brand colours (ask for his if you do not know them; if he has none, propose a palette that fits his mood). "
               "SWAP ONLY mode: change only what he listed; everything else of the model stays as read (same words, colours, motion). Tell him honestly that the studio rebuilds the video from the reading, so the original pictures are not reused: he sends his own pictures for the picture scenes, or the studio makes similar ones. "
               "Tell him once, briefly, that the studio recreates the structure and style with his own assets and never reuses the other creator's footage, music or logo, which keeps his advert safe to publish. "
               "Product pictures: one clear photo is enough, the studio makes the other angles by itself and keeps the product identical; if the other side has a different look or logo, he should send both sides. "
               "You cannot open links or websites: if he shares a link say it is noted and the studio reads it when the video is made. "
               "THE BRIEF (only when ready): a complete prompt for the studio in its script format: first a line about the video (length follows the voice-over, vertical or the model's shape, the new brand, the mood, the look and colours), then VOICE-OVER (written in full, simple natural English, a hook first, about the same number of words as the model's voice-over, or none if the model has none), CAPTIONS, BACKGROUND, then every scene in the SAME order and with the SAME structure as the model: SCENE n, VOICE, IMAGE PROMPT or ANIMATION (the same elements, positions, styles and animation as the model, with the new copy, colours, logo and his pictures), MOTION (the same camera move), LABEL (the exact new text, the same style and position), SOUND (sounds that fit the mood: a hit only for bold, impact adverts, soft sounds for calm ones). "
               "In the brief, never write the original brand's name, slogan or words. "
               "Reply with JSON only.")
CHAT_SCHEMA = ('{"reply":"what you say to the client (max 3000 characters)","agreed":{"mode":"swap|rebrand|unknown","brand_from":"","brand_to":"","product":"","brand_summary":{"what":"","audience":"","tone":"","slogan":"","colors":"","country":""},'
               '"swaps":[{"old":"","new":""}],"copy_plan":[{"n":1,"scene":1,"role":"headline","old":"","new":"","why":""}],"colors":{"from":["#hex"],"to":["#hex"]},'
               '"changes":["each change the client asked for"],"keep":["what must stay the same"],"voice_over":"the new voice-over in full, or empty","extra":"anything else that matters"},'
               '"needs":{"items":["specific things to send"]},"plan_shown":true,"ready":true,'
               '"brief":"ONLY when ready (the plan is approved or the client sent /make) and brand and product are known: the complete studio prompt described above. Otherwise empty."}')


def _agreed(rf):
    return (rf.get("spec") or {}).get("agreed") or {}


def _spec_view(spec):
    keep = ("summary", "duration", "aspect", "pace", "style", "music", "voiceover", "brand", "voice", "scenes", "needs", "notes")
    view = {k: spec.get(k) for k in keep}
    return json.dumps(view, separators=(",", ":"), ensure_ascii=False)[:14000]


def _ask_ai(prompt, system, temperature=0.5):
    err = ""
    if gemini.available():
        try:
            return gemini.parse_json(gemini.generate(prompt, system=system, temperature=temperature, rounds=2)), err
        except Exception as e:  # noqa: BLE001
            err = "Gemini: " + str(e)[:100]
            print("::warning::rebrand chat by Gemini failed:", err)
    try:
        return groq.parse_json(groq.chat([{"role": "system", "content": system}, {"role": "user", "content": prompt}], temperature=temperature, max_tokens=6000, reasoning="medium")), err
    except Exception as e:  # noqa: BLE001
        err += " Groq: " + str(e)[:100]
        print("::warning::rebrand chat by Groq failed:", str(e)[:100])
    return None, err


def chat_turn(rf, user_text):
    """One turn. Returns (reply text, merged agreed dict, brief text or '')."""
    spec = rf.get("spec") or {}
    hist = rf.get("history") or []
    convo = "\n".join(f"{'CLIENT' if h.get('who') == 'c' else 'YOU'}: {h.get('text', '')}" for h in hist[-16:])
    prompt = (f"READING OF THE MODEL VIDEO:\n{_spec_view(spec)}\n\nWHAT IS AGREED SO FAR:\n{json.dumps(_agreed(rf), separators=(',', ':'), ensure_ascii=False)[:6000]}\n\n"
              f"CONVERSATION SO FAR:\n{convo or '(nothing yet)'}\n\nNEW MESSAGE FROM THE CLIENT:\n{user_text}\n\nAnswer with this JSON (update \"agreed\" with everything known so far, keep earlier facts):\n{CHAT_SCHEMA}")
    ans, _err = _ask_ai(prompt, CHAT_SYSTEM)
    if not isinstance(ans, dict) or not str(ans.get("reply", "")).strip():
        return None, _agreed(rf), ""
    ag = ans.get("agreed") if isinstance(ans.get("agreed"), dict) else {}
    old = _agreed(rf)
    merged = {**old, **{k: v for k, v in ag.items() if v not in (None, "", [], {})}}
    m = str(merged.get("mode", "")).lower()
    merged["mode"] = m if m in ("swap", "rebrand", "exact", "changes") else "unknown"
    merged["brand"] = merged.get("brand_to") or merged.get("brand") or ""
    needs = ans.get("needs") if isinstance(ans.get("needs"), dict) else {}
    if needs:
        merged["needs"] = needs
    ready = bool(ans.get("ready")) and merged["mode"] != "unknown" and (merged.get("product") or merged.get("brand_to") or merged.get("swaps"))
    brief = str(ans.get("brief") or "").strip() if ready else ""
    reply = str(ans["reply"]).strip()[:3800]
    if brief:
        brief, note = _guard(spec, merged, brief)
        merged["brief"] = brief
        if note:
            reply = (reply + "\n\n" + note)[:3900]
    return reply, merged, brief


def _guard(spec, agreed, brief):
    """The brief must not carry the original brand. One repair round by the AI, then a plain substitution of the name; slogans left over are reported to the client."""
    terms = old_terms(spec)
    new = str(agreed.get("brand_to") or agreed.get("brand") or "")
    allowed = [new] + [str(s.get("new", "")) for s in (agreed.get("swaps") or []) if isinstance(s, dict)]
    if agreed.get("mode") == "swap":                                  # swap only: the original words stay, except the ones the client listed
        terms = {"names": [s.get("old") for s in (agreed.get("swaps") or []) if isinstance(s, dict) and s.get("old")], "texts": []}
    left = leftovers(terms, brief, allowed)
    if not left:
        return brief, ""
    ans, _e = _ask_ai("This studio brief still contains words of the ORIGINAL brand: " + ", ".join(left) + ".\nRewrite the brief completely WITHOUT them (use the new brand, new words that do the same job). Keep everything else.\n\nBRIEF:\n" + brief +
                      '\n\nAnswer with JSON: {"brief":"..."}', "You fix studio briefs. Reply with JSON only.", temperature=0.3)
    fixed = str((ans or {}).get("brief") or "").strip() if isinstance(ans, dict) else ""
    if fixed and not leftovers(terms, fixed, allowed):
        return fixed, ""
    out = fixed or brief
    for n in terms.get("names") or []:
        if new and not any(n.lower() in a.lower() for a in allowed if a):
            out = re.sub(r"(?<![A-Za-z0-9])" + re.escape(n) + r"(?![A-Za-z0-9])", new, out, flags=re.I)
    rest = leftovers(terms, out, allowed)
    return out, ("⚠️ Check these words from the original: " + ", ".join(rest) + ". Tell me what to write instead.") if rest else ""


# ---------------------------------------------------------------- instructions for the director
def extra_text(ref):
    """The rebrand instructions for the studio's director: every scene's elements with their exact style and animation; the original brand's own words are never shown, only what replaces them."""
    ag = ref.get("agreed") or {}
    mode = str(ag.get("mode", "unknown")).lower()
    new = str(ag.get("brand_to") or ag.get("brand") or "the client's brand")
    plan = {}
    for p in ag.get("copy_plan") or []:
        if isinstance(p, dict) and p.get("scene") is not None:
            plan.setdefault(int(p["scene"]) if str(p["scene"]).isdigit() else p["scene"], []).append(p)
    swaps = {str(s.get("old", "")).lower(): s.get("new", "") for s in (ag.get("swaps") or []) if isinstance(s, dict)}
    out = (f"REBRAND OF A MODEL VIDEO (the client loves its design): build the new video for {new} as an EXACT rebuild of the model: the same {len(ref['scenes'])} scenes in the same order, the same timing (within a quarter of a second; if the voice-over needs a different total length, scale all scene times in the same proportion), "
           "the same elements in the same positions and sizes, the same fonts and text styles, the same colours roles, the same text and object animation, the same camera moves, the same transitions and effects. Only the CONTENT changes: the words, the logo, the pictures, the brand colours. ")
    if mode == "swap":
        out += "SWAP ONLY: change nothing except the swaps listed below; all other text, colours and motion stay as described.\n"
        if swaps:
            out += "SWAPS:\n" + "\n".join(f"  - {o} -> {n}" for o, n in swaps.items()) + "\n"
    else:
        out += f"Every text, logo, picture and colour that belonged to the original brand is replaced by {new}'s (copy plan below). Never write the original brand's name, slogan or words anywhere.\n"
    if (ag.get("brand_summary") or {}):
        out += "THE NEW BRAND: " + "; ".join(f"{k}: {v}" for k, v in ag["brand_summary"].items() if v) + "\n"
    col = ag.get("colors") or {}
    if col.get("to"):
        out += f"COLOURS: replace the original brand colours {', '.join(map(str, col.get('from') or []))} by {', '.join(map(str, col['to']))} (same roles: main, accent, background, text).\n"
    elif isinstance(ref.get("brand"), dict) and ref["brand"].get("colors") and mode != "swap":
        out += "The original brand's colours must not be used as the brand colours: use the new brand's own colours (from its logo and pictures).\n"
    if ag.get("voice_over"):
        out += "NEW VOICE-OVER (read exactly): " + str(ag["voice_over"])[:1500] + "\n"
    if ag.get("changes"):
        out += "CHANGES THE CLIENT ASKED FOR:\n" + "\n".join(f"  - {c}" for c in ag["changes"][:12]) + "\n"
    if ag.get("keep"):
        out += "KEEP THE SAME: " + "; ".join(str(k) for k in ag["keep"][:12]) + "\n"
    lines = []
    for i, sc in enumerate(ref["scenes"][:30]):
        n = i + 1
        row = f"  {n}. {sc.get('start', 0):.1f}-{sc.get('end', 0):.1f}s | shows: {sc.get('what', '')} | background: {sc.get('background', '')} | motion: {sc.get('motion', '')} | effects: {sc.get('effects', '')} | change: {sc.get('transition', '')}"
        els = []
        for el in sc.get("elements") or []:
            if not isinstance(el, dict):
                continue
            style = f"{el.get('size', '')} {el.get('font', '')} {el.get('color', '')}, at {el.get('position', '')}, {el.get('animation', '')}, {el.get('appears', '')}-{el.get('disappears', '')}s".strip()
            c = str(el.get("content", ""))
            if mode == "swap":
                c = swaps.get(c.lower(), c)
                what = f"'{c}'" if el.get("kind") in ("text", "number") else str(c)
            elif el.get("brand_specific") or el.get("kind") in ("logo", "product", "footage", "person"):
                rep = next((p.get("new") for p in plan.get(n, []) if p.get("role") == el.get("role")), None) or next((p.get("new") for p in plan.get(n, [])), None)
                if el.get("kind") == "logo":
                    what = f"the new brand's logo (replaces the original's logo)"
                elif el.get("kind") in ("product", "footage", "person"):
                    what = f"the client's own {el.get('kind')} picture (a product shot of the client's product; NOT the original's)"
                else:
                    what = f"NEW TEXT '{rep}'" if rep else f"new {el.get('role', 'text')} written for the new brand, same length"
            else:
                what = f"'{c}'" if el.get("kind") in ("text", "number") else str(c)
            els.append(f"       - {el.get('kind', '')} ({el.get('role', '')}): {what} | {style}")
        lines.append(row + ("\n" + "\n".join(els) if els else ""))
    return out + "MODEL SCENES (rebuild each exactly):\n" + "\n".join(lines) + "\n"

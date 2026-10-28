"""Pronunciation help for the generated voice-over.
Only the VOICE hears the sound-spellings. Captions and the screen text keep the real spelling.
1) a fixed list of Yoruba / Igbo names and words (the same list the movie factory uses; add to it any time),
2) names and non-English words found automatically in THIS script by one Groq question (the fixed list always wins).
If the Groq question fails, only the fixed list is used. Nothing here can stop a video."""
import difflib
import re

import groq

PRONOUNCE = {
    "Ile-Ife": "Ee-leh Ee-feh", "Ife": "Ee-feh", "Moremi": "Moh-reh-mee",
    "Ajasoro": "Ah-jah-soh-roh", "Ugbo": "Oog-boh", "Esimirin": "Eh-see-mee-reen",
    "Oluorogbo": "Oh-loo-oh-roh-gboh", "Oduduwa": "Oh-doo-doo-wah", "Oranmiyan": "Oh-rahn-mee-yahn",
    "Ogun": "Oh-goon", "Sango": "Shahn-goh", "Oya": "Oh-yah",
    "Yemoja": "Yeh-moh-jah", "Osun": "Oh-shoon", "Olokun": "Oh-loh-koon",
    "Esu": "Eh-shoo", "Orunmila": "Oh-roon-mee-lah", "Olodumare": "Oh-loh-doo-mah-reh",
    "Alaafin": "Ah-lah-ah-feen", "Ooni": "Oh-oh-nee", "Babalawo": "Bah-bah-lah-woh",
    "Oluwaseun": "Oh-loo-wah-sheh-oon", "Adebayo": "Ah-deh-bah-yoh", "Adewale": "Ah-deh-wah-leh",
    "Ayodele": "Ah-yoh-deh-leh", "Babatunde": "Bah-bah-toon-deh", "Folake": "Foh-lah-keh",
    "Funmilayo": "Foon-mee-lah-yoh", "Yetunde": "Yeh-toon-deh", "Titilayo": "Tee-tee-lah-yoh",
    "Abeni": "Ah-beh-nee", "Kemi": "Keh-mee", "Tunde": "Toon-deh",
    "Femi": "Feh-mee", "Bisi": "Bee-see", "Sade": "Shah-deh",
    "Kunle": "Koon-leh", "Wale": "Wah-leh", "Segun": "Seh-goon",
    "Dayo": "Dah-yoh", "Toyin": "Toh-yeen", "Iyabo": "Ee-yah-boh",
    "Ngozi": "N-goh-zee", "Chioma": "Chee-oh-mah", "Emeka": "Eh-meh-kah",
    "Chidi": "Chee-dee", "Ifeoma": "Ee-feh-oh-mah", "Nneka": "N-neh-kah",
    "Adaeze": "Ah-dah-eh-zeh", "Okoro": "Oh-koh-roh", "Chukwu": "Choo-kwoo",
}

LAST = {"changed": False}


def _dynamic(text):
    """Ask Groq how to spell the hard names of this script so a Nigerian-English voice says them right."""
    try:
        msgs = [
            {"role": "system", "content": "You help a text-to-speech voice (Nigerian English) say names correctly. Reply with ONE JSON object only."},
            {"role": "user", "content": "Read this voice-over script. List ONLY proper names (people, places, brands) and non-English words (Yoruba, Igbo, Hausa, Pidgin, Arabic, French) that a voice may say wrongly. Do NOT list normal English words or common English place names. For each, give a sound-spelling in short hyphenated syllables, for example {\"Funmilayo\": \"Foon-mee-lah-yoh\"}. Keep each key exactly as written in the script. If nothing is hard, reply {}.\n\nSCRIPT:\n" + text[:3000]},
        ]
        out = groq.parse_json(groq.chat(msgs, temperature=0.1, max_tokens=900, tries=2, reasoning="low"))
        res = {}
        for k, v in (out or {}).items():
            if isinstance(v, str) and re.match(r"^[A-Za-z][A-Za-z' .\-]{2,39}$", str(k)) and re.match(r"^[A-Za-z][A-Za-z' \-]{1,60}$", v.strip()) and str(k).lower() in text.lower():
                res[str(k).strip()] = v.strip()
        return res
    except Exception as e:  # noqa: BLE001
        print("pronunciation helper skipped (" + str(e)[:80] + ")")
        return {}


def apply(text):
    """The text the voice should read. Sets LAST['changed'] when any word was replaced."""
    text = str(text or "")
    table = dict(_dynamic(text))
    table.update(PRONOUNCE)                     # the fixed list wins
    keys = sorted(table, key=len, reverse=True)
    lower = {k.lower(): v for k, v in table.items()}
    pat = re.compile(r"(?<![A-Za-z])(" + "|".join(re.escape(k) for k in keys) + r")(?![A-Za-z])", re.I)
    out = pat.sub(lambda m: lower.get(m.group(1).lower(), m.group(1)), text)
    LAST["changed"] = out != text
    return out


def fix_words_to_text(words, text):
    """The speech check hears the sound-spellings. Put the real spelling back in the caption words, keeping the timing."""
    try:
        orig = str(text or "").split()
        norm = lambda t: re.sub(r"[^a-z0-9]", "", str(t).lower())
        a = [norm(x["w"]) for x in words]
        b = [norm(t) for t in orig]
        out = []
        for tag, i1, i2, j1, j2 in difflib.SequenceMatcher(None, a, b, autojunk=False).get_opcodes():
            if tag == "equal":
                out += [dict(x) for x in words[i1:i2]]
            elif i2 > i1 and j2 > j1:
                span0, span1 = float(words[i1]["s"]), float(words[i2 - 1]["e"])
                toks = orig[j1:j2]
                tot = float(sum(len(t) + 1 for t in toks))
                t0 = span0
                for t in toks:
                    t1 = t0 + (span1 - span0) * (len(t) + 1) / tot
                    out.append({"w": t, "s": round(t0, 3), "e": round(t1, 3)})
                    t0 = t1
            elif i2 > i1:
                out += [dict(x) for x in words[i1:i2]]
        return out or words
    except Exception:  # noqa: BLE001
        return words

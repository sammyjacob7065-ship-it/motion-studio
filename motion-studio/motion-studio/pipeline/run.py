"""Motion Studio job runner. Started by GitHub Actions with a job id.

Reads motion/jobs/<job>/brief.json from Supabase, makes the video, and reports every stage to Telegram.
"""
import base64
import io
import json
import os
import re
import sys
import traceback

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import assets as A  # noqa: E402
import checker  # noqa: E402
import director  # noqa: E402
import groq  # noqa: E402
import imagegen  # noqa: E402
import mix  # noqa: E402
import pronounce  # noqa: E402
import render  # noqa: E402
import timeline as T  # noqa: E402
import voice  # noqa: E402
from common import Cancelled, env  # noqa: E402
from monitor import Monitor  # noqa: E402
from sb import Store  # noqa: E402
from tg import Telegram  # noqa: E402
from PIL import Image  # noqa: E402

VOICE_START = 0.5


def b64_jpeg(path, width=640):
    im = Image.open(path).convert("RGB")
    im.thumbnail((width, width * 2))
    buf = io.BytesIO()
    im.save(buf, "JPEG", quality=80)
    return base64.b64encode(buf.getvalue()).decode()


def pick_voice_and_music(registry, paths):
    audios = [n for n, a in registry.items() if a.get("kind") == "audio"]
    hint_v = [n for n in audios if any(k in n.lower() for k in ("voice", "vo_", "_vo", "narr", "speech", "record"))]
    hint_m = [n for n in audios if any(k in n.lower() for k in ("music", "song", "track", "beat", "bg", "background"))]
    v = (hint_v or [n for n in audios if n not in hint_m] or [None])[0]
    m = [n for n in audios if n != v and (n in hint_m or True)]
    return v, m


def fallback_words(text, dur):
    ws = text.split()
    if not ws or dur <= 0:
        return []
    step = dur / len(ws)
    return [{"w": w, "s": round(i * step, 3), "e": round((i + 1) * step - 0.02, 3)} for i, w in enumerate(ws)]


def _ck(store, job, name):
    """A saved step of this job (None when it does not exist yet). Used by /resume so a failed job continues where it stopped."""
    try:
        return store.get_json(f"motion/jobs/{job}/ckpt/{name}.json")
    except Exception:  # noqa: BLE001
        return None


def _ck_save(store, job, name, obj):
    try:
        store.put_json(f"motion/jobs/{job}/ckpt/{name}.json", obj)
    except Exception as e:  # noqa: BLE001
        print("checkpoint not saved:", name, str(e)[:80])


def _ck_file(store, job, name, path):
    try:
        store.upload_file(f"motion/jobs/{job}/ckpt/files/{name}", path)
        return True
    except Exception as e:  # noqa: BLE001
        print("checkpoint file not saved:", name, str(e)[:80])
        return False


def main(job):
    store = Store()
    voice.wake()                       # wake the free voice server now, while the director works
    brief = store.get_json(f"motion/jobs/{job}/brief.json")
    if not brief:
        raise SystemExit(f"No brief found for job {job}")
    tg = Telegram(brief["chat_id"])
    mon = Monitor(store, tg, job)
    work = os.path.abspath(os.path.join("work", job))
    os.makedirs(work, exist_ok=True)
    adir = os.path.join(work, "assets")
    os.makedirs(adir, exist_ok=True)
    stage = "start"
    try:
        # ---- 1. files
        stage = "Checking your files"
        mon.stage("brief", f"{len(brief['assets'])} files, {len(brief.get('urls', []))} links")
        mon.stage("assets")
        registry, paths, notes = {}, {}, []
        for a in brief["assets"]:
            dest = os.path.join(adir, os.path.basename(a["path"]))
            store.download(a["path"], dest)
            final, info, flags = A.analyze(dest, work)
            name = os.path.basename(final)
            if info.get("kind") in ("image", "video", "audio"):
                info["flags"] = flags
                info["origin"] = "supplied by client"
                registry[name], paths[name] = info, final
                notes += [f"{name}: {f}" for f in flags]
            else:
                notes.append(f"{os.path.basename(a['path'])}: not a picture, video or audio file, ignored")
        for i, u in enumerate(brief.get("urls", [])):
            p, note = A.download_url(u, adir, i + 1)
            if not p:
                notes.append(note)
                continue
            final, info, flags = A.analyze(p, work)
            if info.get("kind") in ("image", "video", "audio"):
                name = os.path.basename(final)
                info["flags"], info["origin"] = flags, "from client link"
                registry[name], paths[name] = info, final
        if registry:
            A.describe_images(registry, paths, groq.chat)
        mon.done_stage("assets", f"{len(registry)} usable" + (f", {len(notes)} warnings" if notes else ""))
        if notes:
            tg.send("⚠️ File check:\n" + "\n".join("- " + n for n in notes[:12]))

        # ---- 2. plan
        stage = "Director planning"
        mon.stage("plan")
        ck_plan = _ck(store, job, "plan")
        resumed = []
        if ck_plan and ck_plan.get("plan"):
            plan = ck_plan["plan"]
            resumed.append("plan")
        else:
            plan = director.plan(brief["prompt"], registry)
            _ck_save(store, job, "plan", {"plan": plan})
        size = T.size_for(plan.get("aspect"))
        mon.done_stage("plan", f"{plan.get('aspect', '9:16')}, {len(plan.get('requirements', []))} instructions")
        if brief.get("plan_first"):
            tg.send("🧠 Plan (you asked to see it first)\n\n" + str(plan.get("concept", "")) + "\n\nI will do:\n" + "\n".join(f"{i + 1}. {r}" for i, r in enumerate(plan.get("requirements", []))[:20]) + f"\n\nFormat {plan.get('aspect')}" + "\n\nSend /go to build it, or /cancel to stop. (I wait 30 minutes.)")
            mon.write_status(state="running", stage="Waiting for your /go")
            if not mon.wait_approval(30):
                raise RuntimeError("No answer after 30 minutes, job stopped. Send your prompt again when ready.")

        # ---- 3. stock pictures
        pic_report = []
        if _ck(store, job, "pictures") is None:
            try:
                auto = director.image_department(brief["prompt"], plan, len([1 for a in registry.values() if a.get("kind") == "image" and not a.get("alpha")]))
                if auto:
                    plan["stock"] = list(plan.get("stock") or []) + auto
                    mon.note("stock", f"picture department: {len(auto)} pictures to make")
            except Exception as e:  # noqa: BLE001
                print("picture department skipped:", e)
        ck_stock = _ck(store, job, "pictures")
        if ck_stock is not None:
            for nm, info in (ck_stock.get("entries") or {}).items():
                try:
                    dst = os.path.join(adir, nm)
                    store.download(f"motion/jobs/{job}/ckpt/files/{nm}", dst)
                    registry[nm], paths[nm] = info, dst
                except Exception as e:  # noqa: BLE001
                    notes.append(f"saved picture {nm} could not be reloaded ({str(e)[:50]})")
            resumed.append("pictures")
        else:
            before = set(registry)
            if plan.get("stock"):
                stage = "Getting pictures"
                mon.stage("stock")
                got = 0
                spoken = str((plan.get("voiceover") or {}).get("text", "")) or str(brief.get("prompt", ""))
                for req in plan["stock"][:10]:
                    if any(w in str(req.get("query", "")).lower() for w in ("music", "song", "audio", "sound effect", "soundtrack")):
                        continue
                    p, how = None, "stock picture"
                    if str(req.get("kind", "image")) != "video":
                        said = str(req.get("phrase") or "")
                        ai_prompt = str(req.get("prompt") or "").strip() or (str(req.get("query", "")) + (", " + said if said else ""))
                        p, prov = imagegen.generate(ai_prompt, plan.get("aspect"), adir, re.sub(r"[^A-Za-z0-9_-]", "", str(req.get("id", "pic"))) or "pic", exact=bool(req.get("exact")))
                        if p:
                            how = f"AI picture ({prov})"
                        else:
                            notes.append(f"AI picture '{req.get('query')}': {prov[:160]}")
                            pic_report.append(f"{req.get('query')}: AI failed")
                    if not p:
                        p, note = A.fetch_stock(req, adir, plan.get("aspect"))
                        if not p:
                            notes.append(f"stock '{req.get('query')}': {note}")
                            pic_report.append(f"{req.get('query')}: NO PICTURE")
                            continue
                    final, info, flags = A.analyze(p, work)
                    name = os.path.basename(final)
                    info["flags"], info["origin"] = flags, f"{how} for: {req.get('query')}"
                    pic_report.append(how.replace("AI picture ", "").strip("()") if how != "stock picture" else "stock")
                    info["query"] = str(req.get("query", ""))
                    info["phrase"] = str(req.get("phrase") or "") or checker.phrase_for(req.get("query", ""), spoken)
                    registry[name], paths[name] = info, final
                    got += 1
                mon.done_stage("stock", f"{got} of {len(plan['stock'])}")
                if got < len(plan["stock"]):
                    tg.send("⚠️ Some stock pictures could not be found:\n" + "\n".join("- " + n for n in notes if n.startswith("stock"))[:600])
            for nm in plan.get("cutout", [])[:4]:
                key = next((k for k in registry if k == nm or k.startswith(os.path.splitext(nm)[0])), None)
                if key and registry[key]["kind"] == "image":
                    c = A.cutout(paths[key])
                    if c:
                        n2 = os.path.basename(c)
                        registry[n2] = {**registry[key], "alpha": True, "origin": "background removed from " + key}
                        paths[n2] = c
            try:
                made = {n: registry[n] for n in registry if n not in before}
                for n in list(made):
                    if not _ck_file(store, job, n, paths[n]):
                        made.pop(n)
                _ck_save(store, job, "pictures", {"entries": json.loads(json.dumps(made, default=str))})
            except Exception as e:  # noqa: BLE001
                print("pictures checkpoint skipped:", e)

        # ---- 4. voice
        stage = "Voice and timing"
        mon.stage("voice")
        vo = plan.get("voiceover", {}) or {}
        voice_path, words, voice_len, music_names = None, [], 0.0, []
        video_words = {}
        ck_voice = _ck(store, job, "voice")
        if ck_voice is not None:
            words, voice_len, music_names, video_words = ck_voice.get("words", []), float(ck_voice.get("voice_len", 0)), ck_voice.get("music_names", []), ck_voice.get("video_words", {})
            try:
                if ck_voice.get("how") == "generated":
                    voice_path = store.download(f"motion/jobs/{job}/ckpt/files/voice.mp3", os.path.join(work, "voice.mp3"))
                elif ck_voice.get("how") == "supplied":
                    sv, _sm = pick_voice_and_music(registry, paths)
                    voice_path = paths.get(sv)
                resumed.append("voice")
            except Exception as e:  # noqa: BLE001
                ck_voice = None
                words, voice_len, music_names, video_words, voice_path = [], 0.0, [], {}, None
        if ck_voice is None:
            sup_voice, sup_music = pick_voice_and_music(registry, paths)
            if vo.get("mode") == "supplied" and sup_voice:
                voice_path = paths[sup_voice]
                music_names = sup_music
            elif vo.get("mode") == "generate" and vo.get("text"):
                voice_path = voice.generate(vo["text"], os.path.join(work, "voice.mp3"), work)
            try:
                want = float(plan.get("duration") or 0)
                got = A.duration_of(voice_path)
                if want >= 10 and got > want - 2.0:                    # the video must end when the brief says: speak a little faster
                    fast = min(1.3, got / max(5.0, want - 2.0))
                    if fast > 1.03:
                        voice_path = voice.generate(vo["text"], os.path.join(work, "voice.mp3"), work, speed=round(fast, 2))
                        notes.append(f"voice sped up x{fast:.2f} to fit {want:.0f} s" + (" (still longer: shorten the script a little)" if A.duration_of(voice_path) > want - 1.0 else ""))
            except Exception as e:  # noqa: BLE001
                print("voice speed fit skipped:", e)
                music_names = [n for n in (sup_voice and [sup_voice] or []) + sup_music]
            else:
                music_names = [n for n in registry if registry[n].get("kind") == "audio"]
            if voice_path:
                voice_len = A.duration_of(voice_path)
                try:
                    words, _txt, _d = voice.words_for(voice_path)
                    if vo.get("mode") == "generate" and pronounce.LAST["changed"]:
                        words = pronounce.fix_words_to_text(words, vo.get("text", ""))      # captions keep the real spelling of names
                except Exception as e:  # noqa: BLE001
                    words = fallback_words(vo.get("text", ""), voice_len)
                    notes.append("word timing guessed (speech check failed: " + str(e)[:60] + ")")
            video_words = {}
            if plan.get("transcribe_videos") or plan.get("captions"):
                for n, a in registry.items():
                    if a.get("kind") == "video" and a.get("audio"):
                        try:
                            ap = os.path.join(os.path.dirname(paths[n]), a["audio"])
                            small = os.path.join(work, n + ".speech.mp3")
                            import subprocess
                            subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", ap, "-ac", "1", "-ar", "16000", "-b:a", "48k", small], check=True)
                            video_words[n], _t, _d = voice.words_for(small)
                        except Exception as e:  # noqa: BLE001
                            notes.append(f"{n}: could not read the speech ({str(e)[:60]})")
            try:
                how = "generated" if (vo.get("mode") == "generate" and voice_path) else ("supplied" if (voice_path and vo.get("mode") == "supplied") else None)
                if how != "generated" or _ck_file(store, job, "voice.mp3", voice_path):
                    _ck_save(store, job, "voice", {"how": how, "words": words, "voice_len": voice_len, "music_names": music_names, "video_words": video_words})
            except Exception as e:  # noqa: BLE001
                print("voice checkpoint skipped:", e)
        mon.done_stage("voice", f"{voice_len:.1f}s voice, {len(words)} words" if voice_path else "no voice-over")

        # ---- 5. timeline
        stage = "Writing the timeline"
        mon.stage("timeline")
        sfx_files = mix.make_sfx(os.path.join(work, "sfx"))
        min_dur = (VOICE_START + voice_len) if voice_path else None
        director.PART_HOOK["load"] = lambda k: _ck(store, job, f"part{k}")
        director.PART_HOOK["save"] = lambda k, obj: _ck_save(store, job, f"part{k}", obj)
        ck_tl = _ck(store, job, "timeline")
        if ck_tl and ck_tl.get("raw_tl"):
            raw_tl, raw_audio, dnotes, user_msg = ck_tl["raw_tl"], ck_tl.get("raw_audio"), ck_tl.get("dnotes"), ck_tl.get("user_msg", "")
            tl, warns = T.normalize(raw_tl, registry, voice_len=(VOICE_START + voice_len) if voice_path else None)
            resumed.append("timeline")
        else:
            (raw_tl, raw_audio, dnotes), user_msg = director.timeline(brief["prompt"], plan, registry, words, VOICE_START, size, mix.SFX_NAMES, min_duration=min_dur)
            raw_tl.setdefault("aspect", plan.get("aspect", "9:16"))
            tl, warns = T.normalize(raw_tl, registry, voice_len=(VOICE_START + voice_len) if voice_path else None)
            problems = warns + T.check_layout(tl, registry)
            for _ in range(2):
                if not problems:
                    break
                raw_tl, raw_audio, dn2 = director.repair(raw_tl, raw_audio, problems, user_msg)
                raw_tl.setdefault("aspect", plan.get("aspect", "9:16"))
                tl, warns = T.normalize(raw_tl, registry, voice_len=(VOICE_START + voice_len) if voice_path else None)
                problems = warns + T.check_layout(tl, registry)
                dnotes = dn2 or dnotes
            _ck_save(store, job, "timeline", {"raw_tl": raw_tl, "raw_audio": raw_audio, "dnotes": dnotes, "user_msg": user_msg})

        def sync_check(t, a):
            if not voice_path:
                return t, a, []
            return checker.finalize(t, a, words, VOICE_START, registry)

        tl, raw_audio, sync_lines = sync_check(tl, raw_audio)
        mon.done_stage("timeline", f"{len(tl['layers'])} layers, {tl['duration']:.1f}s")
        if resumed:
            tg.send("♻️ Resuming this job: I reused the saved " + ", ".join(resumed) + " and continued from there.")

        def fill_captions(t):
            for l in t["layers"]:
                if l["type"] != "captions":
                    continue
                src = str(l["props"].get("words_from", "voice"))
                if src.startswith("video:"):
                    vn = src.split(":", 1)[1]
                    vw = video_words.get(vn) or []
                    vl = next((x for x in t["layers"] if x["type"] == "video" and x["props"].get("asset") == vn), None)
                    off = (vl["start"] - float(vl["props"].get("srcStart", 0))) if vl else float(l["props"].get("offset", 0))
                    l["props"]["words"] = [{"w": w["w"], "s": round(w["s"] + off, 3), "e": round(w["e"] + off, 3)} for w in vw]
                else:
                    l["props"]["words"] = [{"w": w["w"], "s": round(w["s"] + VOICE_START, 3), "e": round(w["e"] + VOICE_START, 3)} for w in words]
        fill_captions(tl)

        # ---- 6. review (preview frames, vision check)
        if env("REVIEW", "1") == "1":
            stage = "Checking the layout"
            mon.stage("review")
            try:
                props = render.prepare(tl, paths, work)
                n = 5
                times = [round(tl["duration"] * (i + 0.5) / n, 2) for i in range(n)]
                stills = render.render_stills(tl, props, times, os.path.join(work, "stills"))
                if stills:
                    issues = director.critique([b64_jpeg(p) for _t, p in stills], plan.get("requirements", []), [t for t, _p in stills])
                    major = [f"at {i.get('time', '?')}s: {i.get('what', '')}. Fix: {i.get('fix', '')}" for i in issues if str(i.get("severity")) == "major"]
                    if major:
                        mon.note("review", f"fixing {len(major)} problem(s)")
                        raw_tl, raw_audio, dn3 = director.repair(raw_tl, raw_audio, major, user_msg)
                        raw_tl.setdefault("aspect", plan.get("aspect", "9:16"))
                        tl2, warns2 = T.normalize(raw_tl, registry, voice_len=(VOICE_START + voice_len) if voice_path else None)
                        if not T.check_layout(tl2, registry) and len(tl2["layers"]) >= max(3, len(tl["layers"]) // 2):
                            tl, raw_audio, sync_lines = sync_check(tl2, raw_audio)
                            fill_captions(tl)
                            dnotes = dn3 or dnotes
                    mon.done_stage("review", "clean" if not major else f"{len(major)} fixed")
                else:
                    mon.done_stage("review", "skipped")
            except Exception as e:  # noqa: BLE001
                mon.done_stage("review", "skipped")
                print("review skipped:", e)

        # ---- 7. render
        stage = "Rendering"
        mon.stage("render")
        props = render.prepare(tl, paths, work)
        silent = os.path.join(work, "silent.mp4")
        render.render_video(tl, props, silent, on_progress=mon.progress)
        mon.done_stage("render", f"{tl['width']}x{tl['height']}")
        mon.check_cancel()

        # ---- 8. audio
        stage = "Mixing audio"
        mon.stage("audio")
        items = []
        if voice_path:
            items.append({"path": voice_path, "start": VOICE_START, "volume": 1.0, "role": "voice"})
        used_video_audio = set()
        for a in raw_audio or []:
            role = a.get("role", "sfx")
            vol = max(0.0, min(1.5, float(a.get("volume", 0.5 if role == "sfx" else 0.16))))
            st = max(0.0, float(a.get("start", 0)))
            if role == "sfx" and a.get("sfx") in sfx_files:
                items.append({"path": sfx_files[a["sfx"]], "start": st, "volume": vol, "role": "sfx"})
            elif role == "music" and a.get("asset") in paths and registry.get(a["asset"], {}).get("kind") == "audio":
                items.append({"path": paths[a["asset"]], "start": st, "volume": vol, "role": "music", "loop": True})
            elif role == "voice" and a.get("asset") in registry and registry[a["asset"]].get("audio"):
                ap = os.path.join(os.path.dirname(paths[a["asset"]]), registry[a["asset"]]["audio"])
                items.append({"path": ap, "start": st, "volume": 1.0, "role": "voice", "srcStart": float(a.get("srcStart", 0)), "dur": float(a.get("dur", 0)) or None})
                used_video_audio.add(a["asset"])
        if not voice_path:
            for l in tl["layers"]:
                n = l["props"].get("asset")
                if l["type"] == "video" and n in registry and registry[n].get("audio") and n not in used_video_audio:
                    ap = os.path.join(os.path.dirname(paths[n]), registry[n]["audio"])
                    items.append({"path": ap, "start": l["start"], "volume": 1.0, "role": "voice", "srcStart": float(l["props"].get("srcStart", 0)), "dur": l["end"] - l["start"]})
                    used_video_audio.add(n)
        if not any(i["role"] == "music" for i in items) and music_names:
            mn = music_names[0]
            if mn in paths and registry[mn].get("kind") == "audio" and mn != sup_voice:
                items.append({"path": paths[mn], "start": 0, "volume": 0.16, "role": "music", "loop": True})
        final = os.path.join(work, "final.mp4")
        mix.mix(silent, items, tl["duration"], final)
        mon.done_stage("audio", f"{len(items)} sounds")

        # ---- 9. deliver
        stage = "Delivering"
        mon.stage("deliver")
        store.upload_file(f"motion/jobs/{job}/final.mp4", final, "video/mp4")
        store.put_json(f"motion/jobs/{job}/timeline.json", {"timeline": tl, "audio": raw_audio, "plan": plan})
        url = store.signed_url(f"motion/jobs/{job}/final.mp4")
        facts = ""
        if voice_path:
            facts = f"A voice-over of {voice_len:.0f} seconds was generated with a male Nigerian voice and mixed into the video. It reads: " + str((plan.get("voiceover") or {}).get("text", ""))[:600] + ". Captions: " + ("a captions layer follows the voice." if any(l["type"] == "captions" for l in tl["layers"]) else "none.") + " Sound effects were mixed in at the audio events."
        cov = director.coverage(plan.get("requirements", []), tl, raw_audio, dnotes, facts)
        done = [c for c in cov if c["status"] == "done"]
        lines = [f"✅ Your video is ready ({tl['width']}x{tl['height']}, {tl['duration']:.0f}s)."]
        if cov:
            lines.append(f"{len(done)} of {len(cov)} instructions done.")
            for c in cov:
                if c["status"] != "done":
                    lines.append(f"• {c['status']}: {c['requirement'][:90]}" + (f" ({c['note'][:90]})" if c.get("note") else ""))
        if pic_report:
            ok = [x for x in pic_report if "NO PICTURE" not in x and "failed" not in x]
            lines.append(f"Pictures: {len(ok)} of {len(pic_report)} made" + (" (" + ", ".join(sorted(set(ok))) + ")" if ok else "") + (". Problems: " + "; ".join(x for x in pic_report if x not in ok)[:200] if len(ok) < len(pic_report) else ""))
        if sync_lines:
            lines.append("Synced to the voice: " + "; ".join(sync_lines)[:350])
        if dnotes:
            lines.append("Note: " + str(dnotes)[:300])
        size_mb = os.path.getsize(final) / 1e6
        if size_mb <= 48:
            try:
                tg.send_video(final, "\n".join(lines))
            except Exception:  # noqa: BLE001
                tg.send("\n".join(lines) + ("\nDownload: " + url if url else ""))
        else:
            tg.send("\n".join(lines) + f"\n\nThe file is {size_mb:.0f} MB, too big for Telegram. Download (7 days):\n{url}")
        mon.finish(url, "; ".join(lines[1:3]))
    except Cancelled:
        return
    except Exception as e:  # noqa: BLE001
        traceback.print_exc()
        mon.fail(stage, e)
        raise SystemExit(1)


if __name__ == "__main__":
    if len(sys.argv) < 2:
        raise SystemExit("usage: python pipeline/run.py <job_id>")
    main(sys.argv[1])

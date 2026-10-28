"""End-to-end test of the job runner with fake Supabase, Telegram, Groq, voice and renderer.
Run:  python tests/test_run.py      (needs ffmpeg; no internet, no keys)"""
import json
import os
import subprocess
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
os.environ.update({"SUPABASE_URL": "https://x.supabase.co", "SUPABASE_SERVICE_KEY": "k", "GROQ_API_KEY": "g", "MOTION_TG_TOKEN": "t", "REVIEW": "1"})
os.chdir(tempfile.mkdtemp())

import run  # noqa: E402
import sb  # noqa: E402
import tg  # noqa: E402
import groq  # noqa: E402
import voice  # noqa: E402
import render  # noqa: E402
from PIL import Image  # noqa: E402

STORE = {}
FILES = {}


class FakeStore:
    def __init__(self): pass
    def put_json(self, p, o): STORE[p] = json.loads(json.dumps(o))
    def get_json(self, p): return STORE.get(p)
    def download(self, p, dest):
        os.makedirs(os.path.dirname(dest), exist_ok=True)
        open(dest, "wb").write(FILES[p])
        return dest
    def upload_file(self, p, src, ct=""): STORE[p] = {"uploaded": os.path.getsize(src)}
    def signed_url(self, p, days=7): return "https://signed/" + p


SENT = []


class FakeTg:
    def __init__(self, chat): self.chat = chat
    def send(self, t): SENT.append(t); return len(SENT)
    def edit(self, i, t): SENT.append("EDIT " + t.replace("\n", " | ")); return True
    def send_video(self, p, c=""): SENT.append("VIDEO " + c.replace("\n", " | "))
    def send_photo(self, p, c=""): pass


EX = json.load(open(os.path.join(ROOT, "director", "examples", "fintech.json")))
CALLS = []


def fake_chat(messages, model=None, temperature=0.4, max_tokens=6000, json_mode=True, tries=5, reasoning=None):
    first = messages[0]["content"]
    sysm = first if isinstance(first, str) else ""
    CALLS.append(sysm[:40])
    if sysm.startswith("You are the planning assistant"):
        return json.dumps({"requirements": ["Use the supplied phone picture", "Say Connect and show glowing lines", "End with the logo"], "concept": "Premium fintech ad", "aspect": "9:16", "duration": 12,
                           "voiceover": {"mode": "generate", "text": "Connect your money. Secure it. Send it fast."}, "stock": [], "cutout": [], "captions": True, "transcribe_videos": False, "style": {}})
    if sysm.startswith("You are the creative director"):
        tl = json.loads(json.dumps(EX["timeline"]))
        tl["layers"].append({"id": "cap", "type": "captions", "start": 0.5, "end": 11, "props": {"words_from": "voice", "y": 1500}})
        tl["layers"].append({"id": "bad_overlap", "type": "text", "start": 6.5, "end": 8, "x": 540, "y": 330, "props": {"text": "OVERLAP", "size": 120}})
        if CALLS.count(sysm[:40]) > 1:
            tl["layers"] = [l for l in tl["layers"] if l["id"] != "bad_overlap"]
        return json.dumps({"timeline": tl, "audio": EX["audio"] + [{"role": "sfx", "sfx": "unknown_sound", "start": 1}], "notes": "Phone shown as a flat picture with depth."})
    if sysm.startswith("You check a finished"):
        return json.dumps({"results": [{"n": 1, "status": "done"}, {"n": 2, "status": "done"}, {"n": 3, "status": "simplified", "note": "logo shown small"}]})
    if isinstance(messages[0]["content"], list):
        txt = messages[0]["content"][0]["text"]
        if "Describe this picture" in txt:
            return json.dumps({"what": "a phone", "has_text": False, "is_logo": False, "has_person": False, "background": "transparent"})
        return json.dumps({"issues": [{"severity": "major", "time": 3.0, "what": "text too close to the phone", "fix": "move text up"}]})
    raise AssertionError("unexpected call: " + sysm[:60])


def fake_generate(text, out, work):
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", "sine=f=300:d=7", "-ac", "2", out], check=True)
    return out


def fake_words(path):
    return [{"w": w, "s": 0.4 * i, "e": 0.4 * i + 0.35} for i, w in enumerate("Connect your money Secure it Send it fast".split())], "", 7.0


def fake_still(tl, props, times, out):
    os.makedirs(out, exist_ok=True)
    res = []
    for i, t in enumerate(times):
        p = os.path.join(out, f"s{i}.jpg")
        Image.new("RGB", (540, 960), (10, 20, 60)).save(p)
        res.append((t, p))
    return res


def fake_render(tl, props, out, on_progress=None):
    for p in (10, 50, 100):
        on_progress and on_progress(p)
    subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"color=c=navy:s=270x480:r=30:d={tl['duration']}", "-pix_fmt", "yuv420p", out], check=True)
    return out


run.Store, run.Telegram = FakeStore, FakeTg
voice.generate, voice.words_for = fake_generate, fake_words
groq.chat = fake_chat
import director  # noqa: E402
director.groq.chat = fake_chat
run.render.render_video, run.render.render_stills = fake_render, fake_still
run.render.prepare = lambda tl, paths, work: (open(os.path.join(work, "timeline.json"), "w").write(json.dumps(tl)) and os.path.join(work, "timeline.json")) or os.path.join(work, "timeline.json")

tmp = tempfile.mkdtemp()
Image.new("RGBA", (700, 1400), (255, 255, 255, 255)).save(tmp + "/phone.png")
Image.new("RGBA", (600, 600), (245, 196, 81, 255)).save(tmp + "/logo.png")
JOB = "mtest-1"
for n in ("phone.png", "logo.png"):
    FILES[f"motion/jobs/{JOB}/assets/{n}"] = open(f"{tmp}/{n}", "rb").read()
STORE[f"motion/jobs/{JOB}/brief.json"] = {"job_id": JOB, "chat_id": 1, "prompt": "Premium fintech ad using the phone and logo. Say Connect: glowing lines. End with the logo.", "urls": [],
    "assets": [{"path": f"motion/jobs/{JOB}/assets/{n}", "name": n, "kind": "image"} for n in ("phone.png", "logo.png")], "plan_first": False}

run.main(JOB)
st = STORE[f"motion/jobs/{JOB}/status.json"]
print("STATUS:", st["state"], "|", st["stage"])
assert st["state"] == "done", st
print("DELIVERED:", [s for s in SENT if s.startswith("VIDEO")][0][:160])
print("director calls:", len([c for c in CALLS if c.startswith("You are the creative director")]), "(2 = one fix round)")
final = STORE[f"motion/jobs/{JOB}/final.mp4"]
print("final uploaded bytes:", final["uploaded"])
out = subprocess.run(["ffprobe", "-v", "error", "-show_entries", "stream=codec_type", "-of", "csv=p=0", os.path.join("work", JOB, "final.mp4")], capture_output=True, text=True).stdout.split()
print("streams:", out)
print("OK")

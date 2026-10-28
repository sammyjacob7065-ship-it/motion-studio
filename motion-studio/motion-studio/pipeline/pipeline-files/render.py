"""Runs the Remotion renderer (engine/) for a timeline."""
import json
import os
import re
import shutil
import subprocess
from common import env

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
ENGINE = os.path.join(ROOT, "engine")


def prepare(timeline, asset_paths, work):
    """Copies the files the timeline uses into engine/public/assets and writes timeline.json."""
    dest = os.path.join(ENGINE, "public", "assets")
    shutil.rmtree(dest, ignore_errors=True)
    os.makedirs(dest, exist_ok=True)
    used = set()
    for l in timeline["layers"]:
        a = l.get("props", {}).get("asset")
        if a:
            used.add(a)
    bg = timeline.get("background", {}).get("asset")
    if bg:
        used.add(bg)
    for name in used:
        shutil.copy(asset_paths[name], os.path.join(dest, name))
    tp = os.path.join(work, "timeline.json")
    with open(tp, "w", encoding="utf-8") as f:
        json.dump(timeline, f)
    return os.path.abspath(tp)


def _run(cmd, on_line=None, timeout=3 * 3600):
    p = subprocess.Popen(cmd, cwd=ENGINE, stdout=subprocess.PIPE, stderr=subprocess.STDOUT, text=True, bufsize=1)
    tail = []
    for line in p.stdout:
        tail.append(line)
        tail = tail[-40:]
        if on_line:
            on_line(line)
    p.wait(timeout=timeout)
    return p.returncode, "".join(tail)


def render_video(timeline, props_path, out_path, on_progress=None):
    conc = env("RENDER_CONCURRENCY", "4")
    cmd = ["npx", "remotion", "render", "src/index.ts", "Main", os.path.abspath(out_path), f"--props={props_path}", "--codec=h264", "--crf=18", "--muted", f"--concurrency={conc}", "--log=info"]

    def on_line(line):
        m = re.search(r"Rendered (\d+)/(\d+)", line)
        if m and on_progress:
            on_progress(int(100 * int(m.group(1)) / max(1, int(m.group(2)))))
    code, tail = _run(cmd, on_line)
    if code != 0 or not os.path.exists(out_path):
        raise RuntimeError("render failed: " + re.sub(r"\s+", " ", tail)[-500:])
    return out_path


def render_stills(timeline, props_path, times, out_dir):
    os.makedirs(out_dir, exist_ok=True)
    paths = []
    for i, t in enumerate(times):
        p = os.path.abspath(os.path.join(out_dir, f"still_{i}.jpg"))
        frame = max(0, min(int(t * timeline["fps"]), int(timeline["duration"] * timeline["fps"]) - 1))
        code, tail = _run(["npx", "remotion", "still", "src/index.ts", "Main", p, f"--props={props_path}", f"--frame={frame}", "--image-format=jpeg", "--scale=0.5"])
        if code == 0 and os.path.exists(p):
            paths.append((t, p))
    return paths

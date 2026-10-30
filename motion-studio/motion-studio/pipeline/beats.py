"""Finds the beat of a song (pure Python, no extra packages): tempo, beat times and the strongest hits. Used to cut pictures and place graphics on the music."""
import array
import math
import subprocess

SR = 8000
FRAME = 80           # 10 ms


def _envelope(path, max_seconds=240):
    p = subprocess.run(["ffmpeg", "-v", "error", "-i", path, "-t", str(max_seconds), "-ac", "1", "-ar", str(SR), "-f", "s16le", "-"], capture_output=True)
    pcm = array.array("h")
    pcm.frombytes(p.stdout[: len(p.stdout) // 2 * 2])
    env = []
    for i in range(0, len(pcm) - FRAME, FRAME):
        seg = pcm[i:i + FRAME]
        env.append(math.sqrt(sum(x * x for x in seg) / FRAME))
    return env


def analyze(path):
    """Returns {"bpm", "period", "beats": [seconds], "hits": [seconds], "duration"} or None when no clear beat was found."""
    try:
        env = _envelope(path)
    except Exception:  # noqa: BLE001
        return None
    n = len(env)
    if n < 300:
        return None
    # onset strength = rise of the (smoothed, compressed) loudness
    comp = [math.log1p(e / 50.0) for e in env]
    sm = [sum(comp[max(0, i - 2):i + 3]) / len(comp[max(0, i - 2):i + 3]) for i in range(n)]
    flux = [max(0.0, sm[i] - sm[i - 1]) for i in range(1, n)]
    flux.insert(0, 0.0)
    mean = sum(flux) / n
    flux = [max(0.0, f - mean) for f in flux]
    # tempo: strongest repeat distance between 0.33 s (180 bpm) and 1.0 s (60 bpm)
    best_lag, best_score = None, 0.0
    for lag in range(33, 101):
        score = sum(flux[i] * flux[i + lag] for i in range(0, n - lag, 1))
        score *= 1.0 + 0.15 * (1 if 40 <= lag <= 75 else 0)          # 80-150 bpm is the most common
        if score > best_score:
            best_lag, best_score = lag, score
    if not best_lag or best_score <= 0:
        return None
    # phase: where inside one beat the strongest onsets fall
    phase_scores = [0.0] * best_lag
    for i, f in enumerate(flux):
        phase_scores[i % best_lag] += f
    ph = max(range(best_lag), key=lambda k: phase_scores[k])
    beats = []
    i = ph
    while i < n:
        # snap each beat to the local onset peak (within 3 frames) so a drifting tempo stays on the music
        lo, hi = max(0, i - 3), min(n, i + 4)
        j = max(range(lo, hi), key=lambda k: flux[k])
        beats.append(round(j * 0.01, 3))
        i += best_lag
    hits = []
    for j in sorted(range(n), key=lambda k: -flux[k]):
        t = j * 0.01
        if flux[j] <= 0:
            break
        if all(abs(t - h) >= 1.2 for h in hits):
            hits.append(round(t, 3))
        if len(hits) >= 12:
            break
    return {"bpm": round(60.0 / (best_lag * 0.01), 1), "period": round(best_lag * 0.01, 3), "beats": beats, "hits": sorted(hits), "duration": round(n * 0.01, 2)}


def describe(info, limit=40):
    """A short text for the director."""
    if not info:
        return ""
    b = info["beats"][:limit]
    return (f"MUSIC: about {info['bpm']:.0f} BPM (a beat every {info['period']:.2f}s). Beat times (s): " + ", ".join(f"{t:.2f}" for t in b)
            + (" ..." if len(info["beats"]) > limit else "") + ". Strongest hits (s): " + ", ".join(f"{t:.1f}" for t in info["hits"][:8])
            + ". Cut pictures and start graphics ON these beats; put the big moments on the strong hits.")

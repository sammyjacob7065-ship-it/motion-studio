"""Audio: synthesized sound effects (royalty free by construction) and the final mix with ffmpeg."""
import os
import subprocess

SFX = {
    "whoosh": ("(random(0)*2-1)*pow(sin(PI*t/0.9),2)*0.7", 0.9, "highpass=f=300,lowpass=f=6500"),
    "swoosh_up": ("(random(0)*2-1)*pow(sin(PI*t/0.6),3)*0.6", 0.6, "highpass=f=700,lowpass=f=9000"),
    "pop": ("sin(2*PI*(600+900*exp(-t*40))*t)*exp(-t*30)*0.8", 0.18, ""),
    "click": ("(random(0)*2-1)*exp(-t*220)*0.8", 0.06, "highpass=f=1500"),
    "roll": ("sin(2*PI*1800*t)*exp(-16*mod(30*(1-pow(2,-10*t/1.6)),1))*0.55", 1.7, ""),
    "tick": ("sin(2*PI*1800*t)*exp(-t*90)*0.7", 0.05, ""),
    "hit": ("sin(2*PI*(55+120*exp(-t*18))*t)*exp(-t*5)*0.9+(random(0)*2-1)*exp(-t*35)*0.35", 1.2, "lowpass=f=4000"),
    "riser": ("(sin(2*PI*(220+1400*t/1.8*t/1.8)*t)*0.35+(random(0)*2-1)*0.25)*(t/1.8)", 1.8, "lowpass=f=7000"),
    "shimmer": ("(sin(2*PI*2093*t)+sin(2*PI*2637*t)+sin(2*PI*3136*t))*0.12*exp(-t*3)", 1.4, ""),
    "sparkle": ("(sin(2*PI*3136*t)+sin(2*PI*4186*t)*0.7)*0.14*exp(-t*6)*(0.6+0.4*sin(2*PI*14*t))", 0.9, ""),
}
SFX_NAMES = sorted(SFX)


def make_sfx(dest_dir):
    os.makedirs(dest_dir, exist_ok=True)
    out = {}
    for name, (expr, dur, flt) in SFX.items():
        p = os.path.join(dest_dir, name + ".wav")
        cmd = ["ffmpeg", "-y", "-loglevel", "error", "-f", "lavfi", "-i", f"aevalsrc='{expr}':d={dur}:s=48000"]
        af = ",".join(x for x in [flt, f"afade=t=out:st={max(0.0, dur - 0.08)}:d=0.08"] if x)
        cmd += ["-af", af, "-ac", "2", p]
        r = subprocess.run(cmd, capture_output=True, text=True)
        if r.returncode == 0 and os.path.exists(p):
            out[name] = p
    return out


def mix(video, items, duration, out_path):
    """items: [{path, start, volume, role(voice|music|sfx), srcStart, dur, loop}]. Returns out_path."""
    if not items:
        subprocess.run(["ffmpeg", "-y", "-loglevel", "error", "-i", video, "-c", "copy", out_path], check=True)
        return out_path
    cmd = ["ffmpeg", "-y", "-loglevel", "error", "-i", video]
    fl, voices, musics, sfxs = [], [], [], []
    for i, it in enumerate(items):
        n = i + 1
        if it.get("loop"):
            cmd += ["-stream_loop", "-1"]
        cmd += ["-i", it["path"]]
        chain = f"[{n}:a]aresample=48000,aformat=channel_layouts=stereo"
        ss = float(it.get("srcStart", 0) or 0)
        d = it.get("dur")
        trim = []
        if ss > 0:
            trim.append(f"start={ss}")
        if d:
            trim.append(f"duration={float(d)}")
        if it.get("loop") and not d:
            trim.append(f"duration={duration}")
        if trim:
            chain += ",atrim=" + ":".join(trim)
        chain += ",asetpts=PTS-STARTPTS"
        vol = float(it.get("volume", 1.0))
        chain += f",volume={vol}"
        role = it.get("role", "sfx")
        if role == "music":
            fo = max(0.0, duration - float(it.get("start", 0)) - 1.6)
            chain += f",afade=t=in:d=1.0,afade=t=out:st={fo}:d=1.5"
        ms = int(max(0.0, float(it.get("start", 0))) * 1000)
        if ms:
            chain += f",adelay={ms}|{ms}"
        chain += f",apad=whole_dur={duration}[a{n}]"
        fl.append(chain)
        (voices if role == "voice" else musics if role == "music" else sfxs).append(f"[a{n}]")
    parts = []
    if voices and musics:
        fl.append("".join(voices) + f"amix=inputs={len(voices)}:normalize=0:dropout_transition=0[vo_all]")
        fl.append("[vo_all]asplit=2[vo][vosc]")
        fl.append("".join(musics) + f"amix=inputs={len(musics)}:normalize=0:dropout_transition=0[mu_all]")
        fl.append("[mu_all][vosc]sidechaincompress=threshold=0.04:ratio=9:attack=15:release=450[mu]")
        parts += ["[vo]", "[mu]"]
    else:
        parts += voices + musics
    parts += sfxs
    fl.append("".join(parts) + f"amix=inputs={len(parts)}:normalize=0:dropout_transition=0,loudnorm=I=-16:TP=-1.5:LRA=11,atrim=0:{duration},asetpts=PTS-STARTPTS[aout]")
    cmd += ["-filter_complex", ";".join(fl), "-map", "0:v", "-map", "[aout]", "-c:v", "copy", "-c:a", "aac", "-b:a", "192k", "-shortest", "-movflags", "+faststart", out_path]
    r = subprocess.run(cmd, capture_output=True, text=True)
    if r.returncode != 0:
        raise RuntimeError("audio mix failed: " + r.stderr[-300:])
    return out_path

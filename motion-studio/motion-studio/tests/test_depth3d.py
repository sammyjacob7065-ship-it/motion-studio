"""Unit test of the 3D department (no internet, no keys).  Run:  python tests/test_depth3d.py"""
import os
import sys
import tempfile

ROOT = os.path.dirname(os.path.dirname(os.path.abspath(__file__)))
sys.path.insert(0, os.path.join(ROOT, "pipeline"))
import numpy as np  # noqa: E402
from PIL import Image, ImageDraw  # noqa: E402

import creative  # noqa: E402
import depth3d  # noqa: E402

d = tempfile.mkdtemp()
# a studio photo: plain light backdrop, a green bottle with a cream label wider than the neck
ph = Image.new("RGB", (800, 800), (232, 232, 236))
dr = ImageDraw.Draw(ph)
dr.rounded_rectangle((300, 260, 500, 740), 30, fill=(30, 120, 60))
dr.rounded_rectangle((360, 120, 440, 280), 20, fill=(30, 120, 60))
dr.rectangle((300, 420, 500, 600), fill=(250, 245, 230))
ph.save(os.path.join(d, "p.jpg"))
files, aspect = depth3d.make_depth_slices(os.path.join(d, "p.jpg"), os.path.join(d, "p"), 4)
assert len(files) == 4 and abs(aspect - 1.0) < 1e-6 and not depth3d.make_depth_slices.single, "four slices expected"
top = np.array(Image.open(files[-1][0]))[:, :, 3]
assert top[500, 400] > 200 and top[30, 30] < 20, "subject must be the top slice, background empty there"
assert top[500, 310] > 200, "the cream label belongs to the bottle (no hole)"
assert np.array(Image.open(files[0][0]))[:, :, 3].min() == 255, "the far slice is full"
# no subject, no model: one honest slice
Image.fromarray((np.random.RandomState(1).rand(400, 400, 3) * 255).astype("uint8")).save(os.path.join(d, "noise.jpg"))
_real = depth3d._subject_alpha
depth3d._subject_alpha = lambda *a, **k: None          # force "no subject found" (a cut-out model, when installed, could find one in noise)
f2, _ = depth3d.make_depth_slices(os.path.join(d, "noise.jpg"), os.path.join(d, "n"), 4)
assert len(f2) == 1 and depth3d.make_depth_slices.single, "busy picture without a subject must stay one slice"
depth3d._subject_alpha = _real
# plain back + edge colour + spin
cut = Image.new("RGBA", (200, 400), (0, 0, 0, 0))
ImageDraw.Draw(cut).rounded_rectangle((20, 10, 180, 390), 30, fill=(200, 30, 30, 255))
cut.save(os.path.join(d, "c.png"))
b = np.array(Image.open(depth3d.plain_back(os.path.join(d, "c.png"), os.path.join(d, "b.png"))))
assert b[200, 100, 3] == 255 and b[2, 2, 3] == 0, "back keeps the outline"
assert depth3d.edge_color(os.path.join(d, "c.png")).startswith("#")
lay = {"start": 1, "end": 5, "props": {"spin": {"turns": 1, "start": 2, "end": 4}}}
depth3d.expand_motion(lay)
assert lay["anim"]["rotateY"][0][:2] == [2.0, 0.0] and lay["anim"]["rotateY"][1][1] == 360.0
sw = {"start": 0, "end": 4, "props": {"swing": {"angle": 30, "cycles": 2}}}
depth3d.expand_motion(sw)
ks = sw["anim"]["rotateY"]
assert ks[0][1] == 0 and ks[-1][1] == 0 and all(ks[i][0] <= ks[i + 1][0] for i in range(len(ks) - 1)), "swing keys must be in time order"
# creative director gate
reg = {"a.jpg": {"kind": "image"}}
assert creative.wanted("make a 30 second ad for this", reg)
assert not creative.wanted("SCENE 1\nVOICE-OVER: \"x\"", reg)
assert not creative.wanted("CREATIVE: off\nmake an ad", reg)
assert creative.duration_of("a 45 second ad")[0] == 45 and creative.duration_of("30 minutes")[0] == 120
print("depth3d + creative tests passed")

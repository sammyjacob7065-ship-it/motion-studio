"""Cleaner department: removes an old text / logo completely from a frame BEFORE anything new is written.
The old way (paint over the letters' colour) left what is around the letters: glow, drop shadow, outline, anti-aliased edges, so the old text still showed as a ghost.
Here the cleaner
  1. looks at the ring of picture around the text (outside it) and fits a smooth model of the background from it (a robust surface per colour channel);
  2. compares the whole area under and around the text with that model: everything that differs (letters, glow, shadow, outline, edges) is 'old text' and goes into the mask,
     including the faint tails (hysteresis), and the mask is grown a little;
  3. rebuilds the background under the mask: from the surface model plus the picture's own grain when the background is smooth (gradients, blurred light),
     or by inpainting when the background has real structure;
  4. gives a quality number (how well the ring was explained by the model) so the caller can check the result.
Works on one frame region; the caller passes the region and the tight text box inside it."""
import cv2
import numpy as np


def _terms(h, w):
    ys, xs = np.mgrid[0:h, 0:w].astype(np.float32)
    x, y = xs / max(1, w - 1) * 2 - 1, ys / max(1, h - 1) * 2 - 1
    return np.stack([np.ones_like(x), x, y, x * y, x * x, y * y, x * x * y, x * y * y], axis=-1)


def fit_surface(roi, ring):
    """Robust polynomial surface through the ring pixels. Returns (fit float32 HxWx3, residual scale per channel)."""
    h, w = roi.shape[:2]
    T = _terms(h, w)
    idx = np.flatnonzero(ring.ravel())
    if len(idx) < 40:
        return None, None
    if len(idx) > 6000:
        idx = np.random.default_rng(1).choice(idx, 6000, replace=False)
    A = T.reshape(-1, T.shape[-1])[idx]
    keep = np.ones(len(idx), bool)
    fit = np.zeros(roi.shape, np.float32)
    flat = roi.reshape(-1, 3).astype(np.float32)
    coef = None
    for _ in range(4):
        coef = np.linalg.lstsq(A[keep], flat[idx][keep], rcond=None)[0]
        res = np.linalg.norm(A @ coef - flat[idx], axis=1)
        s = 1.4826 * np.median(res[keep]) + 1e-3
        new = res < 2.8 * max(s, 2.0)
        if new.sum() < 30 or (new == keep).all():
            break
        keep = new
    fit = (T.reshape(-1, T.shape[-1]) @ coef).reshape(h, w, 3).astype(np.float32)
    res_ring = np.linalg.norm(fit - roi.astype(np.float32), axis=2)[ring]
    return fit, float(1.4826 * np.median(np.abs(res_ring - np.median(res_ring))) + np.median(res_ring))


def clean(roi, inner, margin=0.55, grow=0.14, force=None):
    """roi: BGR uint8 region. inner: (x0,y0,x1,y1) the tight box of the old text inside the roi.
    Returns (clean roi uint8, mask uint8, quality) where quality is the residual of the background model in grey levels (small = a smooth background, rebuilt exactly)."""
    h, w = roi.shape[:2]
    ix0, iy0, ix1, iy1 = [int(v) for v in inner]
    th = max(8, iy1 - iy0)
    m = int(th * margin) + 3
    cz = np.zeros((h, w), bool)                                  # clear zone: the text plus its glow room
    cz[max(0, iy0 - m):min(h, iy1 + m), max(0, ix0 - m):min(w, ix1 + m)] = True
    ring = ~cz
    ring &= cv2.erode(np.ones((h, w), np.uint8), np.ones((3, 3), np.uint8)).astype(bool)
    fit, scale = fit_surface(roi, ring)
    f = roi.astype(np.float32)
    if fit is None:
        mask = np.zeros((h, w), np.uint8)
        mask[iy0:iy1, ix0:ix1] = 1
        return cv2.inpaint(roi, mask, 5, cv2.INPAINT_TELEA), mask, 99.0
    res = np.linalg.norm(cv2.GaussianBlur(f, (0, 0), 1.0) - fit, axis=2)          # grain does not count as difference
    ring_res = res[ring]
    sigma = float(1.4826 * np.median(np.abs(ring_res - np.median(ring_res)))) + 1.0
    thr = max(8.0, 3.0 * sigma + float(np.median(ring_res)))
    core = ((res > thr) & cz).astype(np.uint8)
    # only what belongs to the text: components that touch the text box
    box = np.zeros((h, w), np.uint8)
    box[iy0:iy1, ix0:ix1] = 1
    n, lab = cv2.connectedComponents(cv2.dilate(core, np.ones((3, 3), np.uint8), iterations=2))
    keep = np.zeros((h, w), np.uint8)
    for k in range(1, n):
        comp = lab == k
        if (comp & (box > 0)).any():
            keep |= comp.astype(np.uint8)
    core &= keep
    g = max(3, int(th * grow))
    ker = cv2.getStructuringElement(cv2.MORPH_ELLIPSE, (2 * g + 1, 2 * g + 1))
    mask = cv2.dilate(core, ker)
    # the faint tails of the glow and the shadow: weaker differences next to the mask
    low = ((res > max(4.0, 0.8 * sigma + float(np.median(ring_res)))) & cz).astype(np.uint8)
    tail = cv2.dilate(mask, np.ones((6 * g + 1, 6 * g + 1), np.uint8)) & low
    mask = cv2.morphologyEx(mask | tail, cv2.MORPH_CLOSE, np.ones((5, 5), np.uint8))
    mask &= cz.astype(np.uint8)
    if force is not None:                                      # the caller knows part of what must go (an object's outline): joined to the mask
        mask |= (force > 0).astype(np.uint8)
    smooth = scale <= 11.0
    if smooth:
        # rebuilt from the model of the background, with the picture's own grain
        hp = f - cv2.GaussianBlur(f, (0, 0), 1.2)
        grain = 0.45 * float(np.std(hp[ring]))
        noise = cv2.GaussianBlur(np.random.default_rng(7).normal(0, grain * 1.3, f.shape).astype(np.float32), (0, 0), 0.6)
        # structure the model cannot hold (the edge of a circle, a light streak) is carried over from the picture around: inpaint the difference, not the picture
        r = cv2.GaussianBlur(f, (0, 0), 1.0) - fit
        bad = ((res > 60) & ring).astype(np.uint8)                           # other objects in the ring (a logo, a picture): not structure of the background, never carried over
        big0 = cv2.dilate(mask | cv2.dilate(bad, np.ones((5, 5), np.uint8)), np.ones((3, 3), np.uint8))
        r16 = np.clip(r * 4 + 128, 0, 255).astype(np.uint8)
        ri = cv2.inpaint(r16, big0 * 255, 7, cv2.INPAINT_NS).astype(np.float32)
        ri = (ri - 128) / 4.0
        ri = cv2.GaussianBlur(ri, (0, 0), 1.5)
        if float(np.std(cv2.GaussianBlur(r, (0, 0), 2.0)[ring])) < 2.5:           # the background is explained by the model (no structure to carry over): no streaks from noise
            ri = np.zeros_like(ri)
        rebuilt = np.clip(fit + ri + noise, 0, 255)
        a = cv2.GaussianBlur(mask.astype(np.float32), (0, 0), max(1.0, g * 0.35))[..., None]
        a = np.clip(a * 1.5, 0, 1) * (cz[..., None])
        out = f * (1 - a) + rebuilt * a
        return np.clip(out, 0, 255).astype(np.uint8), mask, scale
    # a background with structure: inpainting from the pixels around (the stronger method when the contrib module is there)
    big = cv2.dilate(mask, np.ones((3, 3), np.uint8))
    try:
        dst = np.zeros_like(roi)
        cv2.xphoto.inpaint(roi, (1 - big).astype(np.uint8) * 255, dst, cv2.xphoto.INPAINT_FSR_FAST)
        out = dst
    except Exception:  # noqa: BLE001
        out = cv2.inpaint(roi, big * 255, 6, cv2.INPAINT_TELEA)
    return out, mask, scale

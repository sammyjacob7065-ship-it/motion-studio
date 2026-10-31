import type { CameraKey, EnterExit, Key, Layer } from './types';

const clamp01 = (x: number) => Math.min(1, Math.max(0, x));
const c1 = 1.70158;
const c3 = c1 + 1;
const c4 = (2 * Math.PI) / 3;

export const EASES: Record<string, (x: number) => number> = {
  linear: (x) => x,
  in: (x) => x * x * x,
  out: (x) => 1 - Math.pow(1 - x, 3),
  inOut: (x) => (x < 0.5 ? 4 * x * x * x : 1 - Math.pow(-2 * x + 2, 3) / 2),
  inQuad: (x) => x * x,
  outQuad: (x) => 1 - (1 - x) * (1 - x),
  inOutQuad: (x) => (x < 0.5 ? 2 * x * x : 1 - Math.pow(-2 * x + 2, 2) / 2),
  outQuart: (x) => 1 - Math.pow(1 - x, 4),
  inOutQuart: (x) => (x < 0.5 ? 8 * x * x * x * x : 1 - Math.pow(-2 * x + 2, 4) / 2),
  outExpo: (x) => (x >= 1 ? 1 : 1 - Math.pow(2, -10 * x)),
  inExpo: (x) => (x <= 0 ? 0 : Math.pow(2, 10 * x - 10)),
  inOutExpo: (x) => (x <= 0 ? 0 : x >= 1 ? 1 : x < 0.5 ? Math.pow(2, 20 * x - 10) / 2 : (2 - Math.pow(2, -20 * x + 10)) / 2),
  outBack: (x) => 1 + c3 * Math.pow(x - 1, 3) + c1 * Math.pow(x - 1, 2),
  inBack: (x) => c3 * x * x * x - c1 * x * x,
  outElastic: (x) => (x <= 0 ? 0 : x >= 1 ? 1 : Math.pow(2, -10 * x) * Math.sin((x * 10 - 0.75) * c4) + 1),
  outBounce: (x) => { const n1 = 7.5625, d1 = 2.75; if (x < 1 / d1) return n1 * x * x; if (x < 2 / d1) return n1 * (x -= 1.5 / d1) * x + 0.75; if (x < 2.5 / d1) return n1 * (x -= 2.25 / d1) * x + 0.9375; return n1 * (x -= 2.625 / d1) * x + 0.984375; },
  inBounce: (x) => 1 - EASES.outBounce(1 - x),
  spring: (x) => (x <= 0 ? 0 : x >= 1 ? 1 : 1 - Math.exp(-6 * x) * Math.cos(x * 9)),
};

export const ease = (name: string | undefined, x: number) => (EASES[name || 'inOut'] || EASES.inOut)(clamp01(x));

/** Value of a keyframe track at time t (seconds). Numbers interpolate, strings step. */
export function sampleTrack(keys: Key[] | undefined, t: number, fallback: number): number {
  if (!keys || !keys.length) return fallback;
  const ks = [...keys].sort((a, b) => a[0] - b[0]);
  if (t <= ks[0][0]) return Number(ks[0][1]);
  const last = ks[ks.length - 1];
  if (t >= last[0]) return Number(last[1]);
  for (let i = 0; i < ks.length - 1; i++) {
    const a = ks[i], b = ks[i + 1];
    if (t >= a[0] && t <= b[0]) {
      const span = b[0] - a[0] || 1e-6;
      const p = ease((b[2] as string) || (a[2] as string) || 'inOut', (t - a[0]) / span);
      return Number(a[1]) + (Number(b[1]) - Number(a[1])) * p;
    }
  }
  return fallback;
}

export function cameraAt(cam: CameraKey[] | undefined, t: number) {
  if (!cam || !cam.length) return { scale: 1, x: 0, y: 0, rotate: 0 };
  const ks = [...cam].sort((a, b) => a[0] - b[0]);
  const pick = (i: number) => ({ scale: ks[i][1], x: ks[i][2], y: ks[i][3], rotate: ks[i][4] || 0 });
  if (t <= ks[0][0]) return pick(0);
  if (t >= ks[ks.length - 1][0]) return pick(ks.length - 1);
  for (let i = 0; i < ks.length - 1; i++) {
    if (t >= ks[i][0] && t <= ks[i + 1][0]) {
      const p = ease((ks[i + 1][5] as string) || 'inOutQuart', (t - ks[i][0]) / (ks[i + 1][0] - ks[i][0] || 1e-6));
      const a = pick(i), b = pick(i + 1);
      return { scale: a.scale + (b.scale - a.scale) * p, x: a.x + (b.x - a.x) * p, y: a.y + (b.y - a.y) * p, rotate: a.rotate + (b.rotate - a.rotate) * p };
    }
  }
  return { scale: 1, x: 0, y: 0, rotate: 0 };
}

export type Fx = { opacity: number; dx: number; dy: number; scale: number; rotate: number; blur: number; clip: number; draw: number };
export const NEUTRAL: Fx = { opacity: 1, dx: 0, dy: 0, scale: 1, rotate: 0, blur: 0, clip: 1, draw: 1 };

/** Effect of an enter (dir=1) or exit (dir=-1) preset. p goes 0 -> 1 over the preset duration. */
export function presetFx(preset: string | undefined, p0: number, easeName: string | undefined, distance = 120, dir = 1): Fx {
  const fx = { ...NEUTRAL };
  if (!preset || preset === 'none') return fx;
  // for enter: progress p goes 0 (hidden) to 1 (shown). for exit: goes 1 (shown) to 0 (hidden)
  const p = ease(easeName || (preset === 'pop' ? 'outBack' : 'outExpo'), dir === 1 ? p0 : 1 - p0);
  const q = 1 - p; // how far from the shown state
  const raw = clamp01(dir === 1 ? p0 : 1 - p0);
  switch (preset) {
    case 'fade': fx.opacity = raw; break;
    case 'slideUp': fx.opacity = clamp01(p * 1.6); fx.dy = q * distance; break;
    case 'slideDown': fx.opacity = clamp01(p * 1.6); fx.dy = -q * distance; break;
    case 'slideLeft': fx.opacity = clamp01(p * 1.6); fx.dx = q * distance; break;
    case 'slideRight': fx.opacity = clamp01(p * 1.6); fx.dx = -q * distance; break;
    case 'scaleIn': fx.opacity = clamp01(p * 1.4); fx.scale = 0.6 + 0.4 * p; break;
    case 'zoomIn': fx.opacity = clamp01(p * 1.4); fx.scale = 1.5 - 0.5 * p; break;
    case 'pop': fx.opacity = clamp01(raw * 3); fx.scale = Math.max(0, p); break;
    case 'blurIn': fx.opacity = clamp01(p * 1.5); fx.blur = q * 28; fx.scale = 1 + q * 0.06; break;
    case 'wipe': fx.clip = p; fx.opacity = 1; break;
    case 'rotateIn': fx.opacity = clamp01(p * 1.5); fx.rotate = -q * 18; fx.scale = 0.85 + 0.15 * p; break;
    case 'drop': fx.opacity = clamp01(raw * 4); fx.dy = -q * distance * 2; fx.scale = 1 + q * 0.1; break;
    case 'riseGlow': fx.opacity = clamp01(p * 1.4); fx.dy = q * distance * 0.6; fx.blur = q * 10; break;
    case 'draw': fx.draw = p; break;
    default: fx.opacity = raw;
  }
  return fx;
}

export function layerFx(layer: Layer, t: number): Fx {
  let fx = { ...NEUTRAL };
  const en = layer.enter as EnterExit | undefined;
  const ex = layer.exit as EnterExit | undefined;
  if (en && en.preset) {
    const d = Math.max(0.05, en.dur ?? 0.7);
    const start = layer.start + (en.delay || 0);
    const p = (t - start) / d;
    if (p < 1) {
      if (p <= 0) return { ...NEUTRAL, opacity: 0, clip: 0, draw: 0, scale: en.preset === 'pop' ? 0 : 1 };
      fx = presetFx(en.preset, p, en.ease, en.distance, 1);
    }
  }
  if (ex && ex.preset) {
    const d = Math.max(0.05, ex.dur ?? 0.5);
    const p = (t - (layer.end - d)) / d;
    if (p > 0) {
      const f2 = presetFx(ex.preset, p, ex.ease || 'inQuad', ex.distance, -1);
      fx = {
        opacity: fx.opacity * f2.opacity, dx: fx.dx + f2.dx, dy: fx.dy + f2.dy, scale: fx.scale * f2.scale,
        rotate: fx.rotate + f2.rotate, blur: Math.max(fx.blur, f2.blur), clip: Math.min(fx.clip, f2.clip), draw: Math.min(fx.draw, f2.draw),
      };
    }
  }
  return fx;
}

/** Number prop that may be animated through layer.anim[name]. */
export function num(layer: Layer, name: string, t: number, base: number): number {
  return sampleTrack(layer.anim && layer.anim[name], t, base);
}

/** Small deterministic random generator (so particles look the same on every frame and every render). */
export function rng(seed: number) {
  let s = (seed * 2654435761) >>> 0 || 1;
  return () => {
    s ^= s << 13; s >>>= 0;
    s ^= s >>> 17;
    s ^= s << 5; s >>>= 0;
    return (s >>> 0) / 4294967296;
  };
}

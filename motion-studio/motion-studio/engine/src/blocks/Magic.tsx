import React from 'react';
import { Img, staticFile } from 'remotion';
import { Ctx, LayerBox, hexA } from './common';
import { ease, rng } from '../anim';
import type { Layer } from '../types';

/**
 * MAGIC product moments: small After-Effects-style animations made from pictures and drawn parts.
 * kinds: box_open | table_rise | drop | roll_in | cap_pop | spin_float | fly_in | burst | fizz
 * Everything is a pure function of the time since the layer started (u), so every render looks the same.
 */

const clamp = (x: number, a = 0, b = 1) => Math.min(b, Math.max(a, x));
const seg = (u: number, a: number, b: number) => clamp((u - a) / (b - a || 1e-6));
const E = (name: string, x: number) => ease(name, clamp(x));
const lerp = (a: number, b: number, p: number) => a + (b - a) * p;
const imgSrc = (name: string) => staticFile('assets/' + name);

type Base = { u: number; W: number; H: number; p: Record<string, any>; aspect: number; asset: string; accent: string };

/* ---------- small drawing helpers ---------- */

const Glow: React.FC<{ x: number; y: number; r: number; color: string; a: number }> = ({ x, y, r, color, a }) =>
  a <= 0.01 ? null : <div style={{ position: 'absolute', left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: '50%', background: `radial-gradient(circle, ${hexA(color, a)} 0%, ${hexA(color, a * 0.45)} 38%, ${hexA(color, 0)} 70%)`, pointerEvents: 'none' }} />;

const Ring: React.FC<{ x: number; y: number; r: number; color: string; a: number; w?: number; squash?: number }> = ({ x, y, r, color, a, w = 6, squash = 1 }) =>
  a <= 0.01 ? null : <div style={{ position: 'absolute', left: x - r, top: y - r * squash, width: r * 2, height: r * 2 * squash, borderRadius: '50%', border: `${w}px solid ${hexA(color, a)}`, boxShadow: `0 0 24px ${hexA(color, a * 0.7)}`, boxSizing: 'border-box', pointerEvents: 'none' }} />;

const Rays: React.FC<{ x: number; y: number; r: number; color: string; a: number; rot: number }> = ({ x, y, r, color, a, rot }) =>
  a <= 0.01 ? null : (
    <div style={{
      position: 'absolute', left: x - r, top: y - r, width: r * 2, height: r * 2, borderRadius: '50%', opacity: a, transform: `rotate(${rot}deg)`,
      background: `repeating-conic-gradient(from 0deg, ${hexA(color, 0.55)} 0deg 5deg, ${hexA(color, 0)} 5deg 18deg)`,
      WebkitMaskImage: 'radial-gradient(circle, #000 0%, rgba(0,0,0,0.6) 45%, transparent 72%)', maskImage: 'radial-gradient(circle, #000 0%, rgba(0,0,0,0.6) 45%, transparent 72%)', pointerEvents: 'none',
    }} />
  );

/** Particles flying out of a point; s = seconds since the burst. */
const Sparks: React.FC<{ x: number; y: number; s: number; n: number; color: string; seed: number; speed: number; life: number; grav?: number; size?: number; from?: number; to?: number }> = ({ x, y, s, n, color, seed, speed, life, grav = 600, size = 9, from = 0, to = 360 }) => {
  if (s < 0 || s > life) return null;
  const els: React.ReactNode[] = [];
  const r = rng(seed);
  for (let i = 0; i < n; i++) {
    const ang = ((from + (to - from) * r()) * Math.PI) / 180;
    const sp = speed * (0.35 + 0.8 * r());
    const sz = size * (0.5 + r());
    const w = r();
    const px = x + Math.cos(ang) * sp * s * (1 - 0.35 * (s / life));
    const py = y + Math.sin(ang) * sp * s * (1 - 0.35 * (s / life)) + 0.5 * grav * s * s;
    const a = Math.pow(1 - s / life, 1.2);
    const c = w > 0.7 ? '#ffffff' : color;
    els.push(<div key={i} style={{ position: 'absolute', left: px - sz / 2, top: py - sz / 2, width: sz, height: sz, borderRadius: '50%', background: c, opacity: a, boxShadow: `0 0 ${sz * 2}px ${hexA(c, 0.9)}` }} />);
  }
  return <>{els}</>;
};

/** Bubbles rising from a mouth; s = seconds since the fizz started. */
const Bubbles: React.FC<{ x: number; y: number; s: number; life: number; seed: number; n?: number; spread?: number; rise?: number }> = ({ x, y, s, life, seed, n = 26, spread = 90, rise = 520 }) => {
  if (s < 0) return null;
  const els: React.ReactNode[] = [];
  const r = rng(seed);
  for (let i = 0; i < n; i++) {
    const delay = r() * life * 0.7;
    const age = s - delay;
    const dur = 0.9 + r() * 0.9;
    const x0 = (r() - 0.5) * spread * 0.5;
    const wob = 10 + r() * 24;
    const sz = 8 + r() * 20;
    const ph = r() * 6.28;
    if (age < 0 || age > dur) continue;
    const q = age / dur;
    const px = x + x0 + Math.sin(q * 7 + ph) * wob + (x0 / spread) * q * 80;
    const py = y - q * rise * (0.55 + 0.6 * r());
    const a = Math.sin(Math.min(1, q * 1.2) * Math.PI) * 0.85;
    els.push(<div key={i} style={{ position: 'absolute', left: px - sz / 2, top: py - sz / 2, width: sz, height: sz, borderRadius: '50%', border: '2px solid rgba(255,255,255,0.85)', background: 'radial-gradient(circle at 32% 30%, rgba(255,255,255,0.75), rgba(255,255,255,0.1) 60%)', opacity: a }} />);
  }
  return <>{els}</>;
};

const Mist: React.FC<{ x: number; y: number; s: number; color?: string }> = ({ x, y, s, color = '#ffffff' }) => {
  if (s < 0 || s > 1.8) return null;
  const els: React.ReactNode[] = [];
  for (let i = 0; i < 7; i++) {
    const r = rng(77 + i * 13);
    const dx = (r() - 0.5) * 220 * s;
    const q = s / 1.8;
    const sz = 110 + r() * 150 + q * 120;
    els.push(<div key={i} style={{ position: 'absolute', left: x + dx - sz / 2, top: y - s * (160 + r() * 140) - sz / 2, width: sz, height: sz, borderRadius: '50%', background: `radial-gradient(circle, ${hexA(color, 0.34 * (1 - q))}, ${hexA(color, 0)} 70%)`, filter: 'blur(6px)' }} />);
  }
  return <>{els}</>;
};

const Shadow: React.FC<{ x: number; y: number; w: number; a: number }> = ({ x, y, w, a }) =>
  a <= 0.01 ? null : <div style={{ position: 'absolute', left: x - w / 2, top: y - w * 0.09, width: w, height: w * 0.18, borderRadius: '50%', background: `radial-gradient(ellipse, rgba(0,0,0,${0.55 * a}) 0%, rgba(0,0,0,${0.25 * a}) 45%, rgba(0,0,0,0) 72%)`, pointerEvents: 'none' }} />;

const Product: React.FC<{ src: string; w: number; aspect: number; glow?: string; extra?: React.CSSProperties; clipTop?: number }> = ({ src, w, aspect, glow, extra, clipTop = 0 }) => (
  <Img src={src} onError={() => console.error('PICTURE FAILED TO LOAD: ' + src)} style={{ width: w, height: w * aspect, display: 'block', filter: `drop-shadow(0 18px 26px rgba(0,0,0,0.38))${glow ? ` drop-shadow(0 0 28px ${hexA(glow, 0.45)})` : ''}`, clipPath: clipTop > 0 ? `inset(${clipTop * 100}% 0 0 0)` : undefined, ...extra }} />
);

const Twinkle: React.FC<{ cx: number; cy: number; rx: number; ry: number; u: number; n: number; color: string; seed: number }> = ({ cx, cy, rx, ry, u, n, color, seed }) => {
  const els: React.ReactNode[] = [];
  const r = rng(seed);
  for (let i = 0; i < n; i++) {
    const ang = r() * 6.28, rad = 0.55 + r() * 0.5, sp = 0.8 + r() * 1.4, ph = r() * 6.28, sz = 14 + r() * 22;
    const a = Math.max(0, Math.sin(u * sp * 2.2 + ph));
    const x = cx + Math.cos(ang + u * 0.15) * rx * rad, y = cy + Math.sin(ang + u * 0.15) * ry * rad;
    els.push(
      <div key={i} style={{ position: 'absolute', left: x - sz / 2, top: y - sz / 2, width: sz, height: sz, opacity: a, transform: `scale(${0.4 + a * 0.8}) rotate(45deg)`, pointerEvents: 'none' }}>
        <div style={{ position: 'absolute', left: '44%', top: 0, width: '12%', height: '100%', background: color, borderRadius: 4, boxShadow: `0 0 12px ${hexA(color, 0.9)}` }} />
        <div style={{ position: 'absolute', top: '44%', left: 0, height: '12%', width: '100%', background: color, borderRadius: 4, boxShadow: `0 0 12px ${hexA(color, 0.9)}` }} />
      </div>,
    );
  }
  return <>{els}</>;
};

/* ---------- 1. BOX OPENS BY ITSELF, PRODUCT RISES OUT ---------- */

const Flap: React.FC<{ len: number; width: number; angle: number; color: string; inner: string; o: number }> = ({ len, width, angle, color, inner, o }) => (
  <div style={{ opacity: o, position: 'absolute', left: -width / 2, top: 0, width, height: len, transformOrigin: '50% 0%', transformStyle: 'preserve-3d', transform: `rotateX(${angle}deg)` }}>
    <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(180deg, ${color}, ${hexA(color, 0.92)})`, border: `1px solid ${hexA('#000000', 0.18)}`, boxSizing: 'border-box', backfaceVisibility: 'hidden' }} />
    <div style={{ position: 'absolute', inset: 0, background: `linear-gradient(180deg, ${inner}, ${hexA(inner, 0.85)})`, border: `1px solid ${hexA('#000000', 0.2)}`, boxSizing: 'border-box', transform: 'rotateY(180deg)', backfaceVisibility: 'hidden' }} />
  </div>
);

const BoxOpen: React.FC<Base> = ({ u, W, H, p, aspect, asset, accent }) => {
  const size = p.size ?? Math.min(W * 0.5, H * 0.3);
  const bw = size * 1.15, bh = size * 0.95, bd = size * 0.85;
  const cx = W / 2, cy = H * (p.y ?? 0.56);
  const kraft = p.boxColor || '#c8955a';
  const dark = '#8b5e2f';
  const inner = '#5a3a1a';
  const land = E('outBack', seg(u, 0.0, 0.7));
  const dropY = lerp(-H * 0.35, 0, E('outQuart', seg(u, 0.0, 0.55)));
  const sq = 1 + 0.06 * Math.sin(seg(u, 0.45, 0.85) * Math.PI);
  const aSide = lerp(-90, -205, E('outBack', seg(u, 0.95, 1.5)));
  const aFront = lerp(-90, -238, E('outBack', seg(u, 1.12, 1.7)));
  const pw = Math.min(size * 0.72, (bh * 0.85) / aspect);
  const ph = pw * aspect;
  const yIn = bh / 2 - ph / 2 - 6;                                   // sits on the box floor
  const yOut = -bh / 2 - ph / 2 - size * 0.12;
  const rise = E('outExpo', seg(u, 1.35, 2.45));
  const wob = Math.sin(seg(u, 1.35, 2.6) * Math.PI * 2) * 4 * (1 - seg(u, 1.35, 2.6));
  const leave = E('inOutQuart', seg(u, 2.75, 3.6));
  const worldFinal = H * 0.46;
  const groupDY = lerp(0, H * 0.34, leave);
  const worldY = lerp(cy + lerp(yIn, yOut, rise), worldFinal, leave);
  const prodLocalY = worldY - cy - groupDY;
  const bob = Math.sin(u * 2.4) * 10 * seg(u, 2.6, 3.2);
  const boxA = 1 - E('inQuad', seg(u, 2.9, 3.6));
  const pScale = lerp(1, 1.22, leave);
  const camY = Math.sin(u * 0.9) * 10;
  const burst = seg(u, 1.3, 2.4);
  return (
    <>
      <Glow x={cx} y={H * 0.44} r={size * (1.1 + 0.4 * leave)} color={accent} a={0.18 + 0.42 * Math.sin(Math.min(1, burst * 1.3) * Math.PI) * 0.6 + 0.3 * leave} />
      <Rays x={cx} y={cy - bh * 0.5} r={size * 1.6} color={accent} a={0.85 * Math.sin(clamp(burst * 1.15) * Math.PI)} rot={u * 24} />
      <Shadow x={cx} y={cy + bh / 2 + 18} w={bw * 1.5 * land} a={boxA * land} />
      <div style={{ position: 'absolute', left: cx, top: cy + dropY, width: 0, height: 0, perspective: 1500, perspectiveOrigin: '50% 40%' }}>
        <div style={{ position: 'absolute', left: 0, top: groupDY, width: 0, height: 0, transformStyle: 'preserve-3d', transform: `scale(${land * sq}) rotateX(${-16}deg) rotateY(${camY}deg)` }}>
          {/* inside of the box (back, left, right, floor) */}
          <div style={{ opacity: boxA, position: 'absolute', left: -bw / 2, top: -bh / 2, width: bw, height: bh, background: `linear-gradient(180deg, ${inner}, #2b1a0a)`, transform: `translateZ(${-bd / 2}px)` }} />
          <div style={{ opacity: boxA, position: 'absolute', left: -bd / 2, top: -bh / 2, width: bd, height: bh, background: `linear-gradient(90deg, #2b1a0a, ${inner})`, transform: `rotateY(90deg) translateZ(${-bw / 2}px)` }} />
          <div style={{ opacity: boxA, position: 'absolute', left: -bd / 2, top: -bh / 2, width: bd, height: bh, background: `linear-gradient(270deg, #2b1a0a, ${inner})`, transform: `rotateY(-90deg) translateZ(${-bw / 2}px)` }} />
          <div style={{ opacity: boxA, position: 'absolute', left: -bw / 2, top: -bd / 2, width: bw, height: bd, background: '#1d1208', transform: `rotateX(90deg) translateZ(${-bh / 2}px)` }} />
          {/* the product (a flat picture standing inside the box) */}
          <div style={{ position: 'absolute', left: -pw / 2, top: -ph / 2, width: pw, height: ph, transform: `translate3d(0, ${prodLocalY - groupDY * 0}px, 0) rotateZ(${wob}deg) scale(${pScale})`, opacity: 1 }}>
            <Product src={imgSrc(asset)} w={pw} aspect={aspect} glow={accent} extra={{ transform: `translateY(${bob}px)` }} />
          </div>
          {/* outside walls (front, left, right) */}
          <div style={{ opacity: boxA, position: 'absolute', left: -bw / 2, top: -bh / 2, width: bw, height: bh, background: `linear-gradient(180deg, ${kraft}, ${dark})`, transform: `translateZ(${bd / 2}px)`, boxShadow: 'inset 0 0 0 2px rgba(0,0,0,0.12)' }}>
            <div style={{ position: 'absolute', left: '8%', right: '8%', top: '12%', height: 6, background: hexA('#000000', 0.16), borderRadius: 3 }} />
            <div style={{ position: 'absolute', left: '40%', right: '40%', top: '46%', height: '8%', background: hexA(accent, 0.85), borderRadius: 6 }} />
          </div>
          <div style={{ opacity: boxA, position: 'absolute', left: -bd / 2, top: -bh / 2, width: bd, height: bh, background: `linear-gradient(90deg, ${dark}, ${kraft})`, transform: `rotateY(-90deg) translateZ(${bw / 2}px)` }} />
          <div style={{ opacity: boxA, position: 'absolute', left: -bd / 2, top: -bh / 2, width: bd, height: bh, background: `linear-gradient(270deg, ${dark}, ${kraft})`, transform: `rotateY(90deg) translateZ(${bw / 2}px)` }} />
          {/* flaps: they open by themselves */}
          <div style={{ position: 'absolute', left: 0, top: -bh / 2, width: 0, height: 0, transformStyle: 'preserve-3d', transform: `translateZ(${bd / 2}px)` }}>
            <Flap o={boxA} len={bd / 2} width={bw} angle={aFront} color={kraft} inner={inner} />
          </div>
          <div style={{ position: 'absolute', left: 0, top: -bh / 2, width: 0, height: 0, transformStyle: 'preserve-3d', transform: `translateZ(${-bd / 2}px) rotateY(180deg)` }}>
            <Flap o={boxA} len={bd / 2} width={bw} angle={aFront} color={kraft} inner={inner} />
          </div>
          <div style={{ position: 'absolute', left: bw / 2, top: -bh / 2, width: 0, height: 0, transformStyle: 'preserve-3d', transform: 'rotateY(90deg)' }}>
            <Flap o={boxA} len={bw / 2} width={bd} angle={aSide} color={dark} inner={inner} />
          </div>
          <div style={{ position: 'absolute', left: -bw / 2, top: -bh / 2, width: 0, height: 0, transformStyle: 'preserve-3d', transform: 'rotateY(-90deg)' }}>
            <Flap o={boxA} len={bw / 2} width={bd} angle={aSide} color={dark} inner={inner} />
          </div>
        </div>
      </div>
      <Sparks x={cx} y={cy - bh * 0.5} s={u - 1.4} n={34} color={accent} seed={11} speed={620} life={1.5} grav={520} from={200} to={340} size={10} />
      <Twinkle cx={cx} cy={H * 0.44} rx={size * 0.9} ry={size * 0.8} u={u} n={9} color="#ffffff" seed={4} />
    </>
  );
};

/* ---------- 2. TABLE RISES, PRODUCT DROPS OR ROLLS ON TOP ---------- */

const TableScene: React.FC<Base & { table: boolean; then: string }> = ({ u, W, H, p, aspect, asset, accent, table, then }) => {
  const size = p.size ?? Math.min(W * 0.5, H * 0.3);
  const tw = size * 1.35;
  const e = tw * 0.26;
  const th = size * 0.85;
  const cx = W / 2;
  const topY = H * (p.y ?? 0.62);
  const tcol = p.tableColor || '#e9edf2';
  const rise = table ? E('outBack', seg(u, 0.05, 0.95)) : 1;
  const tableDY = (1 - rise) * (H * 0.5);
  const pw = Math.min(size * 0.75, H * 0.34 / aspect);
  const ph = pw * aspect;
  const restY = (table ? topY + e * 0.12 : topY + ph * 0.1) - ph / 2;
  const t0 = table ? 1.05 : 0.15;
  let px = cx, py = restY, rot = 0, sx = 1, sy = 1, vis = 1, impact = -1;
  let shadowA = 0;
  if (then === 'roll') {
    const dur = 1.35;
    const q = seg(u, t0, t0 + dur);
    const eq = E('outQuart', q);
    const x0 = -pw * 0.7, total = cx - x0;
    px = lerp(x0, cx, eq);
    rot = -(1 - eq) * 360 * 1.5;
    py = restY + (Math.sin(eq * Math.PI * 2.5) * 6) * (1 - eq);
    if (u < t0) vis = 0;
    shadowA = eq;
    impact = t0 + dur * 0.55;
    void total;
  } else {
    const fall = 0.5;
    const q = seg(u, t0, t0 + fall);
    const startY = restY - H * 0.55;
    const hit = t0 + fall;
    if (u < t0) vis = 0;
    if (u < hit) {
      py = lerp(startY, restY, q * q);
      rot = (1 - q) * -14;
      shadowA = q * 0.7;
    } else {
      const s = u - hit;
      const bounce = Math.max(0, Math.sin(Math.min(1, s / 0.38) * Math.PI)) * (ph * 0.14) * (1 - Math.min(1, s / 0.9));
      py = restY - bounce;
      const sq = Math.exp(-s * 9) * Math.cos(s * 26);
      sy = 1 - 0.16 * sq; sx = 1 + 0.12 * sq;
      shadowA = 1;
    }
    impact = hit;
  }
  const s = u - impact;
  const baseShadowY = (table ? topY + e * 0.18 : topY + ph * 0.1);
  return (
    <>
      <Glow x={cx} y={restY} r={size * 1.25} color={accent} a={0.30 * seg(u, t0, t0 + 0.8)} />
      {table ? (
        <div style={{ position: 'absolute', left: cx - tw / 2, top: topY - e / 2 + tableDY, width: tw, height: th + e }}>
          <div style={{ position: 'absolute', left: 0, top: e / 2, width: tw, height: th, background: `linear-gradient(90deg, ${hexA('#000000', 0.35)} 0%, ${tcol} 22%, #ffffff 46%, ${tcol} 70%, ${hexA('#000000', 0.45)} 100%)`, borderRadius: `0 0 ${tw / 2}px ${tw / 2}px / 0 0 ${e / 2}px ${e / 2}px`, boxShadow: `0 40px 60px ${hexA('#000000', 0.45)}` }} />
          <div style={{ position: 'absolute', left: 0, top: 0, width: tw, height: e, borderRadius: '50%', background: `radial-gradient(ellipse at 50% 40%, #ffffff 0%, ${tcol} 70%, ${hexA(accent, 0.6)} 100%)`, border: `3px solid ${hexA(accent, 0.9)}`, boxShadow: `0 0 30px ${hexA(accent, 0.7)}`, boxSizing: 'border-box' }} />
        </div>
      ) : null}
      <Shadow x={px} y={baseShadowY + tableDY} w={pw * (then === 'roll' ? 0.95 : 0.9) * (0.6 + 0.4 * shadowA)} a={shadowA * vis} />
      {vis ? (
        <div style={{ position: 'absolute', left: px - pw / 2, top: py - ph / 2, width: pw, height: ph, transform: `rotate(${rot}deg) scale(${sx}, ${sy})`, transformOrigin: then === 'roll' ? '50% 55%' : '50% 100%' }}>
          <Product src={imgSrc(asset)} w={pw} aspect={aspect} glow={accent} />
        </div>
      ) : null}
      <Ring x={cx} y={baseShadowY} r={tw * 0.55 * seg(s, 0, 0.7)} color="#ffffff" a={s > 0 ? 0.7 * (1 - seg(s, 0, 0.7)) : 0} w={5} squash={0.28} />
      <Sparks x={cx} y={baseShadowY - 10} s={s} n={26} color={accent} seed={21} speed={420} life={1.1} grav={800} from={200} to={340} size={9} />
      <Twinkle cx={cx} cy={restY} rx={size * 0.85} ry={size * 0.8} u={u} n={8} color="#ffffff" seed={8} />
    </>
  );
};

/* ---------- 3. CAP POPS OFF THE BOTTLE, ROLLS, FIZZ ---------- */

const Cap: React.FC<{ w: number; h: number; color: string }> = ({ w, h, color }) => (
  <div style={{ position: 'relative', width: w, height: h }}>
    <div style={{ position: 'absolute', left: 0, top: h * 0.2, width: w, height: h * 0.8, borderRadius: `${h * 0.18}px ${h * 0.18}px ${h * 0.3}px ${h * 0.3}px`, background: `repeating-linear-gradient(90deg, ${color} 0px, ${color} 5px, ${hexA('#000000', 0.28)} 5px, ${hexA('#000000', 0.28)} 7px)`, boxShadow: 'inset 0 -6px 10px rgba(0,0,0,0.35), inset 0 4px 6px rgba(255,255,255,0.35)' }} />
    <div style={{ position: 'absolute', left: 0, top: 0, width: w, height: h * 0.5, borderRadius: '50%', background: `radial-gradient(ellipse at 40% 30%, #ffffff55, ${color} 55%, ${hexA('#000000', 0.45)} 100%)`, border: `2px solid ${hexA('#000000', 0.25)}`, boxSizing: 'border-box' }} />
  </div>
);

const CapPop: React.FC<Base> = ({ u, W, H, p, aspect, asset, accent }) => {
  const ph = Math.min(H * 0.5, (W * 0.62) * aspect);
  const pw = ph / aspect;
  const cx = W / 2;
  const groundY = H * (p.y ?? 0.68);
  const drop = 0.55;
  const q = seg(u, 0.1, 0.1 + drop);
  const hit = 0.1 + drop;
  let by = groundY - ph;
  let sx = 1, sy = 1;
  if (u < hit) by = lerp(groundY - ph - H * 0.5, groundY - ph, q * q);
  else { const s = u - hit; const sq = Math.exp(-s * 8) * Math.cos(s * 24); sy = 1 - 0.1 * sq; sx = 1 + 0.07 * sq; by = groundY - ph - Math.max(0, Math.sin(Math.min(1, s / 0.3) * Math.PI)) * ph * 0.05 * (1 - Math.min(1, s / 0.6)); }
  const bx = cx - pw / 2;
  const capXf = p.capX ?? 0.5, capYf = p.capY ?? 0.045, capWf = p.capW ?? 0.2;
  const cw = pw * capWf, ch = cw * 0.6;
  const capX0 = bx + pw * capXf, capY0 = by + ph * capYf;
  const tPop = p.popAt ?? 1.55;
  const s = u - tPop;
  const vis = u >= 0.1;
  const capless = !!p.capless;
  // cap flight, simulated with small time steps (same every render)
  let cxp = capX0, cyp = capY0, crot = 0, cflip = 0;
  if (u >= tPop) {
    let vx = W * 0.20, vy = -H * 0.95, x = capX0, y = capY0 - ch * 0.2, r = 0, rv = 900, flip = 0;
    const g = H * 2.6;
    const floorY = groundY + ph * 0.02 - ch * 0.4;
    const dt = 1 / 60;
    let t = 0, rolling = false;
    while (t < s) {
      const stepT = Math.min(dt, s - t);
      if (!rolling) {
        vy += g * stepT; x += vx * stepT; y += vy * stepT; r += rv * stepT; flip += 1200 * stepT;
        if (y >= floorY && vy > 0) {
          y = floorY;
          if (Math.abs(vy) < H * 0.25) { rolling = true; vy = 0; flip = 0; }
          else { vy = -vy * 0.42; vx *= 0.7; rv *= 0.6; }
        }
      } else {
        vx *= Math.pow(0.35, stepT); x += vx * stepT; r += (vx / (cw * 0.5)) * (180 / Math.PI) * stepT; flip *= 0.9;
      }
      t += stepT;
    }
    cxp = x; cyp = y; crot = r; cflip = flip;
  } else if (u >= tPop - 0.5) {
    const k = seg(u, tPop - 0.5, tPop);
    crot = Math.sin(k * 30) * 9 * k;                            // the cap shakes: it is about to pop
    cyp = capY0 - k * 6;
  }
  const popped = u >= tPop;
  const clip = popped && !capless ? Math.min(0.6, capYf + 0.07) : 0;
  const fz = u - tPop;
  const neckX = capX0, neckY = by + ph * (capYf + 0.02);
  return (
    <>
      <Glow x={cx} y={by + ph * 0.5} r={ph * 0.8} color={accent} a={0.30 * seg(u, 0.4, 1.2)} />
      <Shadow x={cx} y={groundY + 6} w={pw * 1.5 * (vis ? 1 : 0)} a={seg(u, 0.1, 0.65) * 0.9} />
      {vis ? (
        <div style={{ position: 'absolute', left: bx, top: by, width: pw, height: ph, transform: `scale(${sx}, ${sy})`, transformOrigin: '50% 100%' }}>
          <Product src={imgSrc(asset)} w={pw} aspect={aspect} glow={accent} clipTop={clip} extra={clip ? { transform: `translateY(${-0}px)` } : undefined} />
          {popped && !capless ? <div style={{ position: 'absolute', left: pw * capXf - cw * 0.55, top: ph * clip - ch * 0.18, width: cw * 1.1, height: ch * 0.4, borderRadius: '50%', background: 'radial-gradient(ellipse, #111 0%, #2a2a2a 60%, #888 100%)', border: '2px solid rgba(255,255,255,0.4)', boxSizing: 'border-box' }} /> : null}
          {!popped && !capless ? <div style={{ position: 'absolute', left: pw * capXf - cw / 2, top: ph * capYf - ch * 0.1, width: cw, height: ch, opacity: 0 }} /> : null}
        </div>
      ) : null}
      {vis && u < tPop && !capless ? null : null}
      {vis ? (
        <div style={{ position: 'absolute', left: cxp - cw / 2, top: cyp - ch / 2, width: cw, height: ch, transform: `rotate(${crot}deg) rotateX(${popped ? cflip : 0}deg)`, perspective: 600 }}>
          <Cap w={cw} h={ch} color={p.capColor || '#d62828'} />
        </div>
      ) : null}
      <Ring x={neckX} y={neckY} r={cw * 2.6 * seg(fz, 0, 0.5)} color="#ffffff" a={fz > 0 ? 0.8 * (1 - seg(fz, 0, 0.5)) : 0} w={5} squash={0.35} />
      <Sparks x={neckX} y={neckY} s={fz} n={30} color="#bfe9ff" seed={31} speed={760} life={1.2} grav={900} from={235} to={305} size={9} />
      <Mist x={neckX} y={neckY} s={fz} />
      <Bubbles x={neckX} y={neckY} s={fz} life={2.2} seed={5} n={34} spread={cw * 1.8} rise={H * 0.28} />
    </>
  );
};

/* ---------- 4. SPIN AND FLOAT, FLY IN ---------- */

const SpinFloat: React.FC<Base & { items: string[] }> = ({ u, W, H, p, aspect, asset, accent, items }) => {
  const size = p.size ?? Math.min(W * 0.62, H * 0.34);
  const pw = Math.min(size, (H * 0.34) / aspect);
  const ph = pw * aspect;
  const cx = W / 2, cy = H * (p.y ?? 0.46);
  const inQ = E('outBack', seg(u, 0.0, 0.8));
  const spin = lerp(-300, 0, E('outQuart', seg(u, 0.0, 1.5)));
  const bob = Math.sin(u * 2.2) * 14;
  const tilt = Math.sin(u * 1.1) * 6;
  const orbit = items.length ? Math.min(W * 0.36, size * 0.95) : 0;
  const els: React.ReactNode[] = [];
  items.forEach((it, i) => {
    const n = items.length;
    const delay = 0.9 + i * 0.22;
    const q = seg(u, delay, delay + 0.9);
    const eq = E('outBack', q);
    const ang = (i / n) * Math.PI * 2 - Math.PI / 2 + Math.sin(u * 0.6) * 0.08;
    const tx = cx + Math.cos(ang) * orbit * 1.05, ty = cy + Math.sin(ang) * Math.max(orbit * 0.9, ph * 0.66) + Math.sin(u * 2 + i) * 9;
    const fromAng = ang + (i % 2 ? 1 : -1) * 1.2;
    const sxp = cx + Math.cos(fromAng) * Math.max(W, H) * 0.8, syp = cy + Math.sin(fromAng) * Math.max(W, H) * 0.8;
    const x = lerp(sxp, tx, E('outExpo', q)), y = lerp(syp, ty, E('outExpo', q));
    const iw = size * 0.36;
    els.push(
      <React.Fragment key={i}>
        <div style={{ position: 'absolute', left: x - iw / 2, top: y - iw / 2, width: iw, transform: `rotate(${(1 - eq) * (i % 2 ? 360 : -360)}deg) scale(${0.3 + 0.7 * eq})`, opacity: clamp(q * 3) }}>
          <Img src={imgSrc(it)} style={{ width: iw, height: 'auto', display: 'block', filter: `drop-shadow(0 12px 18px rgba(0,0,0,0.4)) drop-shadow(0 0 16px ${hexA(accent, 0.4)})` }} />
        </div>
        <Sparks x={tx} y={ty} s={u - (delay + 0.75)} n={12} color={accent} seed={50 + i} speed={300} life={0.9} grav={300} size={7} />
      </React.Fragment>,
    );
  });
  return (
    <>
      <Glow x={cx} y={cy} r={size * 1.2} color={accent} a={0.38 * inQ} />
      <Rays x={cx} y={cy} r={size * 1.5} color={accent} a={0.16 * inQ} rot={u * 14} />
      <Shadow x={cx} y={cy + ph / 2 + 70} w={pw * 0.8 * (1 - bob / 90)} a={0.6 * inQ} />
      <div style={{ position: 'absolute', left: cx - pw / 2, top: cy - ph / 2 + bob, width: pw, height: ph, transform: `perspective(1200px) rotateY(${spin}deg) rotateZ(${tilt}deg) scale(${inQ})` }}>
        <Product src={imgSrc(asset)} w={pw} aspect={aspect} glow={accent} />
      </div>
      {els}
      <Twinkle cx={cx} cy={cy} rx={size * 0.95} ry={size * 0.9} u={u} n={10} color="#ffffff" seed={14} />
    </>
  );
};

/* ---------- stand-alone effects ---------- */

const EffectOnly: React.FC<{ kind: string; u: number; W: number; H: number; accent: string; p: Record<string, any> }> = ({ kind, u, W, H, accent, p }) => {
  const x = p.x ?? W / 2, y = p.fy != null ? H * p.fy : H * 0.5;
  if (kind === 'steam') return <>{[0, 1, 2, 3].map((k) => <Mist key={k} x={x + (k - 1.5) * 70} y={y} s={(u + k * 0.45) % 1.8} color={p.smokeColor || '#ffffff'} />)}</>;
  if (kind === 'splash') {
    const c = p.splashColor || accent;
    return (
      <>
        <Ring x={x} y={y} r={W * 0.2 * seg(u, 0, 0.6)} color={c} a={0.8 * (1 - seg(u, 0, 0.6))} w={7} squash={0.3} />
        <Sparks x={x} y={y} s={u} n={p.count ?? 54} color={c} seed={p.seed ?? 17} speed={p.power ?? 900} life={1.3} grav={2200} size={p.size ?? 13} from={215} to={325} />
      </>
    );
  }
  if (kind === 'fizz') return <Bubbles x={x} y={y} s={u} life={p.life ?? 3} seed={9} n={46} spread={W * 0.4} rise={H * 0.4} />;
  return (
    <>
      <Glow x={x} y={y} r={W * 0.5} color={accent} a={0.6 * Math.sin(clamp(u / 1.2) * Math.PI)} />
      <Rays x={x} y={y} r={W * 0.8} color={accent} a={0.9 * Math.sin(clamp(u / 1.4) * Math.PI)} rot={u * 40} />
      <Ring x={x} y={y} r={W * 0.45 * seg(u, 0, 0.8)} color="#ffffff" a={0.9 * (1 - seg(u, 0, 0.8))} w={8} />
      <Sparks x={x} y={y} s={u} n={46} color={accent} seed={3} speed={900} life={1.6} grav={500} size={11} />
    </>
  );
};

/* ---------- the layer ---------- */

export const MagicLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const u = (ctx.t - layer.start) * Math.min(3, Math.max(0.4, Number(p.speed) || 1));     // speed squeezes or stretches the whole moment to fit the scene
  const kind = String(p.kind || 'spin_float');
  const accent = p.color || ctx.palette.accent || '#f5c451';
  const base: Base = { u, W: ctx.W, H: ctx.H, p, aspect: Number(p.aspect) > 0 ? Number(p.aspect) : 1, asset: String(p.asset || ''), accent };
  const needAsset = !['burst', 'fizz', 'splash', 'steam'].includes(kind);
  return (
    <LayerBox layer={{ ...layer, parallax: 0 }} ctx={ctx} full>
      {() => {
        if (needAsset && !base.asset) return null;
        switch (kind) {
          case 'box_open': return <BoxOpen {...base} />;
          case 'table_rise': return <TableScene {...base} table then={String(p.then || 'drop')} />;
          case 'drop': return <TableScene {...base} table={false} then="drop" />;
          case 'roll_in': return <TableScene {...base} table={false} then="roll" />;
          case 'cap_pop': return <CapPop {...base} />;
          case 'fly_in': return <SpinFloat {...base} items={Array.isArray(p.items) ? p.items.map(String) : []} />;
          case 'burst': case 'fizz': case 'splash': case 'steam': return <EffectOnly kind={kind} u={u} W={ctx.W} H={ctx.H} accent={accent} p={p} />;
          default: return <SpinFloat {...base} items={[]} />;
        }
      }}
    </LayerBox>
  );
};

import React from 'react';
import { Ctx, LayerBox, hexA } from './common';
import { rng } from '../anim';
import type { Layer } from '../types';

export const ParticlesLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const mode = p.mode || 'float';
  const count = Math.min(260, p.count ?? 60);
  const colors: string[] = p.colors && p.colors.length ? p.colors : [ctx.palette.accent || '#f5c451', ctx.palette.primary || '#3b82f6', '#ffffff'];
  const [smin, smax] = p.size || [3, 9];
  const seed = p.seed ?? 5;
  const origin = p.origin || [ctx.W / 2, ctx.H / 2];
  const area = p.area || [ctx.W, ctx.H];
  const life = p.life ?? (mode === 'burst' ? 1.6 : 6);
  const speed = p.speed ?? (mode === 'burst' ? 700 : 40);
  const dirDeg = p.direction ?? (mode === 'rain' ? 90 : -90);
  const spread = p.spread ?? (mode === 'burst' ? 360 : 40);
  const g = p.gravity ?? (mode === 'burst' ? 420 : 0);
  const t = ctx.t - layer.start;
  const glow = p.glow ?? true;
  const els: React.ReactNode[] = [];
  for (let i = 0; i < count; i++) {
    const r = rng(seed * 1000 + i * 7919);
    const r1 = r(), r2 = r(), r3 = r(), r4 = r(), r5 = r();
    const size = smin + (smax - smin) * r1;
    const color = colors[Math.floor(r2 * colors.length) % colors.length];
    let x = 0, y = 0, o = 1, rotate = 0, sx = 1, sy = 1;
    if (mode === 'burst') {
      const age = t - (p.stagger ?? 0.08) * r3;
      if (age < 0 || age > life) continue;
      const u = age / life;
      const ang = ((dirDeg - spread / 2 + spread * r4) * Math.PI) / 180;
      const v = speed * (0.35 + 0.65 * r5);
      x = origin[0] + Math.cos(ang) * v * age * (1 - 0.45 * u);
      y = origin[1] + Math.sin(ang) * v * age * (1 - 0.45 * u) + 0.5 * g * age * age;
      o = (1 - u * u) * 1;
      const k = 1 - u * 0.6;
      sx = sy = k;
    } else if (mode === 'sparkle') {
      x = origin[0] - area[0] / 2 + area[0] * r3;
      y = origin[1] - area[1] / 2 + area[1] * r4;
      const per = p.period ?? 2.2;
      o = Math.pow(Math.max(0, Math.sin(((t / per) + r5) * Math.PI * 2)), 3);
      sx = sy = 0.4 + 0.9 * o;
    } else if (mode === 'rain') {
      const u = ((t / life) * (0.6 + 0.8 * r5) + r4) % 1;
      x = origin[0] - area[0] / 2 + area[0] * r3;
      y = origin[1] - area[1] / 2 + area[1] * u;
      o = Math.sin(u * Math.PI) * 0.9;
      rotate = dirDeg - 90; sy = 6;
    } else if (mode === 'stream') {
      const u = ((t / life) * (0.7 + 0.6 * r5) + r4) % 1;
      const ang = ((dirDeg - spread / 2 + spread * r3) * Math.PI) / 180;
      x = origin[0] + Math.cos(ang) * speed * u * life;
      y = origin[1] + Math.sin(ang) * speed * u * life;
      o = Math.sin(u * Math.PI);
    } else {
      // float: slow drifting dust / bokeh
      const u = ((t / life) * (0.5 + 0.8 * r5) + r4) % 1;
      x = origin[0] - area[0] / 2 + area[0] * r3 + Math.sin(t * (0.4 + r5) + r1 * 6.28) * 28;
      y = origin[1] + area[1] / 2 - area[1] * u;
      o = Math.sin(u * Math.PI) * (0.35 + 0.65 * r2);
    }
    if (o <= 0.01) continue;
    els.push(
      <div
        key={i}
        style={{
          position: 'absolute', left: x - size / 2, top: y - size / 2, width: size, height: size, borderRadius: '50%', opacity: o * (p.opacity ?? 1),
          background: color, transform: `rotate(${rotate}deg) scale(${sx}, ${sy})`,
          boxShadow: glow ? `0 0 ${size * 2.2}px ${size * 0.6}px ${hexA(color, 0.55)}` : undefined,
        }}
      />,
    );
  }
  return <LayerBox layer={layer} ctx={ctx} full>{() => <>{els}</>}</LayerBox>;
};

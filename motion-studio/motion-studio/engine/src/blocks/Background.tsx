import React from 'react';
import { Img, staticFile } from 'remotion';
import { hexA, Ctx } from './common';
import { rng } from '../anim';
import type { Background as BG } from '../types';

export const Background: React.FC<{ bg?: BG; ctx: Ctx }> = ({ bg, ctx }) => {
  const b = bg || {};
  const colors = b.colors && b.colors.length ? b.colors : ['#06070d', '#10182f'];
  const { t, W, H } = ctx;
  let base: React.CSSProperties = {};
  if (b.type === 'solid') base = { background: colors[0] };
  else if (b.type === 'radial') base = { background: `radial-gradient(circle at 50% 38%, ${colors.join(', ')})` };
  else base = { background: `linear-gradient(${b.angle ?? 160}deg, ${colors.join(', ')})` };
  const orbs = Math.min(12, b.orbs ?? 0);
  const r = rng((b.seed ?? 7) + 11);
  const orbEls = [];
  for (let i = 0; i < orbs; i++) {
    const x0 = r() * W, y0 = r() * H, size = (0.18 + r() * 0.3) * Math.max(W, H), sp = 0.15 + r() * 0.25, ph = r() * 6.28;
    const x = x0 + Math.sin(t * sp + ph) * W * 0.06, y = y0 + Math.cos(t * sp * 0.8 + ph) * H * 0.04;
    orbEls.push(
      <div key={i} style={{ position: 'absolute', left: x - size / 2, top: y - size / 2, width: size, height: size, borderRadius: '50%', background: `radial-gradient(circle, ${hexA(b.orbColor || colors[colors.length - 1], 0.35)}, transparent 68%)`, filter: 'blur(30px)' }} />,
    );
  }
  return (
    <div style={{ position: 'absolute', inset: 0, overflow: 'hidden', ...base }}>
      {b.type === 'image' && b.asset ? (
        <>
          <Img src={staticFile('assets/' + b.asset)} style={{ position: 'absolute', inset: -40, width: W + 80, height: H + 80, objectFit: 'cover', filter: `blur(${b.blur ?? 0}px)`, transform: `scale(${1 + t * 0.01})` }} />
          <div style={{ position: 'absolute', inset: 0, background: 'rgba(0,0,0,0.35)' }} />
        </>
      ) : null}
      {orbEls}
      {b.vignette ? <div style={{ position: 'absolute', inset: 0, background: `radial-gradient(ellipse at center, rgba(0,0,0,0) 45%, rgba(0,0,0,${b.vignette}) 100%)` }} /> : null}
      {b.grain ? (
        <svg style={{ position: 'absolute', inset: 0, width: '100%', height: '100%', opacity: b.grain, mixBlendMode: 'overlay' }}>
          <filter id="grain"><feTurbulence type="fractalNoise" baseFrequency="0.9" numOctaves="2" seed={ctx.frame % 9} /></filter>
          <rect width="100%" height="100%" filter="url(#grain)" />
        </svg>
      ) : null}
    </div>
  );
};

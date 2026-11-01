import React from 'react';
import { useCurrentFrame, useVideoConfig } from 'remotion';
import { cameraAt, layerFx, num } from '../anim';
import type { CameraKey, Layer } from '../types';

export const hexA = (color: string | undefined, a: number): string => {
  const c = String(color || '#ffffff').trim();
  const m = c.match(/^#([0-9a-f]{3}|[0-9a-f]{6})$/i);
  if (!m) return c;
  let h = m[1];
  if (h.length === 3) h = h.split('').map((x) => x + x).join('');
  const n = parseInt(h, 16);
  return `rgba(${(n >> 16) & 255},${(n >> 8) & 255},${n & 255},${Math.max(0, Math.min(1, a))})`;
};

export const glowFilter = (g: any): string => {
  if (!g) return '';
  const color = g.color || '#6aa9ff';
  const b = g.blur ?? 24;
  const o = g.opacity ?? 0.8;
  return `drop-shadow(0 0 ${b * 0.35}px ${hexA(color, o)}) drop-shadow(0 0 ${b}px ${hexA(color, o * 0.7)}) drop-shadow(0 0 ${b * 2}px ${hexA(color, o * 0.4)})`;
};

export const shadowFilter = (s: any): string => {
  if (!s) return '';
  const o = typeof s === 'object' ? s : {};
  return `drop-shadow(0 ${o.y ?? 24}px ${o.blur ?? 40}px rgba(0,0,0,${o.opacity ?? 0.45}))`;
};

export type Ctx = { t: number; frame: number; fps: number; W: number; H: number; camera?: CameraKey[]; palette: Record<string, string> };

export const useCtx = (camera: CameraKey[] | undefined, palette: Record<string, string>): Ctx => {
  const frame = useCurrentFrame();
  const { fps, width, height } = useVideoConfig();
  return { t: frame / fps, frame, fps, W: width, H: height, camera, palette };
};

/**
 * PHYSICS: props.physics = {from:[x,y], vx, vy, gravity (px/s2, default 2600), floor (y where it lands), bounce (0-1, default .4), spin (deg/s while flying), radius (px, rolls when it lands), friction}.
 * The object flies, falls, bounces on the floor and rolls to a stop. Times are counted from the layer's start. Same result in every render.
 */
const physicsAt = (layer: Layer, t: number) => {
  const p: any = layer.props!.physics;
  const from = Array.isArray(p.from) ? p.from : [layer.x ?? 0, layer.y ?? 0];
  const g = p.gravity ?? 2600, bounce = p.bounce ?? 0.4, floor = p.floor ?? 1e9, radius = p.radius ?? 0, fr = p.friction ?? 0.35;
  let spin = p.spin ?? 0, x = from[0], y = from[1], vx = p.vx ?? 0, vy = p.vy ?? 0, rot = p.rot0 ?? 0, rolling = false;
  const total = Math.max(0, t - layer.start);
  const dt = 1 / 60;
  let tt = 0, n = 0;
  while (tt < total && n++ < 900) {
    const st = Math.min(dt, total - tt);
    if (!rolling) {
      vy += g * st; x += vx * st; y += vy * st; rot += spin * st;
      if (y >= floor && vy > 0) {
        y = floor;
        if (Math.abs(vy) < 260) { rolling = true; vy = 0; }
        else { vy = -vy * bounce; vx *= 0.8; spin *= 0.6; }
      }
    } else {
      vx *= Math.pow(fr, st); x += vx * st;
      if (radius > 0) rot += (vx / radius) * (180 / Math.PI) * st; else rot += spin * st * 0.2;
    }
    tt += st;
  }
  return { x, y, rot };
};

/** Positions a layer, applies camera, enter/exit effects, pulse and animated x/y/scale/rotate/opacity. */
export const LayerBox: React.FC<{ layer: Layer; ctx: Ctx; full?: boolean; three?: boolean; children: (fx: ReturnType<typeof layerFx>) => React.ReactNode }> = ({ layer, ctx, full, three, children }) => {
  const { t } = ctx;
  if (t < layer.start - 1e-6 || t > layer.end + 1e-6) return null;
  const fx = layerFx(layer, t);
  const par = layer.parallax ?? 1;
  const cam = cameraAt(ctx.camera, t);
  const camT = `translate(${-cam.x * par}px, ${-cam.y * par}px) scale(${1 + (cam.scale - 1) * par}) rotate(${cam.rotate * par}deg)`;
  const ph = layer.props && layer.props.physics ? physicsAt(layer, t) : null;   // a thrown / dropped / bouncing / rolling object: the studio simulates it
  const wg = layer.props && layer.props.wiggle;                                  // {pos, rot, freq}: a living shake (hand-held look, shivering, vibration)
  const wob = (k: number) => (wg ? Math.sin(t * (wg.freq ?? 3) * 6.2832 + k * 1.7) * 0.6 + Math.sin(t * (wg.freq ?? 3) * 9.7 + k * 4.1) * 0.4 : 0);
  const x = (ph ? ph.x : num(layer, 'x', t, layer.x ?? ctx.W / 2)) + (wg ? wob(1) * (wg.pos ?? 0) : 0);
  const y = (ph ? ph.y : num(layer, 'y', t, layer.y ?? ctx.H / 2)) + (wg ? wob(2) * (wg.pos ?? 0) : 0);
  const sc = num(layer, 'scale', t, 1);
  const sX = num(layer, 'scaleX', t, 1), sY = num(layer, 'scaleY', t, 1);
  const rX = num(layer, 'rotateX', t, 0), rY = num(layer, 'rotateY', t, 0), skX = num(layer, 'skewX', t, 0);
  const org = layer.props && Array.isArray(layer.props.origin) ? `${layer.props.origin[0]}% ${layer.props.origin[1]}%` : undefined;   // the pivot (hinge) of rotations and scaling
  const rot = num(layer, 'rotate', t, 0) + (ph ? ph.rot : 0) + (wg ? wob(3) * (wg.rot ?? 0) : 0);
  const op = num(layer, 'opacity', t, 1) * fx.opacity;
  const pul = layer.props && layer.props.pulse;
  const pulse = pul ? 1 + (pul.amount ?? 0.05) * Math.sin(((t - layer.start) / (pul.period ?? 1.6)) * Math.PI * 2) : 1;
  const blur = Math.max(fx.blur, num(layer, 'blur', t, 0));
  const clip = fx.clip < 1 ? `inset(-50% ${(1 - fx.clip) * 100}% -50% -50%)` : undefined;
  if (full) {
    return (
      <div style={{ position: 'absolute', inset: 0, transform: camT, transformOrigin: '50% 50%', opacity: op, zIndex: layer.z ?? 0, filter: blur ? `blur(${blur}px)` : undefined }}>
        {children(fx)}
      </div>
    );
  }
  return (
    <div style={{ position: 'absolute', inset: 0, transform: camT, transformOrigin: '50% 50%', zIndex: layer.z ?? 0, pointerEvents: 'none' }}>
      <div
        style={{
          position: 'absolute', left: x, top: y,
          transform: `translate(-50%, -50%) translate(${fx.dx}px, ${fx.dy}px) ${rX || rY ? 'perspective(1400px) ' : ''}rotate(${rot + fx.rotate}deg)${rX ? ` rotateX(${rX}deg)` : ''}${rY ? ` rotateY(${rY}deg)` : ''}${skX ? ` skewX(${skX}deg)` : ''} scale(${sc * fx.scale * pulse * sX}, ${sc * fx.scale * pulse * sY})`,
          transformOrigin: org, transformStyle: three ? 'preserve-3d' : undefined,
          opacity: op, filter: blur ? `blur(${blur}px)` : undefined, clipPath: clip,
        }}
      >
        {children(fx)}
      </div>
    </div>
  );
};

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

/** Positions a layer, applies camera, enter/exit effects, pulse and animated x/y/scale/rotate/opacity. */
export const LayerBox: React.FC<{ layer: Layer; ctx: Ctx; full?: boolean; children: (fx: ReturnType<typeof layerFx>) => React.ReactNode }> = ({ layer, ctx, full, children }) => {
  const { t } = ctx;
  if (t < layer.start - 1e-6 || t > layer.end + 1e-6) return null;
  const fx = layerFx(layer, t);
  const par = layer.parallax ?? 1;
  const cam = cameraAt(ctx.camera, t);
  const camT = `translate(${-cam.x * par}px, ${-cam.y * par}px) scale(${1 + (cam.scale - 1) * par}) rotate(${cam.rotate * par}deg)`;
  const x = num(layer, 'x', t, layer.x ?? ctx.W / 2);
  const y = num(layer, 'y', t, layer.y ?? ctx.H / 2);
  const sc = num(layer, 'scale', t, 1);
  const rot = num(layer, 'rotate', t, 0);
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
          transform: `translate(-50%, -50%) translate(${fx.dx}px, ${fx.dy}px) rotate(${rot + fx.rotate}deg) scale(${sc * fx.scale * pulse})`,
          opacity: op, filter: blur ? `blur(${blur}px)` : undefined, clipPath: clip,
        }}
      >
        {children(fx)}
      </div>
    </div>
  );
};

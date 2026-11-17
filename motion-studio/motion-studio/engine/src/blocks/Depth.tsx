import React from 'react';
import { Img, staticFile } from 'remotion';
import { Ctx, LayerBox, glowFilter, shadowFilter } from './common';
import { ease } from '../anim';
import type { Layer } from '../types';

/**
 * DEPTH: one flat picture becomes a real-looking 3D scene (2.5D parallax, the "photo comes alive" look of After Effects).
 * The studio has cut the picture into depth slices (props.layers = [{asset, depth}], depth 0 = far background ... 1 = nearest, with the hidden parts painted in).
 * The camera then moves through it: near slices travel more than far slices, so the subject separates from the background like in real 3D.
 * props: width (px), aspect (height/width of the picture), move: orbit | push | pull | drift | pan | tilt | rise (default orbit), amount (how far, 0.3-2, default 1),
 *        zoom (extra push in %, default 6), loop (true: keep circling for the whole layer), focus (0-1, which depth stays still, default 0.5), blurFar (px of blur on the far slice, default 0),
 *        glow / shadow (on the whole scene). The move runs from the layer's start to its end, eased by props.ease (default inOutQuad).
 */
const pathAt = (move: string, u: number, loop: boolean, tt: number) => {
  // returns the camera offset in "unit" coordinates: x, y in [-1, 1] and a push amount in [0, 1]
  const a = loop ? tt * Math.PI * 2 : u * Math.PI;
  switch (move) {
    case 'push': return { x: 0, y: 0, z: u };
    case 'pull': return { x: 0, y: 0, z: 1 - u };
    case 'drift': return { x: (loop ? Math.sin(a) : u * 2 - 1) * 0.8, y: (loop ? Math.cos(a * 0.7) : 0) * 0.25, z: u * 0.3 };
    case 'pan': return { x: u * 2 - 1, y: 0, z: u * 0.15 };
    case 'tilt': return { x: 0, y: u * 2 - 1, z: u * 0.15 };
    case 'rise': return { x: 0, y: 1 - u * 2, z: u * 0.25 };
    default: return { x: Math.sin(loop ? a : (u - 0.5) * Math.PI), y: Math.sin((loop ? a : u * Math.PI) * 0.5) * 0.35 - 0.1, z: u * 0.4 };   // orbit
  }
};

export const DepthLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const { t } = ctx;
  const W = Number(p.width) || ctx.W * 0.9;
  const H = W * (Number(p.aspect) || 1);
  const slices: { asset: string; depth: number }[] = (Array.isArray(p.layers) ? p.layers : []).filter((s: any) => s && s.asset);
  const dur = Math.max(0.1, layer.end - layer.start);
  const loop = !!p.loop;
  const tt = (t - layer.start) / dur;
  const u = ease(p.ease || 'inOutQuad', Math.min(1, Math.max(0, tt)));
  const cam = pathAt(String(p.move || 'orbit'), u, loop, loop ? (t - layer.start) / Math.max(1, Number(p.period) || 6) : tt);
  const amt = (Number(p.amount) || 1) * W * 0.045;          // pixels the nearest slice travels
  const focus = p.focus === undefined ? 0.5 : Number(p.focus);
  const zoom = (p.zoom === undefined ? 6 : Number(p.zoom)) / 100;
  const filt = [glowFilter(p.glow), shadowFilter(p.shadow)].filter(Boolean).join(' ');
  // the far slice is drawn a little larger so its edges never show when the slices move
  const margin = 1 + (Math.abs(Number(p.amount) || 1) * 0.07 + zoom);
  return (
    <LayerBox layer={layer} ctx={ctx}>
      {() => (
        <div style={{ position: 'relative', width: W, height: H, filter: filt || undefined }}>
          <div style={{ position: 'absolute', inset: 0, overflow: p.overflow === 'visible' ? 'visible' : 'hidden' }}>
            {slices.map((s, i) => {
              const d = Math.min(1, Math.max(0, Number(s.depth)));
              const rel = d - focus;                                           // + near, - far
              const dx = -cam.x * amt * rel * 2;
              const dy = -cam.y * amt * rel * 2;
              const sc = (i === 0 ? margin : 1 + 0.02) * (1 + zoom * cam.z * (0.35 + d * 0.9));
              const blur = i === 0 && p.blurFar ? Number(p.blurFar) : 0;
              return (
                <Img
                  key={s.asset + i}
                  src={staticFile('assets/' + s.asset)}
                  onError={() => console.error('PICTURE FAILED TO LOAD: ' + s.asset)}
                  style={{ position: 'absolute', left: 0, top: 0, width: '100%', height: '100%', transform: `translate(${dx}px, ${dy}px) scale(${sc})`, transformOrigin: '50% 55%', filter: blur ? `blur(${blur}px)` : undefined }}
                />
              );
            })}
          </div>
        </div>
      )}
    </LayerBox>
  );
};

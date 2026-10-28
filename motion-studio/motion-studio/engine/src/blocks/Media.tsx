import React from 'react';
import { Img, OffthreadVideo, Sequence, staticFile } from 'remotion';
import { Ctx, LayerBox, glowFilter, shadowFilter, hexA } from './common';
import { num, sampleTrack } from '../anim';
import type { Layer } from '../types';

const filters = (p: any) => [glowFilter(p.glow), shadowFilter(p.shadow)].filter(Boolean).join(' ');

/** Shared frame for images and videos: size, rounded corners, border, glow, shadow, Ken Burns, light sheen. */
const Frame: React.FC<{ layer: Layer; ctx: Ctx; src: string; video?: boolean }> = ({ layer, ctx, src, video }) => {
  const p = layer.props || {};
  const { t } = ctx;
  const w = num(layer, 'width', t, p.width ?? 600);
  const h = p.height ? num(layer, 'height', t, p.height) : undefined;
  const radius = p.radius ?? 0;
  const fit = p.fit || 'contain';
  const kb = p.kenBurns;
  const prog = Math.min(1, Math.max(0, (t - layer.start) / Math.max(0.1, layer.end - layer.start)));
  const kbScale = kb ? (kb.from ?? 1) + ((kb.to ?? 1.12) - (kb.from ?? 1)) * prog : 1;
  const kbX = kb ? (kb.panX ?? 0) * prog : 0;
  const kbY = kb ? (kb.panY ?? 0) * prog : 0;
  const sheen = layer.anim && layer.anim.sheen ? sampleTrack(layer.anim.sheen, t, -1) : -1;
  const media = video ? (
    <Sequence from={Math.round(layer.start * ctx.fps)}>
      <OffthreadVideo src={src} muted startFrom={Math.round((p.srcStart ?? 0) * ctx.fps)} playbackRate={p.playbackRate ?? 1} style={{ width: '100%', height: '100%', objectFit: fit }} />
    </Sequence>
  ) : (
    <Img src={src} style={{ width: '100%', height: h ? '100%' : 'auto', objectFit: fit, display: 'block', transform: `scale(${kbScale}) translate(${kbX}px, ${kbY}px)` }} />
  );
  return (
    <div style={{ position: 'relative', width: w, height: h, filter: filters(p) }}>
      <div style={{ width: '100%', height: h ? '100%' : undefined, borderRadius: radius, overflow: kb || radius || video ? 'hidden' : 'visible', border: p.border ? `${p.border.width ?? 3}px solid ${p.border.color ?? '#fff'}` : undefined, boxSizing: 'border-box', background: p.backdrop }}>{media}</div>
      {sheen >= 0 && sheen <= 1 ? (
        <div
          style={{
            position: 'absolute', inset: 0, pointerEvents: 'none', mixBlendMode: 'screen',
            WebkitMaskImage: video ? undefined : `url(${src})`, maskImage: video ? undefined : `url(${src})`, WebkitMaskSize: '100% 100%', maskSize: '100% 100%', WebkitMaskRepeat: 'no-repeat', maskRepeat: 'no-repeat',
            background: `linear-gradient(105deg, transparent ${sheen * 160 - 40}%, ${hexA(p.sheenColor || '#ffffff', 0.55)} ${sheen * 160 - 20}%, transparent ${sheen * 160}%)`,
          }}
        />
      ) : null}
    </div>
  );
};

export const ImageLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => (
  <LayerBox layer={layer} ctx={ctx}>{() => <Frame layer={layer} ctx={ctx} src={staticFile('assets/' + (layer.props || {}).asset)} />}</LayerBox>
);
export const VideoLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => (
  <LayerBox layer={layer} ctx={ctx}>{() => <Frame layer={layer} ctx={ctx} video src={staticFile('assets/' + (layer.props || {}).asset)} />}</LayerBox>
);

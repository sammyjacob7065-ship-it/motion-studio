import React from 'react';
import { AbsoluteFill } from 'remotion';
import { Background } from './blocks/Background';
import { useCtx } from './blocks/common';
import { ImageLayer, VideoLayer } from './blocks/Media';
import { TextLayer, CounterLayer } from './blocks/Text';
import { ShapeLayer, IconLayer, LineLayer, TransitionLayer } from './blocks/Graphics';
import { ParticlesLayer } from './blocks/Particles';
import { CaptionsLayer } from './blocks/Captions';
import type { Layer, Timeline } from './types';

const DEFAULT_PALETTE = { primary: '#3b82f6', accent: '#f5c451', text: '#ffffff' };

export const Scene: React.FC<{ timeline: Timeline }> = ({ timeline }) => {
  const palette = { ...DEFAULT_PALETTE, ...(timeline.palette || {}) };
  const ctx = useCtx(timeline.camera, palette);
  const layers = timeline.layers.map((l, i) => ({ l, i })).sort((a, b) => (a.l.z ?? 0) - (b.l.z ?? 0) || a.i - b.i);
  const render = (layer: Layer) => {
    switch (layer.type) {
      case 'image': return <ImageLayer layer={layer} ctx={ctx} />;
      case 'video': return <VideoLayer layer={layer} ctx={ctx} />;
      case 'text': return <TextLayer layer={layer} ctx={ctx} />;
      case 'counter': return <CounterLayer layer={layer} ctx={ctx} />;
      case 'shape': return <ShapeLayer layer={layer} ctx={ctx} />;
      case 'icon': return <IconLayer layer={layer} ctx={ctx} />;
      case 'line': return <LineLayer layer={layer} ctx={ctx} />;
      case 'particles': return <ParticlesLayer layer={layer} ctx={ctx} />;
      case 'captions': return <CaptionsLayer layer={layer} ctx={ctx} />;
      case 'transition': return <TransitionLayer layer={layer} ctx={ctx} />;
      default: return null;
    }
  };
  return (
    <AbsoluteFill style={{ background: '#000', overflow: 'hidden' }}>
      <Background bg={timeline.background} ctx={ctx} />
      {layers.map(({ l }) => (
        <React.Fragment key={l.id}>{render(l)}</React.Fragment>
      ))}
    </AbsoluteFill>
  );
};

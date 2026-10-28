import React from 'react';
import { Composition } from 'remotion';
import { Scene } from './Scene';
import type { Timeline } from './types';

const SAMPLE: Timeline = {
  width: 1080, height: 1920, fps: 30, duration: 4,
  background: { type: 'gradient', colors: ['#050b1f', '#0b2a6f'], angle: 160, vignette: 0.45, grain: 0.06 },
  layers: [{ id: 't1', type: 'text', start: 0.3, end: 4, props: { text: 'Motion Studio', size: 110, mode: 'words' } }],
};

export const Root: React.FC = () => (
  <Composition
    id="Main"
    component={Scene as any}
    width={1080}
    height={1920}
    fps={30}
    durationInFrames={120}
    defaultProps={{ timeline: SAMPLE }}
    calculateMetadata={({ props }: any) => {
      const t: Timeline = props.timeline;
      return { width: t.width, height: t.height, fps: t.fps, durationInFrames: Math.max(1, Math.ceil(t.duration * t.fps)) };
    }}
  />
);

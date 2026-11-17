import React from 'react';
import { Img, staticFile } from 'remotion';
import { Ctx, LayerBox } from './common';
import { num } from '../anim';
import type { Layer } from '../types';

/**
 * SOLID3D: a real turnable 3D object made from a cut-out picture (transparent PNG). Animate it with the layer tracks rotateY (turn), rotateX (tip), rotate, scale, x, y.
 *   mode "slab"     phones, boxes, cards, books, shoes, flat products: a thick slab. Front = the picture, back = props.back picture (or the picture mirrored and darker),
 *                   the rim is built from many thin slices of the same outline, so the thickness is real when it turns.
 *   mode "cylinder" bottles, cans, jars, tubes, cups: the picture is wrapped round a round body, so the label travels round and the sides curve away when it turns. props.back = the back of the label.
 * props: asset, width (px), aspect (height/width), mode, thickness (px, slab, default 9% of width), edgeColor (slab rim), back (picture), slices (slab, default 26),
 *        light (0-1, how much the shading follows the turn, default 0.55), shine (0-1, a moving highlight).
 * A 3D object cannot carry a CSS glow/shadow filter (it would flatten it): put a soft shadow ellipse (shape circle) under it and a glow shape behind it instead.
 */
const clamp = (x: number, a: number, b: number) => Math.min(b, Math.max(a, x));

const Slab: React.FC<{ src: string; back?: string; w: number; h: number; th: number; edge: string; slices: number; rotY: number; light: number; shine: number }> = ({ src, back, w, h, th, edge, slices, rotY, light, shine }) => {
  const rad = (rotY * Math.PI) / 180;
  const front = Math.cos(rad);                                   // 1 facing us, -1 turned away
  const lf = 1 - light * (1 - Math.abs(front)) * 0.9;            // the face darkens as it turns edge-on
  const sh = shine > 0 ? Math.max(0, Math.sin(rad * 1.0 + 0.6)) * shine : 0;
  const mask = { WebkitMaskImage: `url(${src})`, maskImage: `url(${src})`, WebkitMaskSize: '100% 100%', maskSize: '100% 100%' } as React.CSSProperties;
  const rim = [];
  for (let i = 0; i < slices; i++) {
    const z = -th / 2 + (th * (i + 0.5)) / slices;
    const k = 0.78 + 0.22 * Math.sin((i / (slices - 1)) * Math.PI);   // a rounded edge: lighter in the middle of the rim
    rim.push(<div key={i} style={{ position: 'absolute', inset: 0, background: edge, filter: `brightness(${k * (0.8 + 0.2 * Math.abs(Math.sin(rad)))})`, transform: `translateZ(${z}px)`, ...mask }} />);
  }
  return (
    <div style={{ position: 'absolute', inset: 0, transformStyle: 'preserve-3d' }}>
      {rim}
      <div style={{ position: 'absolute', inset: 0, transform: `translateZ(${-th / 2 - 0.5}px) rotateY(180deg)`, backfaceVisibility: 'hidden', filter: `brightness(${0.72 * lf})` }}>
        <Img src={back || src} style={{ width: '100%', height: '100%', display: 'block' }} />
      </div>
      <div style={{ position: 'absolute', inset: 0, transform: `translateZ(${th / 2 + 0.5}px)`, backfaceVisibility: 'hidden', filter: `brightness(${lf})` }}>
        <Img src={src} style={{ width: '100%', height: '100%', display: 'block' }} />
        {sh > 0 ? <div style={{ position: 'absolute', inset: 0, mixBlendMode: 'screen', ...mask, background: `linear-gradient(105deg, transparent ${30 - sh * 30}%, rgba(255,255,255,${0.5 * sh}) ${50 - sh * 10}%, transparent ${70 + sh * 20}%)` }} /> : null}
      </div>
    </div>
  );
};

const Cylinder: React.FC<{ src: string; back?: string; w: number; h: number; rotY: number; light: number; shine: number }> = ({ src, back, w, h, rotY, light, shine }) => {
  // The picture is the FRONT VIEW of a round body of radius w/2: strip j shows picture columns [j*sw, (j+1)*sw] and stands at the angle where that column sits on the body
  // (x = R sin(angle)), so at rest the object is exactly the supplied picture; when it turns, the label wraps round and the sides curve away.
  const N = 72;
  const R = w / 2;
  const wrap = ((((rotY + 180) % 360) + 360) % 360) - 180;       // -180..180
  const ramp = Math.min(1, Math.abs(wrap) / 25);                 // shading and highlight fade in as it starts to turn, so there is no pop
  if (Math.abs(wrap) < 0.4) return <div style={{ position: 'absolute', left: 0, top: 0, width: w, height: h }}><Img src={src} style={{ width: '100%', height: '100%', display: 'block' }} /></div>;   // at rest: exactly the supplied picture, no seams
  light = light * ramp; shine = shine * ramp;
  const sw = w / N;
  const strips: React.ReactNode[] = [];
  for (let side = 0; side < 2; side++) {                          // 0 = front half (the picture), 1 = back half (props.back, or the picture again, darker)
    for (let j = 0; j < N; j++) {
      const x0 = j * sw, x1 = (j + 1) * sw;
      const t0 = Math.asin(Math.min(1, Math.max(-1, (x0 - R) / R))), t1 = Math.asin(Math.min(1, Math.max(-1, (x1 - R) / R)));
      const ang0 = ((t0 + t1) / 2) * (180 / Math.PI);
      const ang = side === 0 ? ang0 : 180 - ang0;
      const chord = Math.max(0.5, 2 * R * Math.sin((t1 - t0) / 2));
      const world = ang + rotY;
      const c = Math.cos((world * Math.PI) / 180);
      if (c < -0.05) continue;                                    // behind the body: never seen
      const lum = (1 - light * (1 - Math.max(0, c)) * 0.85) * (side === 0 || back ? 1 : 0.8);
      const spec = shine > 0 ? Math.pow(Math.max(0, Math.cos(((world - 24) * Math.PI) / 180)), 16) * shine : 0;
      const img = side === 0 ? src : back || src;
      const colL = side === 0 || !back ? x0 : w - x1;               // a back picture is read from behind: its columns run the other way
      const k = chord / sw;                                       // the column is stretched to the width of its strip
      strips.push(
        <div key={side + '_' + j} style={{ position: 'absolute', left: R - chord / 2, top: 0, width: chord + 1.4, height: h, transform: `rotateY(${ang}deg) translateZ(${R}px)`, backfaceVisibility: 'hidden', overflow: 'hidden', filter: `brightness(${lum + spec})` }}>
          <div style={{ position: 'absolute', inset: 0, transform: side === 1 && !back ? 'scaleX(-1)' : undefined }}>
            <Img src={img} style={{ position: 'absolute', top: 0, left: -colL * k, width: w * k, height: h, maxWidth: 'none' }} />
          </div>
        </div>,
      );
    }
  }
  return <div style={{ position: 'absolute', left: 0, top: 0, width: w, height: h, transformStyle: 'preserve-3d' }}>{strips}</div>;
};

export const Solid3DLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const { t } = ctx;
  const w = num(layer, 'width', t, Number(p.width) || 600);
  const h = w * (Number(p.aspect) || 1);
  const src = staticFile('assets/' + p.asset);
  const back = p.back ? staticFile('assets/' + p.back) : undefined;
  const rotY = num(layer, 'rotateY', t, 0);
  const mode = String(p.mode || 'slab');
  const light = p.light === undefined ? 0.55 : clamp(Number(p.light), 0, 1);
  const shine = p.shine === undefined ? 0.35 : clamp(Number(p.shine), 0, 1);
  return (
    <LayerBox layer={layer} ctx={ctx} three>
      {() => (
        <div style={{ position: 'relative', width: w, height: h, transformStyle: 'preserve-3d' }}>
          {mode === 'cylinder'
            ? <Cylinder src={src} back={back} w={w} h={h} rotY={rotY} light={light} shine={shine} />
            : <Slab src={src} back={back} w={w} h={h} th={Number(p.thickness) || w * 0.09} edge={String(p.edgeColor || '#2a2a2a')} slices={Math.max(4, Math.min(64, Math.round(Number(p.slices) || (Number(p.thickness) || w * 0.09) / 1.1)))} rotY={rotY} light={light} shine={shine} />}
        </div>
      )}
    </LayerBox>
  );
};

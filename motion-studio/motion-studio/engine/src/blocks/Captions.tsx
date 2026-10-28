import React from 'react';
import { Ctx, LayerBox, hexA } from './common';
import { fontFamily } from '../fonts';
import { ease } from '../anim';
import type { Layer } from '../types';

type W = { w: string; s: number; e: number };

/** Word-by-word captions: shows a few words at a time and highlights the word being spoken. */
export const CaptionsLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const words: W[] = (p.words || []).filter((x: W) => x && x.w);
  const per = Math.max(1, p.group ?? 3);
  const groups: W[][] = [];
  for (let i = 0; i < words.length; i += per) groups.push(words.slice(i, i + per));
  const t = ctx.t;
  const g = groups.find((gr, i) => {
    const s = gr[0].s - 0.04;
    const nextS = groups[i + 1] ? groups[i + 1][0].s - 0.04 : Infinity;
    const e = Math.min(gr[gr.length - 1].e + 0.35, nextS);
    return t >= s && t < e;
  });
  const size = p.size ?? 74;
  const y = p.y ?? ctx.H * 0.72;
  const col = p.color || '#ffffff';
  const hi = p.highlightColor || ctx.palette.accent || '#f5c451';
  return (
    <LayerBox layer={{ ...layer, parallax: 0 }} ctx={ctx} full>
      {() =>
        g ? (
          <div style={{ position: 'absolute', left: 0, width: ctx.W, top: y, transform: 'translateY(-50%)', display: 'flex', justifyContent: 'center' }}>
            <div style={{ maxWidth: ctx.W * 0.86, textAlign: 'center', fontFamily: fontFamily(p.font || 'Montserrat'), fontWeight: p.weight ?? 800, fontSize: size, lineHeight: 1.18, textTransform: p.uppercase === false ? undefined : 'uppercase', letterSpacing: 1 }}>
              {g.map((wd, i) => {
                const active = t >= wd.s && t < wd.e + 0.02;
                const pop = active ? 1 + 0.14 * ease('outBack', (t - wd.s) / 0.14) - 0.14 : 1;
                return (
                  <span key={i} style={{ display: 'inline-block', margin: '0 0.14em', color: active ? hi : col, transform: `scale(${pop})`, WebkitTextStroke: `${Math.round(size / 14)}px rgba(0,0,0,0.85)`, paintOrder: 'stroke fill', textShadow: `0 6px 24px ${hexA('#000000', 0.5)}` }}>{wd.w}</span>
                );
              })}
            </div>
          </div>
        ) : null
      }
    </LayerBox>
  );
};

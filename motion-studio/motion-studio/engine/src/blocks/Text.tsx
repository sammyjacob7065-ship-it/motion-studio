import React from 'react';
import { Ctx, LayerBox, glowFilter, shadowFilter, hexA } from './common';
import { ease, num, presetFx } from '../anim';
import { fontFamily } from '../fonts';
import type { Layer } from '../types';

const commas = (n: number, dec: number) => n.toLocaleString('en-US', { minimumFractionDigits: dec, maximumFractionDigits: dec });

type TextProps = { text: string; layer: Layer; ctx: Ctx };

const TextInner: React.FC<TextProps> = ({ text, layer, ctx }) => {
  const p = layer.props || {};
  const { t } = ctx;
  const size = num(layer, 'size', t, p.size ?? 72);
  const mode = p.mode || 'block';
  const col = p.color || ctx.palette.text || '#ffffff';
  const hi = (p.highlight || []).map((s: string) => String(s).toLowerCase().replace(/[^a-z0-9]/g, ''));
  const hiColor = p.highlightColor || ctx.palette.accent || '#f5c451';
  const grad = p.gradient && p.gradient.length >= 2 ? `linear-gradient(${p.gradientAngle ?? 90}deg, ${p.gradient.join(', ')})` : undefined;
  const base: React.CSSProperties = {
    fontFamily: fontFamily(p.font), fontSize: size, fontWeight: p.weight ?? 700, color: col, textAlign: p.align || 'center',
    letterSpacing: p.letterSpacing ?? 0, lineHeight: p.lineHeight ?? 1.12, textTransform: p.uppercase ? 'uppercase' : undefined,
    maxWidth: p.maxWidth ?? ctx.W * 0.84, width: p.width ?? 'max-content', whiteSpace: 'pre-wrap', margin: 0,
    WebkitTextStroke: p.stroke ? `${p.stroke.width ?? 2}px ${p.stroke.color ?? '#000'}` : undefined,
    filter: [glowFilter(p.glow), shadowFilter(p.shadow)].filter(Boolean).join(' ') || undefined,
  };
  if (grad) { base.backgroundImage = grad; (base as any).WebkitBackgroundClip = 'text'; base.backgroundClip = 'text'; base.color = 'transparent'; (base as any).WebkitTextFillColor = 'transparent'; }

  if (mode === 'typewriter') {
    const dur = p.typeDur ?? Math.max(0.6, text.length * 0.045);
    const n = Math.floor(text.length * Math.min(1, Math.max(0, (t - layer.start - (p.delay ?? 0)) / dur)));
    const cursor = p.cursor !== false && Math.floor(t * 2.2) % 2 === 0 ? '|' : ' ';
    return <div style={base}>{text.slice(0, n)}<span style={{ opacity: n >= text.length ? 0 : 1 }}>{cursor}</span></div>;
  }
  if (mode === 'block') return <div style={base}>{text}</div>;

  const tokens: string[] = mode === 'chars' ? Array.from(text) : mode === 'lines' ? text.split('\n') : text.split(/(\s+)/);
  const stagger = p.stagger ?? (mode === 'chars' ? 0.03 : mode === 'lines' ? 0.18 : 0.09);
  const tokDur = p.tokenDur ?? 0.55;
  const preset = p.tokenPreset || 'slideUp';
  let idx = 0;
  return (
    <div style={base}>
      {tokens.map((tok, i) => {
        if (mode !== 'lines' && /^\s+$/.test(tok)) return <span key={i}>{tok}</span>;
        const k = idx++;
        const prog = (t - layer.start - (p.delay ?? 0) - k * stagger) / tokDur;
        const fx = prog >= 1 ? presetFx('none', 1, undefined, 0, 1) : prog <= 0 ? { opacity: 0, dx: 0, dy: 0, scale: 1, rotate: 0, blur: 0, clip: 1, draw: 1 } : presetFx(preset, prog, p.tokenEase, p.tokenDistance ?? 46, 1);
        const key = tok.toLowerCase().replace(/[^a-z0-9]/g, '');
        const isHi = hi.length && hi.includes(key);
        return (
          <span key={i} style={{ display: mode === 'lines' ? 'block' : 'inline-block', opacity: fx.opacity, transform: `translate(${fx.dx}px, ${fx.dy}px) scale(${fx.scale}) rotate(${fx.rotate}deg)`, filter: fx.blur ? `blur(${fx.blur}px)` : undefined, color: isHi && !grad ? hiColor : undefined, whiteSpace: 'pre' }}>{tok}</span>
        );
      })}
    </div>
  );
};

const TextBody: React.FC<TextProps> = (props) => {
  const p = props.layer.props || {};
  if (!p.plate) return <TextInner {...props} />;
  const pl = p.plate;
  return (
    <div style={{ background: hexA(pl.color || '#050b1f', pl.opacity ?? 0.6), padding: pl.padding ?? '24px 40px', borderRadius: pl.radius ?? 28, backdropFilter: pl.blur ? `blur(${pl.blur}px)` : undefined, border: pl.border ? `2px solid ${hexA(pl.border, 0.5)}` : undefined }}>
      <TextInner {...props} />
    </div>
  );
};

export const TextLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => (
  <LayerBox layer={layer} ctx={ctx}>{() => <TextBody text={String((layer.props || {}).text ?? '')} layer={layer} ctx={ctx} />}</LayerBox>
);

export const CounterLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const d = p.countDur ?? 1.6;
  const prog = ease(p.countEase || 'outExpo', (ctx.t - layer.start - (p.delay ?? 0)) / d);
  const v = (p.from ?? 0) + ((p.to ?? 100) - (p.from ?? 0)) * prog;
  const dec = p.decimals ?? 0;
  const s = (p.prefix || '') + (p.format === 'plain' ? v.toFixed(dec) : commas(v, dec)) + (p.suffix || '');
  return <LayerBox layer={layer} ctx={ctx}>{() => <TextBody text={s} layer={layer} ctx={ctx} />}</LayerBox>;
};

import React from 'react';
import { Ctx, LayerBox, glowFilter, hexA } from './common';
import { ease, num } from '../anim';
import type { Layer } from '../types';

const fillOf = (p: any, ctx: Ctx) =>
  p.gradient && p.gradient.length >= 2 ? `linear-gradient(${p.gradientAngle ?? 135}deg, ${p.gradient.join(', ')})` : p.color || ctx.palette.primary || '#3b82f6';

export const ShapeLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const { t } = ctx;
  const w = num(layer, 'width', t, p.width ?? 300);
  const h = num(layer, 'height', t, p.height ?? p.width ?? 300);
  const kind = p.shape || 'rect';
  const sw = p.strokeWidth ?? 6;
  const outline = p.fill === false || kind === 'ring';
  const color = p.color || ctx.palette.primary || '#3b82f6';
  const style: React.CSSProperties = {
    width: w, height: h, boxSizing: 'border-box',
    borderRadius: kind === 'circle' || kind === 'ring' ? '50%' : kind === 'pill' ? 9999 : p.radius ?? 0,
    background: outline ? 'transparent' : fillOf(p, ctx),
    border: outline ? `${sw}px solid ${color}` : p.border ? `${p.border.width ?? 2}px solid ${p.border.color ?? '#fff'}` : undefined,
    opacity: p.fillOpacity ?? 1,
    filter: glowFilter(p.glow) || undefined,
    backdropFilter: p.blurBackdrop ? `blur(${p.blurBackdrop}px)` : undefined,
  };
  return (
    <LayerBox layer={layer} ctx={ctx}>
      {() =>
        kind === 'triangle' ? (
          <svg width={w} height={h} viewBox="0 0 100 100" style={{ filter: glowFilter(p.glow) || undefined }}>
            <polygon points="50,6 96,94 4,94" fill={outline ? 'none' : color} stroke={outline ? color : 'none'} strokeWidth={sw / 2} strokeLinejoin="round" />
          </svg>
        ) : (
          <div style={style} />
        )
      }
    </LayerBox>
  );
};

type Part = { t: 'path' | 'rect' | 'circle' | 'ellipse' | 'line' | 'polygon'; [k: string]: any };
const ICONS: Record<string, Part[]> = {
  shield: [{ t: 'path', d: 'M12 2.5 L20 5.5 V11.5 C20 16.5 16.5 20.5 12 22 C7.5 20.5 4 16.5 4 11.5 V5.5 Z' }],
  check: [{ t: 'path', d: 'M5 12.5 L10 17.5 L19 7' }],
  lock: [{ t: 'rect', x: 5, y: 10.5, width: 14, height: 10, rx: 2 }, { t: 'path', d: 'M8 10.5 V7.5 a4 4 0 0 1 8 0 V10.5' }],
  card: [{ t: 'rect', x: 2.5, y: 5.5, width: 19, height: 13, rx: 2.5 }, { t: 'line', x1: 2.5, y1: 10, x2: 21.5, y2: 10 }, { t: 'line', x1: 6, y1: 15, x2: 10, y2: 15 }],
  bolt: [{ t: 'polygon', points: '13,2.5 5,13.5 11,13.5 10,21.5 19,10 13,10' }],
  globe: [{ t: 'circle', cx: 12, cy: 12, r: 9.5 }, { t: 'ellipse', cx: 12, cy: 12, rx: 4, ry: 9.5 }, { t: 'line', x1: 2.5, y1: 12, x2: 21.5, y2: 12 }],
  phone: [{ t: 'rect', x: 7, y: 2.5, width: 10, height: 19, rx: 2.5 }, { t: 'line', x1: 10.5, y1: 18.5, x2: 13.5, y2: 18.5 }],
  coin: [{ t: 'circle', cx: 12, cy: 12, r: 9.5 }, { t: 'path', d: 'M14.5 9 C14 8 13 7.5 12 7.5 C10.5 7.5 9.5 8.3 9.5 9.5 C9.5 12 14.5 11 14.5 14 C14.5 15.3 13.4 16.5 12 16.5 C10.9 16.5 10 16 9.5 15' }, { t: 'line', x1: 12, y1: 5.8, x2: 12, y2: 7.5 }, { t: 'line', x1: 12, y1: 16.5, x2: 12, y2: 18.2 }],
  arrow: [{ t: 'path', d: 'M4.5 12 H19.5 M13.5 6 L19.5 12 L13.5 18' }],
  star: [{ t: 'polygon', points: '12,2.8 14.9,9 21.5,9.7 16.6,14.2 18,20.8 12,17.5 6,20.8 7.4,14.2 2.5,9.7 9.1,9' }],
  play: [{ t: 'path', d: 'M7 4.5 L19 12 L7 19.5 Z' }],
  wifi: [{ t: 'path', d: 'M2.5 9 C8 4 16 4 21.5 9' }, { t: 'path', d: 'M5.5 12.5 C9 9.5 15 9.5 18.5 12.5' }, { t: 'path', d: 'M8.7 16 C10.8 14.2 13.2 14.2 15.3 16' }, { t: 'circle', cx: 12, cy: 19.2, r: 1 }],
  user: [{ t: 'circle', cx: 12, cy: 8, r: 4 }, { t: 'path', d: 'M4.5 21 C4.5 16.5 8 14 12 14 C16 14 19.5 16.5 19.5 21' }],
  chart: [{ t: 'rect', x: 4, y: 12, width: 4, height: 8, rx: 0.8 }, { t: 'rect', x: 10, y: 7, width: 4, height: 13, rx: 0.8 }, { t: 'rect', x: 16, y: 3, width: 4, height: 17, rx: 0.8 }],
  heart: [{ t: 'path', d: 'M12 20.5 C4 15 2.5 10.5 2.5 8 C2.5 5.2 4.6 3.5 7 3.5 C9 3.5 11 4.7 12 6.5 C13 4.7 15 3.5 17 3.5 C19.4 3.5 21.5 5.2 21.5 8 C21.5 10.5 20 15 12 20.5 Z' }],
  mail: [{ t: 'rect', x: 2.5, y: 5, width: 19, height: 14, rx: 2 }, { t: 'path', d: 'M3 7 L12 13.5 L21 7' }],
  clock: [{ t: 'circle', cx: 12, cy: 12, r: 9.5 }, { t: 'path', d: 'M12 6.5 V12 L16 14' }],
  home: [{ t: 'path', d: 'M3.5 11 L12 3.5 L20.5 11 V20.5 H14.5 V14.5 H9.5 V20.5 H3.5 Z' }],
  bell: [{ t: 'path', d: 'M6 16.5 V11 a6 6 0 0 1 12 0 V16.5 L19.5 18.5 H4.5 Z' }, { t: 'path', d: 'M10 21 a2 2 0 0 0 4 0' }],
  cart: [{ t: 'path', d: 'M2.5 3.5 H5 L7.2 15.5 H18 L20 7 H6' }, { t: 'circle', cx: 9, cy: 19.5, r: 1.5 }, { t: 'circle', cx: 17, cy: 19.5, r: 1.5 }],
};
export const ICON_NAMES = Object.keys(ICONS);

export const IconLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const parts = ICONS[p.name] || ICONS.star;
  const size = num(layer, 'size', ctx.t, p.size ?? 160);
  const color = p.color || ctx.palette.primary || '#3b82f6';
  return (
    <LayerBox layer={layer} ctx={ctx}>
      {(fx) => {
        const common: any = { fill: p.fill ? hexA(p.fillColor || color, p.fillOpacity ?? 0.18) : 'none', stroke: color, strokeWidth: p.strokeWidth ?? 1.8, strokeLinecap: 'round', strokeLinejoin: 'round', pathLength: 1 };
        const dash = fx.draw < 1 ? { strokeDasharray: 1, strokeDashoffset: 1 - fx.draw } : {};
        return (
          <svg width={size} height={size} viewBox="0 0 24 24" style={{ filter: glowFilter(p.glow) || undefined, overflow: 'visible' }}>
            {parts.map((q, i) => {
              const { t: tag, ...rest } = q as any;
              const El: any = tag;
              return <El key={i} {...rest} {...common} {...dash} />;
            })}
          </svg>
        );
      }}
    </LayerBox>
  );
};

const toPath = (pts: number[][], curve: number) => {
  if (pts.length < 2) return '';
  if (!curve || pts.length < 3) return 'M' + pts.map((q) => q.join(' ')).join(' L');
  let d = `M${pts[0][0]} ${pts[0][1]}`;
  for (let i = 0; i < pts.length - 1; i++) {
    const p0 = pts[Math.max(0, i - 1)], p1 = pts[i], p2 = pts[i + 1], p3 = pts[Math.min(pts.length - 1, i + 2)];
    const k = curve / 6;
    d += ` C${p1[0] + (p2[0] - p0[0]) * k} ${p1[1] + (p2[1] - p0[1]) * k}, ${p2[0] - (p3[0] - p1[0]) * k} ${p2[1] - (p3[1] - p1[1]) * k}, ${p2[0]} ${p2[1]}`;
  }
  return d;
};

export const LineLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const color = p.color || ctx.palette.primary || '#3b82f6';
  const pts: number[][] = p.points && p.points.length >= 2 ? p.points : [[ctx.W * 0.2, ctx.H * 0.5], [ctx.W * 0.8, ctx.H * 0.5]];
  const d = toPath(pts, p.curve ?? 0.8);
  const w = p.width ?? 5;
  return (
    <LayerBox layer={layer} ctx={ctx} full>
      {(fx) => {
        const draw = layer.anim && layer.anim.draw ? num(layer, 'draw', ctx.t, 1) : fx.draw;
        const pulseOn = p.pulse !== false;
        const travel = ((ctx.t - layer.start) * (p.pulseSpeed ?? 0.6)) % 1;
        return (
          <svg width={ctx.W} height={ctx.H} viewBox={`0 0 ${ctx.W} ${ctx.H}`} style={{ position: 'absolute', inset: 0, overflow: 'visible' }}>
            <g style={{ filter: glowFilter(p.glow ?? { color, blur: 18, opacity: 0.9 }) }}>
              <path d={d} fill="none" stroke={hexA(color, p.baseOpacity ?? 0.55)} strokeWidth={w} strokeLinecap="round" pathLength={1} strokeDasharray={1} strokeDashoffset={1 - draw} />
              {pulseOn && draw >= 0.98 ? (
                <path d={d} fill="none" stroke={p.pulseColor || '#ffffff'} strokeWidth={w * 1.1} strokeLinecap="round" pathLength={1} strokeDasharray={`0.07 1`} strokeDashoffset={-travel + 0.07} />
              ) : null}
              {p.dots !== false && draw > 0.02 ? pts.map((q, i) => {
                const reached = draw >= i / Math.max(1, pts.length - 1) - 0.001;
                return reached ? <circle key={i} cx={q[0]} cy={q[1]} r={w * 1.7} fill={p.dotColor || color} /> : null;
              }) : null}
            </g>
          </svg>
        );
      }}
    </LayerBox>
  );
};

/** Full-screen transition overlay between moments: flash, dip-to-color, wipe, bars. Uses layer start..end as the duration. */
export const TransitionLayer: React.FC<{ layer: Layer; ctx: Ctx }> = ({ layer, ctx }) => {
  const p = layer.props || {};
  const dur = Math.max(0.1, layer.end - layer.start);
  const q = (ctx.t - layer.start) / dur;
  const color = p.color || '#ffffff';
  const kind = p.kind || 'flash';
  const tri = q < 0.5 ? ease('outQuad', q * 2) : ease('inQuad', 1 - (q - 0.5) * 2);
  let inner: React.ReactNode = null;
  if (kind === 'flash') inner = <div style={{ position: 'absolute', inset: 0, background: color, opacity: tri * (p.intensity ?? 0.9) }} />;
  else if (kind === 'fade') inner = <div style={{ position: 'absolute', inset: 0, background: color, opacity: tri }} />;
  else if (kind === 'wipe') {
    const dir = p.direction || 'right';
    const horizontal = dir === 'left' || dir === 'right';
    const span = horizontal ? ctx.W : ctx.H;
    const cover = q < 0.5 ? ease('inOutQuart', q * 2) : 1 + ease('inOutQuart', (q - 0.5) * 2);
    const pos = (cover - 1) * span * (dir === 'left' || dir === 'up' ? -1 : 1);
    inner = <div style={{ position: 'absolute', left: 0, top: 0, width: ctx.W, height: ctx.H, background: color, transform: horizontal ? `translateX(${pos}px)` : `translateY(${pos}px)` }} />;
  } else if (kind === 'bars') {
    const n = p.bars ?? 6;
    inner = (
      <>
        {Array.from({ length: n }).map((_, i) => {
          const local = Math.min(1, Math.max(0, (q < 0.5 ? q * 2 : 1 - (q - 0.5) * 2) * 1.4 - (i / n) * 0.4));
          return <div key={i} style={{ position: 'absolute', left: (i * ctx.W) / n, top: 0, width: ctx.W / n + 1, height: ctx.H, background: color, transform: `scaleY(${ease('inOutQuart', local)})`, transformOrigin: i % 2 ? 'top' : 'bottom' }} />;
        })}
      </>
    );
  }
  return <LayerBox layer={{ ...layer, parallax: 0 }} ctx={ctx} full>{() => inner}</LayerBox>;
};

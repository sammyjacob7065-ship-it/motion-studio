import React from 'react';
import { Ctx, LayerBox } from './common';
import { num } from '../anim';
import type { Layer } from '../types';

/**
 * GROUP: a rig. Its children are placed relative to the group's own centre (child x,y = 0,0 is the group centre), and they inherit every move of the group
 * (position, scale, rotation, 3D tilt, fade). Children can be groups too. This is how any custom object is built: a lid hinged on a box, a chicken swinging
 * on a pan, a door that opens, a character with moving parts.
 */
export const GroupLayer: React.FC<{ layer: Layer; ctx: Ctx; renderChild: (l: Layer) => React.ReactNode }> = ({ layer, ctx, renderChild }) => {
  const p = layer.props || {};
  const kids: Layer[] = (Array.isArray(p.children) ? p.children : []).map((c: Layer) => ({ ...c, parallax: 0, x: c.x ?? 0, y: c.y ?? 0 }));
  // clip: only what is inside the shape is visible (a drink inside a glass, a reveal, a window). Placed relative to the group centre.
  // {shape:'rect'|'ellipse'|'path', width, height, x, y, radius, d}  (anim tracks clipW, clipH, clipX, clipY move and grow it)
  const cl = p.clip;
  let clipPath: string | undefined;
  if (cl) {
    const cw = num(layer, 'clipW', ctx.t, cl.width ?? 400), ch = num(layer, 'clipH', ctx.t, cl.height ?? 400);
    const cx = num(layer, 'clipX', ctx.t, cl.x ?? 0), cy = num(layer, 'clipY', ctx.t, cl.y ?? 0);
    if (cl.shape === 'path' && cl.d) clipPath = `path('${String(cl.d).replace(/'/g, '')}')`;
    else if (cl.shape === 'ellipse') clipPath = `ellipse(${Math.max(0.1, cw / 2)}px ${Math.max(0.1, ch / 2)}px at ${cx}px ${cy}px)`;
    else clipPath = `polygon(${cx - cw / 2}px ${cy - ch / 2}px, ${cx + cw / 2}px ${cy - ch / 2}px, ${cx + cw / 2}px ${cy + ch / 2}px, ${cx - cw / 2}px ${cy + ch / 2}px)`;
  }
  return (
    <LayerBox layer={layer} ctx={ctx} three>
      {() => (
        <div style={{ position: 'absolute', left: 0, top: 0, width: 0, height: 0, transformStyle: clipPath ? 'flat' : 'preserve-3d', perspective: p.perspective, clipPath }}>
          {kids.map((c) => <React.Fragment key={c.id}>{renderChild(c)}</React.Fragment>)}
        </div>
      )}
    </LayerBox>
  );
};

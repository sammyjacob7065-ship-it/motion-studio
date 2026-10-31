import React from 'react';
import { Ctx, LayerBox } from './common';
import type { Layer } from '../types';

/**
 * GROUP: a rig. Its children are placed relative to the group's own centre (child x,y = 0,0 is the group centre), and they inherit every move of the group
 * (position, scale, rotation, 3D tilt, fade). Children can be groups too. This is how any custom object is built: a lid hinged on a box, a chicken swinging
 * on a pan, a door that opens, a character with moving parts.
 */
export const GroupLayer: React.FC<{ layer: Layer; ctx: Ctx; renderChild: (l: Layer) => React.ReactNode }> = ({ layer, ctx, renderChild }) => {
  const p = layer.props || {};
  const kids: Layer[] = (Array.isArray(p.children) ? p.children : []).map((c: Layer) => ({ ...c, parallax: 0, x: c.x ?? 0, y: c.y ?? 0 }));
  return (
    <LayerBox layer={layer} ctx={ctx} three>
      {() => (
        <div style={{ position: 'absolute', left: 0, top: 0, width: 0, height: 0, transformStyle: 'preserve-3d', perspective: p.perspective }}>
          {kids.map((c) => <React.Fragment key={c.id}>{renderChild(c)}</React.Fragment>)}
        </div>
      )}
    </LayerBox>
  );
};

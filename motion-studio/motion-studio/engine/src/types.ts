export type Key = [number, number | string] | [number, number | string, string];
export type Tracks = Record<string, Key[]>;

export type Glow = { color?: string; blur?: number; opacity?: number; spread?: number };

export type EnterExit = { preset?: string; dur?: number; ease?: string; delay?: number; distance?: number };

export type Layer = {
  id: string;
  type: 'image' | 'video' | 'text' | 'shape' | 'icon' | 'line' | 'particles' | 'counter' | 'captions' | 'transition' | 'magic' | 'group';
  start: number;
  end: number;
  x?: number; y?: number;
  parallax?: number;
  z?: number;
  enter?: EnterExit;
  exit?: EnterExit;
  anim?: Tracks;
  props?: Record<string, any>;
};

export type CameraKey = [number, number, number, number, number?, string?]; // t, scale, x, y, rotate, ease

export type Background = {
  type?: 'gradient' | 'solid' | 'image' | 'radial';
  colors?: string[];
  angle?: number;
  asset?: string;
  blur?: number;
  vignette?: number;
  grain?: number;
  orbs?: number;
  orbColor?: string;
  seed?: number;
};

export type Timeline = {
  version?: number;
  width: number;
  height: number;
  fps: number;
  duration: number;
  background?: Background;
  palette?: Record<string, string>;
  camera?: CameraKey[];
  layers: Layer[];
};

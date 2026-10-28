# Timeline format (what the renderer can play)

All times are in SECONDS from the start of the video. All positions are PIXELS on the canvas (origin top-left, x to the right, y down).
The canvas size is given in the brief (for example 1080x1920 for 9:16, 1920x1080 for 16:9, 1080x1080 for 1:1). Layer x,y is the CENTER of the layer.

```
{
 "aspect": "9:16", "fps": 30, "duration": 14.0,
 "palette": {"primary": "#3b82f6", "accent": "#f5c451", "text": "#ffffff"},
 "background": {...},
 "camera": [[t, scale, panX, panY, rotateDeg?, ease?], ...],
 "layers": [ {layer}, ... ]
}
```

## Layer (common fields)
`{"id":"unique","type":"...","start":1.0,"end":6.0,"x":540,"y":960,"z":10,"parallax":1,"enter":{...},"exit":{...},"anim":{...},"props":{...}}`
- `z`: stacking order, higher is in front (background 0, particles 1-5, shapes/lines 5-9, images 10-19, icons 20-29, text 30-49, transitions 90+).
- `parallax`: 1 = moves fully with the camera (default), 0 = fixed on screen (use for UI text, captions), 0.3-0.6 = far background feeling.
- `enter` / `exit`: `{"preset":"slideUp","dur":0.7,"ease":"outExpo","distance":120,"delay":0}`. The exit runs in the LAST `dur` seconds before `end`.
  Presets: fade, slideUp, slideDown, slideLeft, slideRight, scaleIn, zoomIn, pop (springy), blurIn, wipe (reveals left to right), rotateIn, drop, riseGlow, draw (for line and icon: draws itself).
- `anim`: keyframe tracks `{"y": [[t, value, ease?], ...]}`. Times are absolute. Supported tracks: x, y, scale, rotate, opacity, blur, width, height, size, draw (line, 0..1), sheen (image light sweep, 0..1). Values between keys are eased with the ease of the NEXT key.
- Easing names: linear, in, out, inOut, inQuad, outQuad, inOutQuad, outQuart, inOutQuart, outExpo, inExpo, inOutExpo, outBack (overshoot), inBack, outElastic, spring.
- `props.pulse`: `{"period":1.6,"amount":0.05}` makes any layer breathe (scale).

## Types and props
**image** `{"asset":"file name","width":600,"height":(optional),"fit":"contain|cover","radius":0,"border":{"width":3,"color":"#fff"},"glow":{"color","blur":30,"opacity":0.6},"shadow":{"y":30,"blur":50,"opacity":0.45},"kenBurns":{"from":1,"to":1.12,"panX":0,"panY":0}}`
 Use `fit:"cover"` with both width and height for full-bleed photos. Use `anim.sheen` for a moving light sweep across a product or logo. Glow and shadow follow the picture's transparent edges.
**video** `{"asset":"file name","width":1080,"height":1920,"fit":"cover","srcStart":0,"radius":0,"glow":...,"shadow":...}` plays a client video (its sound is mixed separately, see audio).
**text** `{"text":"Hello\nWorld","size":96,"weight":800,"font":"Poppins","color":"#fff","align":"center","uppercase":false,"letterSpacing":0,"lineHeight":1.1,"maxWidth":900,"mode":"block|words|chars|lines|typewriter","stagger":0.1,"tokenPreset":"slideUp","tokenDur":0.55,"delay":0,"highlight":["word"],"highlightColor":"#f5c451","gradient":["#fff","#93c5fd"],"glow":{...},"shadow":{...},"stroke":{"width":2,"color":"#000"},"plate":{"color":"#050b1f","opacity":0.6,"blur":8,"radius":28}}`
 Fonts available: Inter, Poppins, Montserrat, Space Grotesk, Playfair Display, Bebas Neue, Oswald, DM Sans, Outfit, Sora, Anton. Weights 400-900 (Bebas Neue and Anton only 400).
 `mode:"words"` brings words in one by one (best for headlines), `lines` one line at a time, `chars` letter by letter, `typewriter` types it out. `plate` puts a dark card behind text so it stays readable over busy pictures.
 Text width estimate: about size x 0.56 pixels per character (x 0.42 for Bebas Neue, Anton, Oswald). Put "\n" yourself to break lines. Keep every line within 85% of the canvas width.
**counter** `{"from":0,"to":2400000,"prefix":"$","suffix":"+","decimals":0,"countDur":1.6,"countEase":"outExpo", ...same text style props}` animated number.
**shape** `{"shape":"rect|circle|ring|pill|triangle","width":300,"height":300,"color":"#3b82f6","gradient":["#a","#b"],"radius":24,"fill":false,"strokeWidth":6,"fillOpacity":1,"glow":{...},"blurBackdrop":12}` ring = outline circle. Animate width/height for bars and wipes. `blurBackdrop` makes frosted-glass cards.
**icon** `{"name":"shield","size":160,"color":"#f5c451","strokeWidth":1.8,"fill":true,"fillOpacity":0.18,"glow":{...}}`
 Icon names: shield, check, lock, card, bolt, globe, phone, coin, arrow, star, play, wifi, user, chart, heart, mail, clock, home, bell, cart. Use enter preset "draw" to draw it on.
**line** `{"points":[[x,y],[x,y],...],"color":"#60a5fa","width":5,"curve":0.8,"glow":{...},"pulse":true,"pulseSpeed":0.6,"dots":true,"dotColor":"#fff"}` a glowing connection line through the points (curve 0 = straight, 1 = very curved). Use enter preset "draw" so it grows from the first point to the last. A light pulse travels along it after it has drawn. Lines use absolute canvas coordinates (ignore x,y).
**particles** `{"mode":"burst|float|sparkle|rain|stream","count":80,"origin":[x,y],"area":[w,h],"colors":["#f5c451","#fff"],"size":[3,9],"speed":600,"life":1.8,"gravity":300,"direction":-90,"spread":360,"seed":4,"opacity":1,"glow":true}`
 burst = explosion from origin (one-shot, set start at the moment). float = slow rising dust/bokeh across the area (good ambient layer). sparkle = twinkling points in an area. rain = falling streaks. stream = particles flowing out of origin along direction.
**captions** `{"words_from":"voice"}` or `{"words_from":"video:<video file name>","offset":0}` plus `{"group":3,"size":74,"y":1380,"font":"Montserrat","color":"#fff","highlightColor":"#f5c451"}` word-by-word captions that highlight the spoken word (words are filled in for you). Do not write the words yourself.
**transition** `{"kind":"flash|fade|wipe|bars","color":"#ffffff","direction":"right","bars":6,"intensity":0.9}` a full-screen cut effect; `start` to `end` is its duration (0.3-0.7s). Put the content change at its midpoint.

## Background
`{"type":"gradient|radial|solid|image","colors":["#040816","#0a1f5c"],"angle":165,"asset":"(for type image)","blur":0,"vignette":0.45,"grain":0.06,"orbs":6,"orbColor":"#3b82f6","seed":3}`
`orbs` adds slow drifting soft light blobs (premium depth). `grain` 0.04-0.08 and `vignette` 0.35-0.55 give a cinematic finish.

## Camera
Keyframes `[t, scale, panX, panY, rotateDeg, ease]`. Scale 1.0-1.25 for gentle pushes, pan values in pixels (30-120). Layers move with the camera times their `parallax`. Use slow pushes under 1.15 so it feels premium.

## Audio
Top-level list `audio` next to `timeline`: 
`{"role":"sfx","sfx":"whoosh","start":1.2,"volume":0.5}` sound effects: whoosh, swoosh_up, pop, click, tick, hit, riser, shimmer, sparkle.
`{"role":"music","asset":"file name","start":0,"volume":0.16}` background music, only if the client supplied a music file.
`{"role":"voice","asset":"video file name","start":2.0,"srcStart":0,"dur":8}` use the sound of a client video clip (needed when a video layer should be heard).
The generated or supplied voice-over is added for you, you never list it.

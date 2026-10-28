# Motion Studio

A prompt-controlled motion graphics studio. You send a brief (and your pictures, logo, voice, video) in Telegram.
An AI director turns it into an exact timeline, a Remotion engine renders it, FFmpeg mixes the sound, and the finished video comes back to Telegram. Every stage is reported live.

```
Telegram (/newmotion)  ->  n8n "Motion Studio Room"  ->  Supabase (files, brief)  ->  GitHub Actions
                                                                                         |
   engine/    Remotion renderer: the blocks (image, video, text, shape, icon, line, particles, counter, captions, transition)
   pipeline/  run.py -> check files -> plan -> stock pictures -> voice -> timeline -> layout check -> render -> mix -> deliver
   director/  the director's instructions: BLOCKS.md (what the renderer can do), system.md (design rules), examples/
```

## One-time setup

1. **Repo**: create a GitHub repo called `motion-studio` and put all these files in it (keep the `.github` folder: `.github/workflows/render.yml` must exist on the `main` branch).
2. **Secrets**: repo Settings > Secrets and variables > Actions > New repository secret.

| Secret | What |
|---|---|
| `SUPABASE_URL` | same as your movie factory |
| `SUPABASE_SERVICE_KEY` | same as your movie factory |
| `SUPABASE_BUCKET` | `betrayer-assets` (files use the folder `motion/`) |
| `GROQ_API_KEY` | director, speech timing, picture checks |
| `MOTION_TG_TOKEN` | token of the NEW Motion Studio bot (the same one in the n8n Settings node) |
| `PEXELS_API_KEY` (optional) | free key, lets the studio find stock pictures/videos when the brief asks |
| `PIXABAY_API_KEY` (optional) | free key, backup for stock pictures |
| `TTS_URL` (optional) | default is your Render Edge-TTS server |
| `TTS_VOICE` (optional) | default `en-NG-AbeoNeural` |
| `DIRECTOR_MODEL` (optional) | default `openai/gpt-oss-120b`; swap for a stronger model if the plans are weak |
| `VISION_MODEL` (optional) | default `meta-llama/llama-4-scout-17b-16e-instruct` |

3. **n8n**: import `Motion_Studio_Room.json`, paste the bot token in its Settings node, set the Telegram credential on the trigger, publish.
4. Your GitHub token in the n8n Settings node must be allowed to use this repo (Actions: read and write).

## Using it

- Send your files (pictures as **File**, not Photo, to keep full quality), then send your prompt. The prompt starts the job.
- Or send one picture with the prompt as its caption.
- Put `PLAN` alone on the first line to see the plan first, then send `/go`.
- `/status` shows where the job is, `/cancel` stops it.
- Files over 20 MB: put a download link (Google Drive, Dropbox, direct link) in the prompt.

## How the quality is protected

- The director is told to follow the brief literally and to keep client assets exactly as supplied.
- The timeline is validated: unknown blocks, missing files and bad times are fixed or dropped, text is sized to fit.
- A layout check finds overlapping text; a vision check looks at preview frames; major problems are sent back to the director for one repair round.
- At the end each instruction in your brief is ticked off and anything simplified is reported.

## Run the engine on your computer

```
cd engine && npm install && npx remotion studio
```
Put test pictures in `engine/public/assets/`. The test that runs the whole pipeline with fake services (no keys needed): `python tests/test_run.py`.

## Adding a new effect

1. Add the block in `engine/src/blocks/` and register it in `engine/src/Scene.tsx`.
2. Allow it in `pipeline/timeline.py` (`ALLOWED_TYPES`).
3. Describe it in `director/BLOCKS.md`. The director can only use what is described there.
Test it with a hand-written timeline before the director is allowed to use it.

## Known limits (v1)

- Flat pictures get 2.5D motion (depth, light, camera). No real 3D turns and no Lottie/3D models yet.
- Sound effects are synthesized (clean but simple). Music only if the client supplies a file.
- Editing by chat ("make the glow stronger") is not built yet. Each job saves its `timeline.json` in Supabase, which is what that feature will edit.
- Remotion's licence is free for individuals and small teams; check remotion.dev/license if you grow.

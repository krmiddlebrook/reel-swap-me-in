# Local person swap with VACE 1.3B (WanGP)

Free, fully on-device person replacement: take a reel, mask the person in it,
and regenerate them as you — driven by your reference photos. No API costs.
Trade-off: Apple-Silicon (MPS) support in WanGP is official but young —
expect minutes per second of video, not real time.

## Install & launch

```bash
./setup.sh --vace     # one-time: ~15 GB deps + ~11 GB weights on first gen
./vace.sh ui          # web UI at http://localhost:7860, VACE 1.3B preselected
```

Keep generations at **480p** and **≤ 81 frames** (~5 s at 16 fps) — that's
what the 1.3B model is trained for; enable Riflex (a rotary-position extension
for longer clips, in the model's Advanced settings) for up to ~7 s.

## Replace the person in a reel (WanGP docs/VACE.md, Example 1)

1. In the Vace 1.3B screen set **Control Video Process = Transfer human pose**
   and **Area processed = Masked area**.
2. Open the **Matanyone Video Mask Creator** (embedded tool), load the reel,
   click the person to build the mask, then **Export to Control Video Input
   and Video Mask Input**.
3. Under **Reference Image** choose **Inject Landscapes / People / Objects**
   and upload 1–3 photos of you (e.g. from `assets/faces/`). Leave the
   background remover ON for person photos.
4. Describe yourself explicitly in the **Prompt** ("a man with …, wearing …")
   — VACE links reference images to the output through the prompt.
5. Generate. Use the preview thumbnails to confirm the control video shows a
   pose wireframe inside the masked area; launch with `./vace.sh ui
   --save-masks` to dump the generated control/mask videos for debugging.
6. Optional but recommended: run the existing FaceFusion face-restore pass on
   the result for facial identity (it works on any video, not just API swaps).

UI generations are saved under `vendor/wangp/outputs/` (the engine's own
gallery folder); headless runs land in `output/` at the repo root.

## Repeatable / headless runs

In the UI, queue a generation and click **Save Queue** → produces a `.zip`
with all inputs embedded. Re-run it without the UI:

```bash
./vace.sh process my_swap_queue.zip
```

Outputs land in `output/`. This is the bridge to app integration later: one
interactive session defines the recipe, the zip replays it.

## Smoke test & measured performance

`./vace.sh smoke` generates a 17-frame (~1 s) 480p clip headlessly from
`assets/vace-smoke.json`, wrapped in `/usr/bin/time -l` (peak RSS in bytes).
The smoke values are deliberate: 17 frames is the smallest 4n+1 grid ≈ 1 s,
10 steps trades quality for a fast gate, and the fixed seed keeps runs
comparable — bump these only if you're re-baselining.

| Date | Run | Wall time | Peak RSS | Notes |
| ---- | --- | --------- | -------- | ----- |
| 2026-06-12 | first (incl. ~11 GB model download) | 26m 57s | 3.4 GB | MPS autocast dtype warning (harmless); objc dylib duplicate warning (harmless); peak unified memory footprint 14.9 GB |
| 2026-06-12 | second (warm) | 9m 34s | 2.1 GB | Same MPS warnings; peak unified memory footprint 15.4 GB; ~48 s/step → 10 steps in 7 m 35 s |

**Verdict (2026-06-12): GO — warm smoke run completed in 9m 34s (well under the 20-minute gate), producing a valid 17-frame 480x832 h264 clip at 16 fps with exit 0 on both runs.**

**Go/no-go gate:** warm smoke run ≤ 20 min → proceed with the interactive
recipe and speed tuning. Slower → try the CausVid LoRA rescue below before
spending more time; if still impractical, stop here (the Higgsfield path
remains the default).

## Speed-ups to try after the gate passes

- **CausVid LoRA (1.3B)** — distilled 4–8 step generation (~91 MB LoRA),
  available via WanGP's LoRA downloader or Hugging Face; cuts step count
  ~4×. Guidance must be set to 1.0 when active.
- **Self-Forcing / DMD distill LoRA (1.3B)** — same idea, alternative weights.
- **TeaCache / MagCache** (`skip_steps_cache_type`) — skips redundant
  denoising steps, model-supported, no extra weights.
- (lightx2v is 14B-only — not applicable here.)

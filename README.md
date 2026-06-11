# Reel Swap Me In

Paste an Instagram Reel URL — get the reel back **starring you**.

The app downloads the reel, lets you pick a 5–15s window, generates a clean
character reference from your photo, and has Higgsfield's character-swap
models re-render the clip with you as the subject. Everything runs locally
with direct API calls — no frameworks, no pip installs, Python stdlib only.

## Quick start

You need: macOS or Linux, Python 3.8+, and a
[Higgsfield](https://higgsfield.ai) account **with generation credits**
(each swap spends credits from *your* account).

```sh
git clone https://github.com/krmiddlebrook/reel-swap-me-in.git
cd reel-swap-me-in
./setup.sh            # fetches yt-dlp + ffmpeg for your OS
python3 -m app.server
```

Open <http://localhost:8787>. The page walks you through the two one-time
steps:

1. **Connect Higgsfield** — click the button, log in in the browser tab
   that opens, done. (The app registers itself with Higgsfield's OAuth
   server and stores tokens locally in `.higgsfield-credentials.json`,
   chmod 600, gitignored. They refresh automatically.)
2. **Add your photo** — choose a clear, front-facing JPEG/PNG of yourself.

Then paste a reel URL and hit **Replicate**. Generation takes a few
minutes; the page narrates each stage with a live timer, and finished
videos land in `output/`.

## Features

- **Clip picker:** reels longer than 15s pause for you to choose the start
  point and length (5–15s) with a window-looping preview.
- **Character reference:** your first run generates a studio-style
  reference image from your photo (1 credit, cached, regenerated only when
  you change photos) — it gives the swap far more identity signal than a
  casual photo.
- **Two swap engines:** Kling motion control (default; scene comes from
  the reel) and Seedance 2.0 (experimental, 480p, ~36 credits; note it
  refuses reels its copyright filter flags).
- **CLI mode:** `python3 replicate.py <reel-url> [start] [length]`.

## How it works

```
reel URL → bin/yt-dlp (download, public reels only)
         → pick start + length (5–15s) if the reel runs long
         → bin/ffmpeg (frame-accurate cut)
         → character reference (generated once, cached in assets/)
         → direct Higgsfield API calls (upload, swap, poll) — app/higgsfield.py
         → output/<job>.mp4 (played back in the page)
```

Auth is a standard OAuth client (PKCE + dynamic client registration)
against Higgsfield's MCP server — see `app/oauth.py`. If you happen to use
Claude Code and have its Higgsfield connector authorized, the app can also
reuse that session, and installs an optional Claude-agent fallback that
takes over a job if Higgsfield ever changes their API shape. Neither is
required.

## Picking reels that swap well

- **One person** in frame (with several, the model swaps whoever is
  closest to the camera);
- subject mostly **facing the camera**; face not covered for long
  stretches (mics, hands, props);
- **stable lighting**, continuous motion rather than fast cuts;
- a build **roughly matching yours** maps best.

## Troubleshooting

| Symptom | Fix |
| --- | --- |
| "Couldn't download this reel" | The reel must be public. Some are age/region-gated — try another. |
| "Reel too short" | Higgsfield needs at least 5 seconds of source video. |
| "Higgsfield isn't connected" | Click **Connect Higgsfield** on the page and finish the browser login. |
| "copyright filter blocked this content" | Seedance-only screening. Use the Kling engine for that reel. No credits were spent. |
| Generation fails mid-run | Check your credit balance at higgsfield.ai. |
| `bin/yt-dlp` or `bin/ffmpeg` missing | Re-run `./setup.sh`. |

## Consent & content

- Swap in **your own** photo (or someone who has explicitly consented).
  Don't put other people into videos without their permission.
- The reels you replicate are other creators' content — keep results for
  personal use and respect creators' rights, Instagram's terms, and
  [Higgsfield's terms](https://higgsfield.ai).

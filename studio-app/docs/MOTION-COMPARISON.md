# Motion Model Comparison: shot comparison

Production › Motion Model Comparison › **Shot comparison** compares hosted AI video models with the rig animator on one recorded line of a real episode.

- **Inputs:**
  - Only the studio's own approved art: the scene's approved set plate, with the speaker's approved neutral pose composed onto it locally (720×1280 first frame).
  - Two first frames are composed. **Wide** shows the whole figure on the set; **medium** shows head and upper body filling most of the frame, on the same plate enlarged. The avatar model gets **medium** by default and image-to-video gets **wide**. Each can be switched per model before Run.
  - For the avatar model, the line's own recorded audio, cut from the episode's recording as 48 kHz WAV.
  - Nothing from the reference video is used: its frames and the video are deleted after the notes are made.
- **Action:** written from the video notes' fixed-list words for that line (pose, emotion, the speaker's own beats), and editable before planning.
- **Planning is free:** a local job composes the first frame, cuts the audio and renders the same line with the rig.
- **Approval:** for each model the page shows the exact request (endpoint and JSON body), what it sends and the estimated cost. Nothing is sent until you click **Run** for that model. Every paid request counts against the experimental budget (Settings › Motion, default $25), and the running total is shown. A request that would exceed the budget is refused.
- **Results:** side by side with the rig render, each with its actual cost per clip and per second.
  - Every result gets **our original line audio**; any audio a model made is dropped.
  - Each is cut, or its last frame held, to the line's exact length, and checked to within one frame.
- **Models** (fal.ai, prices checked 2026-11-21; both marked "Commercial use permitted (Partner)"):
  - **Kling 2.6 Pro image-to-video**, audio off: $0.07 per second, 5 or 10 s clips. The clip is cut to the line.
  - **Kling AI Avatar v2 Standard**: image plus our line audio, as long as the audio, $0.0562 per second.
- **Server requirement:** `PUBLIC_URL` must be set, so fal.ai can fetch the frame and the audio. Without it, Run is refused.

## Batch mode (one screen)

- **Choose:** pick the episode, tick any lines ("All lines" / "None"), tick the models (the rig render, which is free, Kling i2v and Kling Avatar), and optionally override the framing (defaults: avatar medium, i2v wide).
- **Planning starts by itself** for every ticked line: first frames, audio cut and rig render. Progress shows as preparing / ready. An existing plan for a line is reused.
- **Actions** are filled in for each line from the video notes (pose, emotion, the speaker's beats) plus the line's own words and mood. Tone cues come from a fixed list (pompous, insulting, pleading, shocked, sarcastic, smug, deadpan) and the line's expression, so an action is never a flat "talks". Each is editable under "show/edit", where each clip's exact request can also be checked.
- **One summary before anything paid:** the exact number of clips, the total estimate, and the budget (spent + approved but not yet charged, against the cap). Then **one** confirm, "Run selected". The confirm carries the total you saw; if the selection changed meanwhile, it is refused.
- **Results** form a grid, one row per line, with rig / i2v / avatar columns side by side. Each cell shows the actual cost per clip and per second and the length check. A failed clip shows its reason and a single Retry.
- **Every guarantee is kept:** only our own approved art and audio are sent; every request is exactly the one shown; our original audio goes under every result, with the length checked to within one frame; the cap counts approved but uncharged runs.
- **Tone and action:**
  - **With a text provider in Settings:** the free preparation asks it to write each line's tone and action from the line's text, the lines before and after it, and the video notes. The tone is taken only from a fixed list (pompous, insulting, pleading, shocked, sarcastic, smug, deadpan, matter-of-fact, nervous, cheerful, angry, irritated, sad, puzzled, excited, mocking, proud, defensive, tender, exasperated, whispering, triumphant). The plan shows the tone, where it came from and the writer's estimated cost (text providers do not report usage here; about 4 characters per token at list prices).
  - **Fallback:** if the provider is not set, fails or gives nothing usable, the phrase matcher is used, with a note. It matches whole words and phrases only; cues such as "Sure," or "I," count only at the start of a sentence. A line with no cue still gets a sensible tone (excited, puzzled for a question, matter-of-fact otherwise, or the line's own mood).
  - **Your edit is never overwritten.**

## Your own first frame (a second plan for the same line)

- **What it is:** under a line's requests, **Use my own first frame** uploads an image you made (PNG, JPEG or WebP, at most 15 MB). You tick "made from our own approved art (no third-party picture or video frame)" first; the upload is refused without it.
- **It becomes a second plan beside the original-art one**, never instead of it. It takes the same line audio, the same action text and the same rig render from the original plan. Nothing is prepared again and no text writer runs, so adding it is free.
- **The image:** transparency is flattened onto white. An image that is not 9:16 is centre-cropped to 9:16, and it is scaled to 720×1280 like every first frame. What was done is shown with the plan (for example "your 1000x1000 image, centre-cropped to 9:16, scaled to 720x1280"), and the image shown is exactly the one sent.
- **Running it:** every request, for the original and for your frame, has its own **Run this** button. The confirm shows that request's estimate and the fal.ai budget. Each request shows "your own first frame" under Sends, and the same caps and checks apply: our line audio under the result, the length within one frame, the cost per clip and per second.
- **Results:** your plan has its own row in the results grid, under the line's original row.

## Self-hosted models (GPU proof of concept)

This is the engineering for `docs/GPU-INFRASTRUCTURE.md` §16, accepted 2026-11-22. Nothing here has been rented or run on a GPU yet.

- **Three more columns:**
  - **InfiniteTalk 480p**: image plus our line audio.
  - **Wan 2.2 S2V-14B 480p**: image plus our line audio.
  - **LatentSync 1.6**: re-syncs the mouth of this line's Kling 2.6 Pro clip to our audio, so it needs that clip first.

  All three are Apache-2.0. They are unticked by default.
- **The same plan and the same guarantees:**
  - the same first frames (our approved art) and the line's own audio, sent to our GPU worker as files, never by URL, so no public URL is needed;
  - the same per-run approval and the same one-confirm batch;
  - our audio under every result, with the length checked to within one frame;
  - the cost per clip and per second.
- **A self-hosted clip's cost** is its GPU seconds at the session's hourly price. Boot and idle time are recorded on the GPU session, and Settings shows the all-in cost per clip.
- **Where the clips run** is set in Settings › GPU worker: **Off** (the default); **Rented**, a RunPod Secure Cloud pod per session, billed per second and terminated when idle; or **Our own machine**, one address and a token. The worker image and its job API are in `studio-app/gpu-worker/`.
- **Caps:** self-hosted clips are not on fal.ai's budget. Rented sessions have their own monthly cap (default $50, warning at 80%). Before a launch the studio reserves the price × (maximum session length + 5 min) and refuses a launch that would not fit. A clip still running when the cap is reached (for example, when the cap is lowered) is stopped with the reason, and the pod is terminated.
- **Idle shutdown,** in four layers:
  1. terminate after 5 idle minutes;
  2. terminate after 120 minutes in any case;
  3. a sweep at start-up and every 30 s terminates any pod with our name prefix that is not a live session, and closes sessions whose pod has gone;
  4. the worker refuses jobs past its own limits.

  The RunPod key stays on the studio and is never sent to a pod.
- **Not runnable yet:** a model whose ComfyUI workflow is not pinned (`api/oddstudio/gpu_workflows/`) cannot run, and the page says so. The workflows, the node commits and the weights manifest are the remaining step at no cost before the paid proof of concept (`studio-app/gpu-worker/README.md`).

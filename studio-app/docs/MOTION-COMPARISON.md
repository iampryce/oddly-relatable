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

## Talking shots (WaveSpeed)

A talking shot is a speaking line from a still and the line's own recorded audio. It runs in the same shot comparison, as one more column per provider.

- **Providers** (Settings > Motion > Talking-shot provider; the setting picks which one is ticked by default):

  | Provider | Endpoint | Price | Default first frame | Terms status shown on every clip |
  |---|---|---|---|---|
  | **WaveSpeed InfiniteTalk fast** (default) | `wavespeed-ai/infinitetalk-fast` | $0.015 per second of audio, rounded up, 3 s minimum | cutout on plain colour | "InfiniteTalk, Apache-2.0 model, hosted on WaveSpeed; commercial-use terms not yet confirmed in writing" |
  | WaveSpeed Kling v1 AI Avatar Standard (fallback only) | `kwaivgi/kling-v1-ai-avatar-standard` | $0.05 per second of audio, rounded up, 3 s minimum | medium | "Kling terms not yet confirmed in writing: not for publishing" |

  Kling v1 is never chosen or ticked by itself. In the hand test it gave clean hands but heavy eyelids and a toothy grin even with a neutral prompt. A new provider is one entry in `shot_compare.TALKING` plus its run function in `TALKING_RUN`.
- **What is sent:** `image` (the first frame), `audio` (the line's own recording), `prompt` and, for InfiniteTalk, `seed`. Both files are sent as the studio's short-lived signed links, so `PUBLIC_URL` must be set. The exact body is shown with the request before Run.
- **The prompt is neutral.** The default is "<name> speaks the line: formal, composed, neutral face, eyes wide open as in the image, small nods, no smile", followed by the no-text rule and the "keep the design" sentence. It is NOT the plan's action text. You can edit it per plan, but attitude words (pompous, smug, grin, chin raised and similar) are refused, unless negated as in "no smile". The attitude belongs to the scene's expression setting and the approved poses, not the video prompt.
- **The seed** is shown and editable per plan. It is saved with the clip.
- **Head and shoulders** (720×900, vertical 4:5): cut automatically from the approved neutral pose on the approved set. The neck and shoulder line are found by the rig's own measuring (`rig_extract.py`). The head sits near the top (4% margin) and the frame ends around the top of the vest; a very wide head is fitted to the width, so a little more vest shows. New plans get it in the free preparation. An older plan shows **Make the head-and-shoulders first frame (free)**. A frame that does not exist is never replaced by another one silently: the run is refused.
- **Cutout on plain colour** (InfiniteTalk's default; 720×900): talking characters have no background. The first frame is the character's own approved pose (its transparent art, never the set plate) with the same head-and-shoulders crop, on a flat key colour. There is no gradient, no shadow and no set. The colour is #FF00FF unless the character's approved art comes close to it (then #00FF00, #0000FF, #00FFFF). It is recorded with the plan (`key_colour`). The art's edge is hard, so no pixel of the first frame mixes art and key colour. Only the image sent to WaveSpeed changed: the same prompt rules, cost, cap and no automatic retry apply.
- **Keying (free, local, after the clip):** a separate job removes the key colour from the finished clip, which is itself never changed (`talking_key.py`):
  - a colour key with a small similarity (0.12) and a soft blend (0.10);
  - the matte pulled in by 2 px, past the light halo that scaling leaves along the outline;
  - one pixel of edge softening;
  - in the edge band only, each pixel un-mixed by how much key colour it holds. A half-white, half-magenta pixel becomes white at half opacity; nothing magenta stays on the thick outline or white hair; purple or pink clothing inside the character is never touched.
  - a choke of the faintest edge alpha.

  Outputs: a **transparent copy** (VP9 WebM with alpha and our line audio, ready to place over the set at assembly), **previews over the episode's approved set and over mid-grey**, and a **check image** at 10%, 50% and 90% of the clip (set above, grey below). They show under the clip in the results grid. If keying fails, **Key again (free)** reruns it.
- **Cost before every run:** the estimate is the audio length rounded up × the rate, with the 3 s minimum (6.22 s = 7 s = $0.105 for InfiniteTalk). Only you start a run, with **Run this** or the batch's one confirm.
- **Caps:** a hard cap per plan (Settings > Motion, default $0.50, editable on the plan) covers every talking-shot run of that plan, retries included. A task WaveSpeed accepted counts even if it failed later. The experimental budget (Settings > Motion) still applies, and hosted spend from fal.ai and WaveSpeed is counted together there.
- **Never retried by itself:** a submit is sent once. Only the status checks and the download are repeated after a rate limit, a server error or a dropped connection. A failed shot stays failed until you run it again. The same rule now applies to every paid clip in the shot comparison: the job runner's automatic retry never re-sends a paid request.
- **Stored at once** (WaveSpeed deletes outputs after 7 days): the provider's file as delivered, and the clip with our line audio laid under it at the frame's size (720×900 for head and shoulders), with the length check. Saved with the clip: the provider, endpoint, prompt, seed, cost, billed seconds, the provider's output size, the task id and the terms status.
- **Not for publishing:** every clip is marked `publishable: false` with its terms status, and shows it in the grid. Comparison clips are never offered for publishing; only an episode's own rendered video is.
- **The key** is `wavespeed_api_key` under Settings > Credentials. It is encrypted at rest, only ever put in the Authorization header, and never returned, logged or stored anywhere else.

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

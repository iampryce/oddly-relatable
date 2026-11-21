# Motion Model Comparison: shot comparison

Production › Motion Model Comparison › **Shot comparison** compares hosted AI video models with the rig animator on one recorded line of a real episode.

- **Inputs:**
  - Only the studio's own approved art: the scene's approved set plate, with the speaker's approved neutral pose composed onto it locally (720×1280 first frame).
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

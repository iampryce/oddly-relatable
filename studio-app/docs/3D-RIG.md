# Studio 3D rig animator

The Studio 3D rig animator turns each character into a 3D stickman, built from the character's approved poses and colours:
- a round torso wearing the approved clothing art;
- black tube limbs;
- mitten hands and shoes;
- the big flat head.

Characters can turn, walk, sit on a chair facing any direction, stand up and turn their heads, without losing a body part. The renderer is three.js. It runs on the CPU, needs no paid service, and gives the same frames every time.

It is a Motion option beside the 2D rig animator. The 2D animator stays and nothing is removed.

## Head angles (PR 1)

The head is a flat face picture that turns with the body. There are four views:
- **front:** the approved neutral pose;
- **three-quarter**, **side** and **back:** drawn once per character, each facing right. The left-facing views are the same drawings, mirrored.

Only the neutral head is drawn in these angles. Expressions stay front-only, which is what close-ups use.

Making the angles, on the Characters page, under **Head angles (3D rig)**:
- **Start:** choose the angles to draw and click **Draw N angle(s)**. Nothing is drawn by itself.
- **Cost:** shown first, about $0.05–0.20 per image. A cap refuses a request that could cost more. At most one request per character runs at a time.
- **Identity:** each angle is drawn by the pose-sheet image provider, with the **approved neutral pose as the reference image**, so the face, hair and colours match. It needs an approved neutral pose first.
- **Review:** each drawing waits for your **Approve** or **Reject**. There is one approved drawing per angle; approving a new one retires the old one. Head angles never change a character's expressions or art status.
- **Until approved:** the 3D renderer uses a **mock** for that angle, a squashed copy of the front head (three-quarter, side) or the head's outline filled with the hair colour (back).

API (`oddstudio/head_angles.py`):
- `GET /api/characters/{id}/head-angles`
- `POST /api/characters/{id}/head-angles/generate {angles, max_usd}`
- `POST /api/head-angles/{asset}/decision {decision}`
- the `head_angles` job.

The drawings are character assets of kind `head-angle`. The asset's `expression` field holds the angle.

## The renderer (PR 2)

Settings › Motion has two rig animators side by side:
- **Studio 2D rig animator:** unchanged, still available.
- **Studio 3D rig animator (three.js, CPU, free):** the 3D one.

Both use the same acting renderer (`production/animation/render-acting.mjs`). With the 3D option, the studio adds `"engine": "3d"` to the render spec and passes each character's approved head drawings (`cast[key].head_angles`).

What stays the same:
- the choreography: seats, walking, sitting down and standing up, timed actions, scene and set changes;
- the shots, speech bubbles, captions, the optional hook banner and the end card.

Only the characters are drawn differently (`production/animation/rig3d.mjs`):
- **Body:** built from the approved 2D rig. A round torso in the clothing colour, with the approved clothing art on its front; black tube limbs with round joints; mitten hands; shoes in the shoe colour. Every frame keeps every limb at its length, so no body part is lost.
- **Face:** the front head is the live 2D face, so the line's expression, lip sync, blinks and eye direction work as before.
- **Turning:** the head picture follows where the body and head point: front, three-quarter, side or back, with left being the right drawing mirrored. Approved head drawings are used; any missing angle uses its mock.
- **Seated:** the knees come apart and the shins hang straight down. The sitting angle is fitted to each character's leg length and the seat's marked feet line, so the soles reach the floor. A seat marked higher than the legs can reach leaves the feet hanging a little rather than stretching the legs; a seat marked too low keeps the thighs level.
- **Desk front:** characters seated behind a desk are drawn before the desk front, so they sit behind it.
- **Pictures:** the storyboard pictures ("Refresh stills") come from the same renderer, so they match the video.

The pose maths is in `production/animation/rig3d-pose.mjs`, tested without the canvas or three.js packages.

### Running on the server

- **Packages:** the renderer uses `three@0.162.0`, the last three.js release that runs on WebGL 1, and `gl@8.1.6` (headless-gl), pinned in `skills/directing-stickman-videos/package.json`. headless-gl has a prebuilt binary for the worker's Linux (Debian 13, Node 22).
- **Display:** headless-gl needs a display on Linux, so the studio runs the renderer under `xvfb-run`, a virtual display; nothing is shown anywhere. The worker image adds `xvfb xauth libgl1 libglx-mesa0 libgl1-mesa-dri libxi6`.
- **No browser:** Chromium is not needed.
- **Speed:** on a 4-core laptop CPU at 1080x1920, a frame takes about 0.12–0.17 s, against about 0.11 s for the 2D renderer. Each character's face is redrawn and uploaded only when it changes (the software renderer's texture upload is the costly part), and only the box around the characters is rendered.
- **Determinism:** the same input gives the same frames.
- **Deploying:** the image is built and rolled out as before; the deploy script's backup and rollback are unchanged.
- **Check:** Settings › Motion › Test renders a short line with either rig animator.

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

## Seat facing and spacing (PR 3)

**Facing (owner correction 2026-11-23).** By default, facing follows the scene. The whole body turns (torso, hips, arms, legs and feet), and the head picture follows the total turn: three-quarter, side or back, the left-facing views mirrored. Each turn takes a moment.

- **The speaker** turns toward the person the line addresses (`look_at`), at about 65°: a profile when they are across the room. Without one, they turn the way the reference plan shows them facing; without that, toward the others.
- **Everyone else** turns the way the reference plan shows, at about 45°: left or right, or toward a named person. Without a note, they face the current speaker, or the last one between lines.
- **"Faces the camera" in the plan** is read as "toward the speaker". A listener in a close shot still faces the speaker, and reaction beats look at the speaker, not the camera.
- **The plan's facings** reach the renderer as `facing_notes`, per time range, from the confirmed people only.
- **Episode 14:** Mortimer at the desk on the left is turned right, toward the audience (a profile), and turns toward Sidney in scene 4. Ralph, Sidney and Winifred in the row on the right are turned about 45° toward him.
- **Your choice on a seat always wins.** In the Set panel, under the picture, choose toward the speaker, toward the camera, toward seat N, or away from the camera. An arrow on the picture shows the choice. Leave it on "by the scene" for the behaviour above.
- **Behind a desk,** the desk front still covers a turned speaker's legs. The chair in the set picture is not redrawn.
- **The 2D rig animator** draws everyone facing the camera, as before.

The owner's choice is stored on the seat (`facing`: `speaker` | `camera` | `away` | `seat:N`). A staging edit refuses any other value, a seat facing itself, or a seat that does not exist.

**Desk front.** The desk front is drawn over the characters seated behind it. It is not drawn over a row seated in front of it: seats whose hips are below the desk front's bottom edge.

**Spacing.**
- **No overlap:** seated neighbours' heads never overlap. When the seats are close, the cast is drawn smaller, but never below 318 px (60% of the default 530 px). Only seats side by side in the same row are compared, so a seat behind a desk and the row in front of it never collide.
- **Warning:** two seats closer than one head width at that smallest height (134 px for a typical head) get a warning on the Set panel, with the numbers. For example: "seats 3 and 4 are 129 px apart; need 134 px". The warning shows whenever seats are marked, edited, suggested or approved, and approving such a set also logs it on the episode.
- **Never a refusal:** most generated sets space their chairs for normal proportions, so refusing them would block them.
- **The prompt:** the set prompt still asks for at least one chair's width between seats.

## Acting and blockers (PR 4)

**Dialogue-driven acting.**
- **The speaker:** turns toward the person the line addresses (PR 3).
- **The listeners** react, the same way every render:
  - they look at the speaker;
  - they look at the person the reference plan has them facing, when the plan names one;
  - they look down on a sad, worried, embarrassed or similar reaction;
  - every few seconds they glance briefly (under a second) at another listener, never in a line's first second.
- **The head:** in the 3D rig, it turns toward where the eyes look (up to about 30°), on top of the body's turn. The 2D rig moves only the eyes.
- **Unchanged:** walking, standing up, sitting down, timed actions, and the optional hook banner.

**Expressions never block an episode.**
- **The nearest approved one:** a line asking for an expression with no approved pose uses the nearest approved one, in this order: the same name; a name match (a pose called "smug" for "very smug"); the same family (an "angry" pose for "furious"); otherwise neutral.
- **Where it shows:** the Cast section and the Cast panel list each substitution, for example "furious → angry". It is a note, not a blocker.
- **What still blocks:** only a character without any approved art.
- **Drawing them:** missing expressions can still be drawn ("Draw the missing expressions (optional)").
- **Poses waiting for review:** these count only when they are for an expression the script uses that has no approved pose yet. Leftover poses are not "to review" blockers.

**Changing a line's expression.**
- **Where:** in the Storyboard, under each scene, open **Expressions per line**. Each line shows the speaker's expression and each reacting character's.
- **Choices:** only that character's usable (approved) expressions are offered. A line whose expression has no pose shows which one it uses.
- **What changes:** only the storyboard line (`PUT /api/episodes/{id}/scenes/{scene}/lines/{n}/expression`). The script, its approval and the storyboard's approval stay as they are. The change applies to the stills and the next render.
- **When:** from storyboard review through video review; not during a render.

## 3D camera, Gate 1

A first look at native 3D characters through a perspective camera, for the owner to judge the new look. It is separate from the Studio 3D rig animator above, which is unchanged, and nothing in the studio uses it yet.

**What is drawn.** Uncle Mortimer, seated on a plain chair, seen from the front and from a three-quarter view (38°):
- **Body:** flat toon shading (two tones) with black ink outlines. Rounded parts get an inside-out copy pushed out along their normals and drawn in ink behind them; the chair's boxes get a slightly bigger inside-out box.
- **Head:** a ball. The face (eyes, pupils, brows, mouth) is drawn as vector shapes into a picture pressed onto the ball's front, so it turns and foreshortens with the head. No old face picture is used, and no three-quarter drawings are needed.
- **Mouth:** a shape for each of Rhubarb's visemes (A–H, X), sized to the face's mouth, as in the 2D renderer.
- **Expressions:** brow and eye settings per expression (neutral only for now).
- **Hair:** a mass on the top and back and the side tufts, in the hair colour. The hairline is painted with an ink edge where the hair meets the ball.
- **Clothing:** the torso in the clothing colour, with its details (neckline, collar, buttons, pockets) drawn as shapes. Stick limbs, mitten hands and shoes as before.

**The character spec.** Each character is a small file, `production/animation/cast3d/<key>.json`. It holds:
- the colours;
- the head size and where it sits;
- the hair shapes;
- the face's feature positions, as fractions of the head radius;
- the torso's size and outline;
- the clothing kind and its details;
- shoulder and hip positions, arm, leg and shoe sizes.

Mortimer's numbers were measured once from his approved neutral pose and its acting rig. The 3D character is built from these numbers only, never from the picture, so the old art can be retired.

**Files.**
- `production/animation/cam3d.mjs`: the renderer and the character builder.
- `production/animation/cam3d-math.mjs`: the pure maths (camera orbit, framing, planar picture mapping, outline shells, the seated body, mouth shapes, expressions), tested by `cam3d-math.test.mjs`.
- `production/animation/cam3d-still.mjs`: the stills and the comparison picture.

**Running.** It uses the same packages and display as the rig animator:

```
xvfb-run -a node production/animation/cam3d-still.mjs --spec production/animation/cast3d/uncle-mortimer.json \
  --out <folder> [--ref <approved pose png>] [--yaw 38] [--ss 2] [--bench 10]
```

It writes `front.png` and `three-quarter.png`. With `--ref`, it also writes `comparison.png`: the old approved art labelled "reference only", then the 3D front and three-quarter views. The reference is only read and never stored. Timings are printed as JSON.

**Speed.** Measured at 1080x608 in a Linux container (8 vCPU, software WebGL):
- **Plain frame:** about 30 ms.
- **2x supersampled frame** (the smoothed stills): about 75–90 ms.
- **Setup:** about 1 s, which builds the character and paints the hairline and face.
- **Peak memory:** about 320–400 MB.

The same input gives the same picture every time.

**Not in Gate 1:** animation, the other characters, expressions beyond neutral, and use in episodes.

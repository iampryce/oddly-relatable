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

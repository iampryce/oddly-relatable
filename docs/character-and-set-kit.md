# Character and set kit

How we made the Episode 14, scene 2 art (24 Nov 2026), written down so the next character and the next set follow the
same recipe. It covers the three identity layers, the house-style rules with measured numbers, the kit each character and
each set needs, the reference recipe and prompt structure that worked, the failures we hit and their fixes, the checks
every asset must pass, a proposal for running a new character from a brief, and what is still manual.

Nothing here changes the locked visual identity (`bible/VISUAL_IDENTITY.md`,
`bible/concepts/lookdev-richenv/CANONICAL_REFERENCE.md`). It applies it.

## 1. Three identity layers

| Layer | What it is | Who may change it | Example |
|---|---|---|---|
| **1. Studio identity** (global, locked) | The house style and its measured ratios: simple expressive 2D characters with big round heads, bold black outlines, large white eyes, black hook hands, black stick limbs, rounded shoes, flat colour; richly painted, warm, layered 2D environments | The owner only, by a decision recorded in `DECISIONS.md` | The v1 canon (`lookdev-scene-01.png`), Character 01 master v3, the ratios in section 2 |
| **2. Character identity** (reusable across episodes) | One character's design: head shape and size, face, hair, clothes and colours, hands, shoes, age cues, plus their approved kit (section 3) | The owner approves each asset; later episodes reuse it unchanged | Ralph: spiky brown hair, heavy lids, grey tee, dark grey shoes |
| **3. Episode assets** (per project) | Sets, set views, staging, composites and shot-specific art made for one episode | Made and approved per episode; **never promoted to a global rule** | The Episode 14 study (wide and reverse), Mortimer behind *this* desk |

Rules between the layers:
- A lower layer never overrides a higher one. An episode's set may be warm or cool, but it is still painted 2D; a
  character may age, but only with line-based cues.
- Something that worked in one episode (for example "the leather wingback") stays an episode asset unless the owner
  promotes it to a character's identity.
- Every generation names which layer each reference serves (section 4).

**What the studio already covers, and what is missing:**

| Layer | Covered today | Missing |
|---|---|---|
| Studio identity | `bible/VISUAL_IDENTITY.md`, `CANONICAL_REFERENCE.md` (hash-locked canon), `house_style.py` (`SET_STYLE`, style versions v1/v2), `character_assets.style_version` | The measured ratios as data the studio can check against; an automatic style check on new art |
| Character identity | `characters` (key, name, `visual_description`, `scope` recurring/episode, `art_status`, `expressions`, `locked`); `character_assets` (kind pose/sheet/head-angle/reference, expression, status review/approved/rejected, width, height, `figure_height`, `style_version`); the Characters page (poses, approvals, Draw the missing expressions, Head angles); the Bin | A **pose dimension** beside expression: posture (standing / seated), body turn (front / left / right), view (front / back), framing (full / chest-up). Today a seated, left-turned Ralph can only be stored as "an expression". A **kit checklist** per character showing which required cells exist and are approved. **Provenance** per asset (references used, prompt, route, original file) |
| Episode assets | `settings._sets` (sets with `episode_id`, `kept`, staging: seats with facing, floor line, desk front, standing area); set views (wide, speaker, audience, two-shot) with their own staging; `episodes.set_id`, `scene_set_ids`; storyboard shots, reaction beats and the band layout; the Lab's shot comparison records | A **reverse view** tied to its wide view as "the same room"; per-set **light direction** (for shadows and rim light); **occlusion masks** beyond the desk front (book stacks, lamps); the Stage 1/1b/2a approvals live in manifests in `studio-work/`, not in the studio |

## 2. House-style rules and measured ratios

Measured on 24 Nov 2026 from the files listed (cut-outs on our own grey-background method). Head width is the yardstick
for seated figures; figure height only works for standing ones.

**Standing figures (ratios to figure height H):**

| | v1 Character 01 sheet / master v3 | Mortimer | Ralph | Sidney | Winifred |
|---|---|---|---|---|---|
| Head width / H | 0.46 / 0.41 | 0.42 | 0.40 | 0.42 | 0.38 |
| Head height / H | 0.40 / 0.36 | 0.39 | 0.36 | 0.35 | 0.34 |
| Leg thickness / H | 0.020 / 0.017 | 0.010 | 0.010 | 0.010 | 0.012 |
| Outline / H | 0.011 / 0.010 | 0.007 | 0.007 | 0.006 | 0.010 |
| Torso width / head width | 0.63 / 0.68 | 0.60 | 0.54 | 0.63 | 0.63 |

(Mortimer, Ralph, Sidney and Winifred here are their approved standing neutral poses: 89, 135, 138, 136.)

**Outline thickness / head width:**
- v1 (sheet, master v3): about 0.024–0.027.
- Approved standing neutrals: about 0.015–0.017 (Winifred 0.027).
- The seated masters made with master v3 as the line-weight reference: 0.022–0.026 (Mortimer 02, Ralph 02, Winifred 01,
  Sidney 02). **They match v1.**

**The rules:**
1. **Head:** a large round head, width 0.38–0.46 of standing height. It stays round: no square jaws, no oval faces.
2. **Face:** large white eyes with small dark pupils, eyebrows as single strokes, a small flat mouth. **No nose.** Age and
   mood are added with lines only (forehead lines, cheek lines, under-eye lines, a jaw line), never with shading or new
   shapes.
3. **Outline:** one consistent black outline, about 0.025 of head width (master v3's weight). The approved standing art
   is thinner (about 0.016); new art follows v1.
4. **Limbs:** black stick arms and legs, no clothing drawn over the legs. Standing leg thickness about 0.017–0.020 of
   height (v1); the approved standing art is thinner (0.010–0.012) and is not the target.
5. **Hands and shoes:** black curled hook hands (never spread fingers); rounded shoes in the character's colour (brown, or
   Ralph's dark grey). No laces.
6. **Colour:** flat fills, no shading, no gradients, no shadows on characters.
7. **Environments:** richly painted, warm cinematic light, soft consistent shadows, foreground / middle / background
   depth, believable furniture and props; not photorealistic, not 3D, not flat vector.

The seated-limb thickness could not be measured reliably (the chair's outlines count as limb strokes); check it by eye
against master v3.

## 3. The kits

### Character kit

**Angles (decided 24 Nov):** the head stays **near-frontal**; the **body turns** toward the other person; the **eyes look
toward them**. A **back view** is the only other angle. True three-quarter heads are **not required**: our image routes
did not turn heads reliably (section 5), and the style reads well with a frontal head on a turned body.

| # | Asset | Use | Required |
|---|---|---|---|
| C1 | Standing neutral, front (the identity master) | Identity reference for every other asset | Yes |
| C2 | Seated master: body turned toward the other person (left or right as the scene needs), head near-frontal, eyes toward them, thighs on the seat, both shoes visible | Seated dialogue shots | Yes, per facing the stories use |
| C3 | Seated expression set: the same seat and turn, the expressions the episode needs (for example neutral, worried, sad, smug), with pupils toward the other person | Reaction cuts | Per episode, only the ones used |
| C3m | Figure-only mask for each seated master (hand-drawn polygons; no part of its own chair) | Compositing on the set's chairs | Yes, for every seated master |
| C4 | Back of head and shoulders (seated) | Over-the-shoulder shots | When over-the-shoulder shots are used |
| C5 | Standing expressions (front) | Standing scenes | As today |

Every kit image: one character, plain flat grey background (#D1D1D1), generous margin, crisp edges, so it can be cut out.

### Set kit

| # | Asset | Use | Required |
|---|---|---|---|
| S1 | Wide master, empty, landscape | Establishing and wide shots; the environment reference for every other asset in the episode | Yes |
| S2 | Reverse view of the same room, empty | Shot / reverse shot | When the scene cuts across the room |
| S3 | Staging on each view: seats, desk front, floor line | Placing characters | Yes (marked by the owner) |
| S4 | Occlusion notes per view: what stands in front of a seated character (desk top edge, lamp, book stacks) | Compositing | When characters sit behind furniture |
| S5 | Light direction per view (where the main light comes from) | Shadows and rim light at render time | Yes |

## 4. The reference recipe and prompt structure that worked

**References (our own approved art only; no reference-video frames, no third-party images):**

| Asset | Attach, in this order | Each reference's job, stated in the prompt |
|---|---|---|
| Wide set master | The v1 canonical scene | Style only: painting, light, colour, depth. "Do not copy its room." |
| Reverse view | The approved wide master (+ master v3 as a style note) | The same room: curtains, panelling, rug, wood, light, palette. No people. |
| Seated master (first character) | The character's approved standing neutral; the approved wide set; master v3 | Identity (highest priority); the chair only; outline and limb weight only |
| Seated master (later characters) | The character's approved standing neutral; **an approved seated master of another character**; the approved set | Identity; drawing style and pose to match exactly; the chair only |

**Prompt structure (six parts, in this order):**
1. **What each reference controls.** One line per attached file, with what it must NOT contribute ("Do not copy Ralph's
   face, hair, shirt or colours").
2. **Identity** (or the environment), listed feature by feature.
3. **Line weight and style:** "flat 2D colour with no shading, no gradients and no shadows anywhere", outline as thick as
   the line-weight reference.
4. **Pose / camera:** the body turn with the side named ("toward the viewer's LEFT, toward a desk off to the left"), head
   near-frontal, eyes toward the other person, thighs on the seat, both shoes visible.
5. **Composition and background:** the figure and chair only, plain #D1D1D1, generous margin.
6. **Avoid:** the specific failure modes (no nose, no trousers on the legs, no lace-up shoes, no other characters).

It ends with: generate exactly one image, no retries, no variants; copy the result to a named file and report the original
path and size.

**Run method (the Codex route):** one `codex exec` call per image, ChatGPT sign-in, references attached with `--image`,
the prompt on stdin, each call in its own **empty scratch folder outside the repository** holding only that call's
reference copies, sandbox `workspace-write`. Outputs are copied unchanged, recorded in a manifest (prompt file, reference
hashes, original path, size, SHA-256, review status), and reviewed against the references before any approval.

## 5. Failures we saw and their fixes

| Failure | Where | Fix that worked |
|---|---|---|
| **Character redesigned** into a different cartoon style (nose, open mouth, squarer head, trousered legs, lace-up shoes, short sleeves, thin brown outlines) | Sidney 01 | Fewer references (identity + one approved seated master of another character + the set) and an explicit sentence: "no nose, small flat mouth, round head, black stick limbs, rounded brown shoes, the same outline weight as Ralph; sleeves as in his approved art; add only line-based age cues". Sidney 02 came out on-model. |
| **Body not turning** (torso faces the camera; only the eyes turn) | Mortimer 01 and 02, Ralph 01 | Name the side and the parts ("body: shoulders, torso and knees turned toward the viewer's LEFT"); show an approved turned seated master as the pose reference (Ralph 02 → Winifred, Sidney 02). Mortimer 02 was accepted for chest-up desk shots, where the turn barely shows. Decision: near-frontal heads are fine (section 3). |
| **Chairs not matching the set** | Mortimer 01, Ralph 01 | Attach the approved set and say "controls ONLY the chair: the tufted dark leather wingback… / the dark wooden chairs with slatted backs". |
| **Thin limbs and outlines** (from the thinner approved standing art) | Mortimer 01, Ralph 01 | Attach master v3 as "line weight and limb thickness only". |
| **Shading** on a shirt or a chair | Ralph 01 (and a faint tone change on Ralph 02) | "Flat colour with NO shading … the grey t-shirt is one flat grey, the chair flat with outline only". Check by eye and by the shading check (section 6). |
| **No thighs** (legs dropping from the seat edge) | Mortimer 01, Ralph 01 | "Draw the THIGHS resting on the seat, knees bent, lower legs down to the floor, both shoes visible". |
| **Codex did not copy its own output** (it said it could not find the file, or that the image came back only as in-memory data) | 7 of 9 calls | Not a failed generation: the image is in `~/.codex/generated_images/<session id>/`. Match the folder to the call's session id (the first event of `--json`), copy it unchanged, note it in the manifest. Never re-run the call. |
| **Codex made more than one image in one call** (asked for exactly one) | Mortimer back view 02 | Count the images in the call's session folder after every call; use the first as the candidate, keep the extra, report it (it uses the allowance). |
| **Unrequested motifs** (scales of justice, a statuette) | Study wide | Accepted by the owner; to avoid, list them under Avoid. |
| **Reverse view geometry drift** (two windows behind the chairs where the wide view shows one) | Study reverse | Accepted as minor; when it matters, describe the wall precisely and attach the wide view. |
| **Composites look pasted on** (flat, evenly lit figures in a warm, textured room) | Look-stills | Render-time grade on the figure layer only: a warm cast, a soft rim on the side the light comes from, the shadow cast away from the light. No art file changes. |
| **Leftovers of a figure's own drawn chair** (slivers by the thighs, rail stubs on the shins, a "second seat") after automatic removal | Shot 4 v3 | Do not rely on automatic removal for seated figures: a **hand-drawn figure-only mask** per seated master (head, hair, ears, neck, torso, arms, hands, thigh-and-shin strokes, shoes as hand-placed shapes), with wood colour removed only inside hand-placed chair zones, each shin clipped to its median width and only the thick thigh stroke kept. Store the mask as an asset with its polygon spec. |
| **Mismatched sizes in a row** (one figure towering) | Shot 4 | Codex drew the seated masters at different head-to-body ratios (Winifred's head 24% smaller than Ralph's), so "equal head width" enlarges her body. Use one scale for all images of a scene (the nearest figure up to +8%) and check the row by eye. |
| **The wrong part of a face swapped in** (double head, the old mouth showing) | Animatic, sad face | Align faces on the face circle (the longest unbroken run of skin on a row, which never includes the ears) and cut the swapped head at the chin by counting skin across the face's width (a mouth line does not stop it). |

## 6. Pass/fail checks for each asset

A candidate passes only if every check below passes; the owner then approves. Checks marked **auto** can be measured;
the rest are by eye against the references side by side.

**Character assets (C1–C5):**

| Check | How | Pass |
|---|---|---|
| Identity | By eye beside the approved standing neutral | Recognisably the same character: head, hair silhouette, eyes, brows, mouth, clothes, colours, hands, shoes |
| Round head, no nose | By eye | Round head; no nose; small mouth |
| Outline weight | **auto**: outline / head width | 0.020–0.030 |
| Limb thickness | **auto** on standing art (leg / height); by eye on seated art against master v3 | Standing 0.015–0.022 of height; seated as thick as master v3 |
| Flat colour | **auto**: variance inside each flat colour region | No gradients or shading on the character or its chair |
| Hands and shoes | By eye | Black hook hands; rounded shoes, no laces |
| Pose | By eye | Body turned to the named side; head near-frontal; eyes toward the other person; thighs on the seat; both shoes visible |
| Chair | By eye beside the set | The set's chair design and colour |
| Background | **auto**: border pixels | Uniform grey within ±8 levels; no floor or shadow |
| Cut-out | **auto**: after our cut-out, no grey halo (edge pixels unmixed), no holes in eye whites | Clean |
| Text and extras | By eye | No text, logos, watermarks or other characters |

**Set assets (S1–S2):**

| Check | Pass |
|---|---|
| Style | Richly painted, warm, layered depth; matches the v1 canon's family (not photorealistic, not 3D, not flat vector) |
| Layout | The furniture as briefed (count and position, for example "exactly three chairs on a shallow diagonal") |
| Continuity (reverse) | Same curtains, panelling, rug, floor, wall colour, light and palette as the wide master |
| Empty | No people, animals, text or logos |
| Usable | Clear floor where characters go; a seat for each seated character; foreground does not block the action |

**Composites (look-stills, later the render):** scale consistent between shots (head about 0.6 of the chair's width);
shadow away from the light; the furniture in front (desk top, lamp, books) drawn over the character; no leftover chair
lines from the character's own art.

## 7. Proposal: a new character from a brief

1. **Brief** (owner): name, role, age, personality, clothes and colours, the scenes it will be in (standing or seated,
   which side it faces). The studio checks it against the house-style rules and lists the kit cells the stories need.
2. **Standing neutral master (C1):** one image from the brief, attaching the v1 canonical scene and master v3 as style
   and line-weight references, plus one approved character as a style example. The automatic checks run; the owner
   compares it with the references.
3. **Approval gate:** nothing else is made until the owner approves C1. The approved C1 becomes the character's identity
   reference (layer 2).
4. **The rest of the kit:** each required cell (C2–C5) is one request, one image, with the recipe in section 4. The
   automatic checks run on each; failures show the reason and offer a re-run with the fix from section 5 (each re-run
   is its own click and cost). The owner approves each cell.
5. **Kit complete:** the Characters page shows the kit grid with every required cell approved. Later episodes reuse it;
   an episode adds only the cells it needs (for example a new expression).

**The two image routes:**

| | Image API run by the studio | Codex run on the owner's machine |
|---|---|---|
| How | The studio's image provider (OpenAI images, `images/edits` with references), a job on the worker | `codex exec` on the owner's Mac, ChatGPT sign-in, references attached locally |
| Cost | Per image, shown before the click: the studio estimates about $0.05–0.20 per image (`IMAGE_USD` 0.17 for a 1024×1536 set image) | The ChatGPT plan's image allowance: no per-image charge, but a quota whose remainder is unknown |
| Sizes | Chosen in the request (the studio uses 1024×1536 for sets) | Not selectable: we got 1024×1536, 1672×941 and 1199×1312 |
| Transparency | Not used; grey background and our cut-out | Not available; grey background and our cut-out |
| Fits | Routine kit cells, anything the studio should track and approve in one place | Exploration and the first masters of a new look, when the owner is at the machine |
| Weak points | Cost per image; the studio's prompts must carry the recipe | Manual: runs only on the owner's machine; Codex often failed to copy its own output; results reach the studio only by import |

**Verify before relying on either route:**
- **Commercial-use terms of the generated images.** For the API route, OpenAI's business terms (the Services Agreement)
  on ownership and use of outputs. For the Codex route, OpenAI's Terms of Use for the ChatGPT plan that signs Codex in.
  Record the document, version and date checked. Until then, treat both as **unverified** and do not publish.
  (Separately, Kling output stays unpublished until fal confirms commercial use in writing.)
- That attached reference images are our own approved art only, and that the request sent is recorded with the asset.
- The actual sizes and costs of a test image on each route, compared with the estimates.
- For Codex: the CLI version, that the image-generation feature is on, and that each call runs in an empty folder (Codex
  can read everything in its working folder).

## 8. What is manual today, and what automating it needs

| Manual today | What the studio would need |
|---|---|
| Choosing references and writing each prompt | A prompt builder that assembles the six-part prompt from the kit cell and the character's identity, with each reference's role, shown before the click |
| Running Codex and recovering its output when it fails to copy | An "Import local generations" screen: upload the file plus its manifest (prompt, reference hashes, original path, session id); the studio stores it as a candidate with provenance. The studio never runs Codex |
| Manifests and review sheets in `studio-work/` | Provenance stored with each asset (`character_assets` and set records) and a side-by-side review view |
| Approvals recorded in manifests only | Approval in the studio, per kit cell, by the owner |
| Measuring ratios, checking shading and backgrounds | Automatic checks (section 6) run on every candidate, with the numbers shown |
| Cutting out figures | Our cut-out run as a job on import, the transparent copy stored beside the original |
| Removing a figure's own chair, placing it on the set's chair, drawing the desk and props over it | Seat placement from the set's staging; occlusion masks per view (desk top edge, props); a "seat replaces the set's chair" option per seat |
| The warm grade, rim light and shadow direction | Per-view light direction in the set's staging; a render-time grade on character layers |
| Kit completeness | A kit grid on the Characters page (posture × turn × view × expression), required cells per character |

**Effort estimate: about 14 working days**, as small PRs:

| PR | What | Days |
|---|---|---|
| 1 | Pose dimension on character assets: posture, body turn, view, framing (migration, additive; API; tests) | 1.5 |
| 2 | Kit grid on the Characters page: required cells per character, status per cell, approve/reject per cell | 2 |
| 3 | Provenance on assets: route, prompt, references with hashes, original file, size; shown on the asset | 1 |
| 4 | Prompt builder for the image API route, with each reference's role, the six-part structure and the cost shown first | 2 |
| 5 | Import local generations (the Codex route): upload with manifest, stored as candidates with provenance | 1.5 |
| 6 | Automatic checks: background, cut-out halo, outline / head width, standing limb ratio, flat-colour check; results on the candidate | 2.5 |
| 7 | Set kit: reverse view linked to its wide view; per-view light direction and occlusion masks in staging | 1.5 |
| 8 | Renderer: seat replacement, occlusion layers, render-time grade (warm cast, rim, shadow direction) on character layers | 2 |

Each PR is one commit with tests and docs, default behaviour unchanged, no paid calls in tests.

## 9. Where the Episode 14 files are

On the owner's Mac, not committed (`studio-work/episode-14/scene-02/art-generation/`):
- `stage-01/`, `stage-01b/`, `stage-02a/`, `stage-02b/`: references, prompts, generated originals, review sheets,
  manifests with the owner's decisions (24 Nov): the study wide and reverse, Ralph 02, Winifred 01 and Sidney 02
  approved as masters; Mortimer 02 accepted for chest-up desk shots; Sidney 01 rejected; Ralph's expression sheet 01:
  alert, worried and sad accepted, flinch rejected; sheet 02 (pupils left, a hurt-wince flinch) awaiting review;
  Mortimer back view 01 accepted, 02 (hair strokes) and one unrequested extra awaiting review.
- `look-stills/` (v1 to v4) and `animatic-v1/`: the composites, the hand-drawn figure masks and the free animatic of
  scene 2, with the scripts that made them.

Nothing from these stages has been imported into the studio yet. The direction decided on 24 Nov: these scripts are the
reference implementation; the studio imports the approved art with provenance, binds each shot to its assets, and
renders the scene itself (the storyboard-driven scene engine).

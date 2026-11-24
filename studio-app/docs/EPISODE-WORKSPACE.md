# The episode workspace

Everything about an episode is on one page, in collapsible sections. The tabs are gone.

## Sections

The sections, in this order:
1. Set
2. People / who is who
3. Reference plan
4. Lines and speakers
5. Video notes
6. Cast and poses
7. Script
8. Storyboard
9. Production
10. Review
11. Publishing
12. History

A script-first episode has no recording, so it does not show People, Reference plan, Lines and speakers or Video notes.

Each section header shows:
- a **status badge**;
- a **blocking** flag, when the section stops the next step;
- one line saying what is needed.

| Status | Meaning |
|---|---|
| done (✓) | finished |
| needs you (warn badge, e.g. "accept", "review") | blocks the next step |
| failed | its last job failed; the message is in the section's one line |
| running | a job is queued or running |
| to do (no colour) | needed later, not blocking yet (e.g. the set before production) |
| waiting | an earlier step comes first |
| not needed | nothing to do for this episode |

- **Quiet by default (2026-11-23): only the current step is open.** That is the step that blocks the episode, or, when nothing blocks, the first step still to do in the episode's order (Talking shots comes after the storyboard). Every other section is one collapsed line: its title, its badge (✓ when done) and its note on one line. Its job lines show when you open it.
- **Only the current step is flagged "blocking".** A failure in a later step keeps its red badge and note, without the flag.
- The page order of the sections is unchanged (the 22 Nov order, Set first).
- **The Now box** (top of the episode, 2026-11-23): the single next action, the current step's note, and its cost:
  - "no cost: your decision" for approve, accept and confirm;
  - the talking shots' own estimate ("about $0.135 for 3 line(s), shown again with the total before anything starts");
  - otherwise "cost shown before it starts", never "free" by guess. A retry can be paid again, so it says this too.

  Its button never starts anything paid by itself. "Run N line(s)" opens Talking shots and runs its own Run selected lines flow on the lines not yet keyed: free preparation first where needed, then the confirm with the total, each plan's cap and the budget. Nothing starts without your OK. Any other step's button opens that step, whose own button and confirm do the rest. While a step is running, the box only says so.

- A failed job blocks only a step that is due now. An old failed set candidate shows red, but production is far off, so it does not block the episode.
- What you open or close lasts for this visit only: the next visit starts quiet again, with the current step open.
- A section you opened once stays loaded while collapsed, so an unsaved edit in it survives closing it.

### The banner and the job lines

- **The banner** at the top appears only when something blocks the next step. It says what and where, with a button that opens that section. When nothing blocks there is no banner; work in progress is one quiet line ("Working: …").
- **The episode's last error** shows only while the episode is in a failed stage; after a retry that worked it is in History, not at the top.
- **Overview:** the queue warnings (the job queue down or missing) stay, because jobs cannot run. The disk's yellow level (80%) is a line in the Disk card; only the red level (90%) is a banner.
- **Job lines.** Each section lists its own jobs: every queued or running job, and the latest failure of each kind (per scene, per set) with its message and a Retry button. A later success of the same kind clears an older failure.
- **Where the statuses come from:** `GET /api/episodes/{id}/workspace` (read only; `oddstudio/workspace.py`). The rules are a pure function and are tested directly.

## Set section

Settings › Sets is now only the **library**: the sets kept for reuse, and the library sets made there. An episode's own sets are made, approved, staged and kept in its Set section.

### Set candidates

Each set made for the episode is shown as a large picture, with:
- its **status** (candidate, approved, rejected);
- its **cost**: the image, plus the seat suggestion;
- **"N seats for M people"**. When there are fewer seats than people, it also says how many will stand.

The buttons on each candidate:
- **Approve** or **Reject**. These are your decisions; nothing is approved for you.
- **Generate another**: one more candidate from exactly the same request, whatever the boxes say now.
- **Keep for future episodes.**
- **Use for this episode**, on an approved set.

### Staging on the picture

The staging is edited on the picture, for candidates and approved sets alike:
- **Add a seat**: click where the seated feet rest.
- **Mark the desk front**: click two corners.
- **Set the floor line**: one click.
- **Set the standing area**: two clicks.

The pixel numbers are under "Exact positions". Editing an approved set's staging never changes its picture or its approval (`PUT /api/sets/{id}/staging`).

### Suggested seats

After a candidate is generated, the vision model looks once at **our own generated picture**, never a video frame. It suggests:
- the speaker's seat **behind** the desk, with the desk front marked;
- the other seats as an audience row, left to right;
- the floor line and the standing area.

How the suggestion is used and checked:
- **Use and adjust:** while nobody has edited a candidate's staging, the suggestion is its staging. Adjust it before approving. Once you have edited, "Use the suggestion" applies it only when you click.
- **Again:** "Suggest seats again" runs it once more. Its cost (about $0.002) is shown first, and it is refused over the cap.
- **Checks:** every seat is inside the picture with the hips above the feet. A desk front counts only with a seat behind it. There are at most 8 seats, the speaker's seat first. Duplicates are dropped.
- **Code:** `oddstudio/seat_suggest.py`.

### Text only, and the exact request

- **Text only.** No previous set and no style reference image is sent, unless you attach a reference picture of **your own**: you must confirm it is yours (not a video frame or someone else's image). It is then sent with `images/edits` until you remove it.
- **The layout leads.** Your description, or the set notes verbatim, comes first, marked "follow this exactly; where anything below differs, this description wins". The studio's drawing style is short (at most 45 words) and comes after it. The studio rules and the variety guard follow.
- **One box.** The exact request (endpoint, model, size, reference image, full prompt) is shown before you generate, and on every candidate afterwards.

## Set notes

The set notes describe each room, in words from fixed lists:
- the room type, size and how big it feels;
- the furniture, with shape, material and colour;
- the walls, floor and light, as colour words;
- the window, door and bookcase positions;
- **the roles layout**, as positions only: who sits behind the desk, who sits in a row, who stands. For example: "Layout: the main speaker seated behind the desk; 3 others seated in a row facing the desk."

Names, looks, brands and text are removed and counted. The notes are editable, and "Propose" uses them verbatim.

### Read the room from a video

This makes the set notes only, from a video you upload. Before anything is sent, it shows:
- the frames it will use (4 to 8, spread over the video);
- the one call;
- the cost and the cap.

It is refused over the cap.

It writes only the set notes, on the proposal. It never touches the recording, lines, speakers or cast. The video and the frames are deleted after the call, whatever happens. Code: `oddstudio/room_read.py`.

## Reference plan: only confirmed people count

Once "who is who" is confirmed, a person nobody confirmed is left out of the scenes. So:
- **Seats:** they take no seat. The note "N seated person(s) will stand" counts only the people who will be on screen. The seats a new set is generated for count the same way.
- **Beats:** their beats, and turns towards them, are not acted. The plan lists only the acted beats, and says how many were skipped. With nobody confirmed, no beat is acted.

## Set views

An approved set's card in the Set section has **Views of this room**:
- the speaker, audience and two-shot views, each with its camera words (from "Read the room from a video", editable), its picture and its own staging;
- a list of the view each shot will use.

Missing views use the wide picture. See [SETS.md](SETS.md#views-of-one-set-featset-views).

## Talking shots and the first draft (audio episodes)

The **Talking shots** section sits between Storyboard and Production. It never blocks the episode.

- **The table** lists every line with:
  - its talking-shot status: not run, preparing, queued, running, done (keying), keyed, or failed with the reason;
  - its audio length and cost: the estimate before a run (audio rounded up, 3 s minimum, $0.015/s on WaveSpeed InfiniteTalk fast), the charge after;
  - its plan's cap used;
  - a link to the keyed clip over the set.
- **Run selected lines:**
  - First it prepares any chosen line that has no plan yet, for free: no text writer and no rig render are used, and the cutout first frame is made if it is missing.
  - Then it shows **one** confirm with the TOTAL estimate, each plan's cap and the experimental budget. Nothing starts before you accept.
  - A paid call is never retried by itself: a failed line stays failed until you tick it and run it again.
- **Make the draft (free)** builds the whole episode at 1080×1920:
  - **Picture:** each scene's crop of the approved set plate, filling the frame with no bars.
  - **Cast:** everyone at their seats, in staging order with the speaker first, from their approved neutral poses at the rig's cast height for that set, so all heads share one scale. Anyone seated behind a desk front shows only the upper body.
  - **Speaker:** the keyed talking clip, placed exactly over the pose it was cut from. A line without one shows the neutral pose and a red "no clip yet" mark.
  - **Sound:** the recording, so the script order and pauses are as recorded; then the end card from Settings.
  - **Where it goes:** the Video Library, with its per-scene pieces, as "Draft: not for publishing". It is never the episode's video, so it is never offered to the publishing step.
- **Camera per scene:**
  - **Computed:** a 9:16 crop that holds everyone in the scene with a safe margin of 6% of the frame width on each side, with the heads about a third of the way down.
  - **Too narrow a set:** if the set is too narrow for everyone (Episode 14's four seats span about 93% of a 2:3 plate), the crop is the closest one inside the plate. It never makes bars, and the draft's notes name who is outside the safe margin.
  - **Upscaling:** a crop narrower than 1080 plate pixels is scaled up, and the notes say by how much.
  - **Adjusting it:** the section shows each scene's plate with the crop rectangle, everyone's place and the safe-margin lines. Move or resize the crop (always 9:16, always inside the plate) and **Use this crop**; **Back to computed** undoes it.

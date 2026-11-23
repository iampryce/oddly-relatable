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

| Status | Meaning | Starts |
|---|---|---|
| done | finished | collapsed |
| needs you (warn badge, e.g. "accept", "review") | blocks the next step | expanded, flagged "blocking" |
| failed | its last job failed; the message is shown | expanded |
| running | a job is queued or running | expanded |
| to do (no colour) | needed later, not blocking yet (e.g. the set before production) | expanded |
| waiting | an earlier step comes first | collapsed |
| not needed | nothing to do for this episode | collapsed |

- A failed job blocks only a step that is due now. An old failed set candidate shows red, but production is far off, so it does not block the episode.
- Your own open and closed choices are remembered in this browser, per episode.
- A section you opened once stays loaded while collapsed, so an unsaved edit in it survives closing it.

### The banner and the job lines

- **The banner** at the top says what is blocking the episode and where, with a button that opens that section. When nothing blocks, it says what is running, or that nothing is blocking.
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

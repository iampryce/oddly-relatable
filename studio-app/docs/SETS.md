# Sets (backgrounds)

The episode page (where sets are made, approved and staged) is described in [EPISODE-WORKSPACE.md](EPISODE-WORKSPACE.md).

**Every episode gets a new set of its own.** An earlier set is used again only when you keep it for reuse and choose it (owner rule 2026-11-22). There is no silent default.

## Choosing the episode's set

- The **Set** card on the episode (below the pipeline) shows the current set.
- **Choose an approved set** opens a picker with two groups:
  - **This episode's sets:** sets made for this episode, and any set it already uses.
  - **Kept for reuse:** sets you kept for future episodes, and the studio's repository plates.
  - Each set shows the other episodes that already use it, and reuse always asks for confirmation.
- **Another episode's set is not offered** until it is kept. The card says how many are hidden. Choosing one through the API is refused with "Keep this set for future episodes" (`409`), and so is adding it for scene changes.
- **Keep this set for future episodes** is a checkbox on each set in the episode's Set section and on each set in the Settings › Sets library (`POST /api/sets/{id}/keep {"keep": true|false}`). Un-keeping a set hides it from new episodes; episodes already using it keep it.
- **The writer** is offered only this episode's sets and the kept ones.
- **Production cannot start without a set.** The message is: "choose this episode's set first (Storyboard tab, Set): there is no default set".
- A set that is withdrawn (rejected) after it was chosen also blocks production until another one is chosen.
- When the video notes name a setting, a matching set among this episode's own and kept sets is shown as a suggestion only. It is never applied by itself.
- Episodes that existed before this change keep the set they rendered with (migration `0008`).
- API: `GET /api/episodes/{id}/set-options` and `PUT /api/episodes/{id}/set` (the set must be approved and allowed for the episode; not while it is producing or publishing).

## A new set for the story

The **A new set for this story** box sits on the same card. The studio proposes an original set description, you edit it, and only your click generates a candidate.

- **Set notes from the video (audio episodes, words only).**
  - When the video is analysed, one more vision call reads a few frames per distinct room (at most 3 frames for each of at most 4 rooms). The rooms are the notes' settings after smoothing, so a short cut to another angle is not a new room.
  - The answer must use fixed lists: room size, the main piece and where it sits, the number of seats and how they are arranged, each piece of furniture (item, shape, material, colour, place, including windows, doors, shelves, plants and lamps), the walls, floor, ceiling and light as colour words, and the mood.
  - Anything else is removed and counted: names, brands, logos, text, artwork and people. Screens and boards are always drawn blank.
  - Each room becomes one sentence built only from those words. It is editable under "Set notes from the video" (`PUT /api/episodes/{id}/set-notes`).
  - The frames and the video are deleted after the job, and no frame ever goes to an image generator. To make the notes again, upload the video again.
  - The cost is part of the notes estimate shown before the upload (two rooms assumed) and counts against the notes cap.
- **Audio episodes: "Propose from the video notes" (free).**
  - With set notes, each room's notes are used verbatim, one proposal per room. An office and a meeting room give two proposals, each with its own Generate button.
  - Older notes without set notes give the earlier fixed sentence from the notes' list values.
- **Script-first episodes: "Propose from the story (AI writer)".** One sentence from the title, logline and scene descriptions; quotes and cast names are removed.
- **Exactly what is sent.** "Sent to the image API (exactly), part by part" lists each part:
  - **studio style:** one flat-colour set style that matches the stickman cast. It sets no palette, light, material or mood, and has no warm, cosy, painted-wood wording.
  - **your description:** "Setting:" and the room's text.
  - **studio rules:** always added. An empty room with no people; seating for at least the cast (the most people the notes show at once, else the number of speakers); chairs and sofas facing the camera or seen from the side, never with their backs to the camera; seats at least a chair's width apart (the cast are stick figures with big heads); no text, signs, logos or brands; nothing copied.
  - **variety guard.**
  - **view:** for two-sided rooms.
- **No reference image.** Sets are generated from text only. Every set used to be an edit of the same reference plate, which is why they looked alike.
- **Variety guard.**
  - It lists the look of the studio's five most recent sets from other episodes: each set's stored look, else the look words of its description, plus the look the old house style gave it.
  - It asks that, where the description does not fix them, the new set clearly differs in palette, floor material, light, time of day and layout.
  - When the description names no colour, it adds a palette for this episode, avoiding wall colours the recent sets use. The reference video's own colours win when the set notes name them.
  - The guard is editable and saved per episode (`PUT /api/episodes/{id}/set-proposal/variety`); empty goes back to the automatic one.
- **Generate this set.** The button shows the estimated image cost (about $0.05–0.20 per image) and asks you to confirm. The prompt shown is stored in the job and sent exactly as shown. The candidate keeps it ("The exact request sent to the image API", on its card) along with its look signature for later variety guards.
  - The candidate is linked to the episode and appears in the episode's Set section, where you approve or reject it; it is used only after you approve it. A set made for an episode is not kept for reuse until you say so; a set made in Settings › Sets (for no episode) is a library set and is kept.
  - A second request never overwrites a queued one; each gets its own ID.
- Nothing is generated or approved by itself.
- Data: `episodes.set_proposal` (migration `0009`) holds the rooms, each with its text, source and seats, plus the variety guard; the set notes are part of the episode's video notes.

## Seats and the table front

On the set's card in the episode's Set section (or in the Settings › Sets library) you mark the set's staging, on the picture, before or after approving it.

An **approved** set's staging can be edited later: **Edit staging (seats, table front, floor, standing area)**, then **Save staging** (`PUT /api/sets/{id}/staging`).
- The picture and the approval never change. Only the staging and its preview are redrawn.
- Every episode using the set (as its set or for scene changes) is re-checked: its seats against the most people its video notes seat at once. The result is shown under the set and logged on each episode. A rendered episode is told to render again to use the new staging.
- The same checks as at approval refuse a seat outside the picture, hips below the feet, or a table front that is not a box inside the picture.

- **Seats:** "Add a seat", then click where the seated feet rest. A set can have several seats. You can adjust each seat's hip height and feet height. A set that already has the older single `seat` keeps working.
- **Table front:** "Mark the table front", then click two corners. That part of the picture is drawn again after the seated characters, so they sit behind the table. Standing characters are drawn after it, in front.

How seats are used in a render:
- A scene can start with characters seated (`start: "seat:N"`). Its seated characters take the seats in the scene's staging order, speaker first.
- If there are more seated characters than seats, the extras stand, and the job log says so.
- A character told to sit on a taken seat goes to the nearest free seat. If no seat is free, they stay standing.

## A set per scene (a story that moves location)

- **The episode's sets.** On the Set card, tick "Also for scene changes" on other approved sets. Scenes can only use these sets and the episode's own set.
- **Who picks each scene's set:**
  - **The simple split** changes set only when the accepted video notes' setting changes and one of the episode's sets matches the new setting. Otherwise it keeps the previous scene's set.
  - **The AI writer** (audio and script-first) gets the list and the rule: keep the set unless the story clearly moves.
  - **You** can change a scene's set in the Storyboard tab while the storyboard is in review.
- **Unknown sets:** if the writer names a set that is not on the episode's list, the scene keeps the previous scene's set, and the event log says so.
- **Continuity:** a set changes only at a cut. Each cut starts its scene in that scene's staging on its own set's seats: the scene's characters on stage, the others off.
- **Missing sets block:** a scene whose set is no longer approved stops production with the scene named. There is no silent default.
- **Unchanged otherwise:** a render with one set and no staging is byte-identical to before. Long episodes render their segments the same way. Audio passthrough, lip sync and the audio QA are unchanged.
- Data: `episodes.scene_set_ids`, `storyboard_scenes.set_id` (migration `0011`).

## Two sides of one room (shot / reverse shot)

When the notes show one room from two sides, the Set card offers **"Generate both sides of the room"**.

- **What is generated:** two linked candidates with the same description plus one view line each ("View: the main side of the room…" / "View: the reverse side of the same room…"). Both exact prompts are shown, and the combined cost is confirmed first.
- **Approval:** each candidate is approved, and its seats and table front are marked, in the episode's Set section. The pair shows as "main side" / "reverse side".
- **In scenes:** add both to the episode's sets for scene changes. The simple split then cuts where the camera changes side, and each scene takes its side's set. On the reverse side the standing marks and seats are used in the opposite order, so who sits or stands where flips as it does in the video.
- **Single-view episodes:** with one view, or only one side's set, nothing switches and nothing flips. The render is identical to before.

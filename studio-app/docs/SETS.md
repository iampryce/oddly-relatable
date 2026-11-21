# Sets (backgrounds)

Every episode has its own set, chosen on purpose. There is no silent default.

## Choosing the episode's set

- The **Set** card on the episode (below the pipeline) shows the current set.
- **Choose an approved set** opens a picker with thumbnails. Each set shows the earlier episodes that already use it. Picking a set that is already in use asks for confirmation, so reuse is always deliberate.
- **Production cannot start without a set.** The message is: "choose this episode's set first (Storyboard tab, Set): there is no default set".
- A set that is withdrawn (rejected) after it was chosen also blocks production until another one is chosen.
- When the video notes name a setting, it is shown as a suggestion only. It is never applied by itself.
- Episodes that existed before this change keep the set they rendered with (migration `0008`).
- API: `GET /api/episodes/{id}/set-options` and `PUT /api/episodes/{id}/set` (the set must be approved; not while the episode is producing or publishing).

## A new set for the story

The **Proposed set for this story** box sits on the same card. The studio proposes an original set description, you edit it, and only your click generates a candidate.

- **Audio episodes: "Propose from the video notes" (free).**
  - A fixed sentence is built only from the notes' list values: the setting type, furniture, time of day, how many people are seated or standing, whether they face each other, and the mood.
  - Example: "An original dining room with a long table, evening, 3 people seated facing each other, 1 person standing; the mood is nervous."
  - Your edits to the notes apply.
- **Script-first episodes: "Propose from the story (AI writer)".**
  - One sentence from the title, logline and scene descriptions, written by the selected text provider.
  - Quotes and cast names are removed.
- **Edit and save.** Edit the text and save it. The box then shows the exact prompt that will be sent: the locked house style, then "Setting:" and your text.
- **Generate this set.** The button shows the estimated image cost (about $0.05–0.20 per image), asks you to confirm, and then sends exactly that prompt.
  - The candidate is linked to the episode, appears on the card and in Settings › Sets, and is used only after you approve it there.
  - A second request never overwrites a queued one; each gets its own ID.
- Nothing is generated or approved by itself.
- Data: `episodes.set_proposal` (migration `0009`, holding the text, its source and when it was saved).

## Seats and the table front

On the set approval screen (Settings › Sets) you mark the set's staging before approving it.

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
- **Approval:** each candidate is approved, and its seats and table front are marked, in Settings › Sets. The pair shows as "main side" / "reverse side".
- **In scenes:** add both to the episode's sets for scene changes. The simple split then cuts where the camera changes side, and each scene takes its side's set. On the reverse side the standing marks and seats are used in the opposite order, so who sits or stands where flips as it does in the video.
- **Single-view episodes:** with one view, or only one side's set, nothing switches and nothing flips. The render is identical to before.

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

# Audio-first episodes

A second way to make an episode, alongside the script-first pipeline. The owner uploads an audio file of the dialogue, and the studio builds the characters, script, scenes and video **around** that audio.

The uploaded audio is the voice track. No voice provider is used for these lines.

## Stage 1 (this change): upload, transcription, speakers, cast

1. **Create.** Go to Ideas → "New from audio".
   - Fill in the title and format (Short: audio up to 60 s; long: up to 7½ minutes).
   - Choose the audio file, and where it comes from: own recording, licensed, voice actor, or other.
   - Tick **"I have the right to use this audio"**.
   - The server refuses to create the episode without the checkbox and the source. Both are stored on the episode, and the confirmation is recorded as an append-only review (`gate: audio_rights`, with who confirmed and the stated source).
2. **Upload.**
   - The file is sent as the raw request body: `PUT /api/episodes/{id}/audio` with `Content-Type: audio/*`.
   - Accepted types are MP3, WAV, M4A/MP4 audio, AAC, OGG, WebM audio and FLAC, up to 60 MB.
   - The duration is checked with FFprobe against the format's limit.
   - Upload only: nothing in the studio downloads audio from links or other sites.
3. **Transcribe.**
   - The worker job `audio_transcribe` uses the transcription provider selected in Settings (OpenAI with word timestamps, or local Whisper).
   - The result is split into **timed lines**: a line ends at a pause (≥ 0.6 s), at the end of a sentence, or after 8 s / 24 words.
   - Without word timestamps, each transcription segment becomes one line.
4. **Label speakers.** In the episode page's **Lines and speakers** section:
   - Play each line and give it a speaker (any label, or an existing character's key).
   - Fix the text, split a line where the speaker changes (at a word boundary), or merge lines.
   - The server checks that the timing stays inside the audio, in order and without overlaps.
5. **Cast.** Each speaker label becomes a character. Either:
   - map it to an existing character, or
   - create a new episode character (name, key, personality, look, how they sound, bubble style). It has no art yet; its pose sheet is generated and approved in the usual way.

   "Suggest the cast (AI writer)" runs `audio_cast_suggest` with the selected text provider. It proposes speakers for the lines, a cast and voice styles. This is only a suggestion: nothing changes until the owner applies it.

Stages: `audio_upload` → `audio_transcribing` → `audio_labelling`. If transcription fails, the episode goes back to `audio_upload` with the error shown, and "Transcribe again" retries.

Data: `episodes.source` (`script` | `audio`), `audio_rights_confirmed`, `audio_rights_source`, `audio_asset_id`, and `audio_transcript` (JSON: provider, model, language, duration, `lines` with `id/start/end/text/speaker/words`, `cast`, `cast_suggestion`). These come from migration `0005`, which is additive: existing episodes get `source = script`.

## Video uploads (Stage 1b)

- A video file (MP4, MOV, WebM, MKV, up to 250 MB) is only a carrier for its sound. The worker extracts the first audio track and deletes the video; its picture is never stored, shown, or sent to an image generator.
- A Short longer than 60 s uses a 60 s window of the recording, chosen in the Lines and speakers section (or with the upload when video notes are asked for, below).

## Video reference notes ("reference, not copy")

Ticking **"Use the video as a reference for staging notes"** when uploading a video turns a few of its frames into **text-only** staging notes that the scene writer may use as inspiration.

- **Which frames (notes v2):** only from the part of the video the episode uses: the Short's 60 s window (so a Short longer than 60 s asks for its window with the upload), or the whole clip for a long episode. A Short: 1 frame per second (at most 60); a long episode: 1 frame every 2 s (at most 150), downscaled to 512 px wide and sent in batches of at most 50. Each later batch repeats the previous batch's last frame with its people listed in words, so everyone keeps their number; if the model renumbers them anyway, that overlap frame maps the numbers back.
- **Who reads them:** the studio's API vision provider (Settings → Video and visual analysis: OpenAI or Anthropic with the studio's key). Never a Codex login: without an API vision provider the upload with notes is refused with a clear message. The form shows the number of frames, calls and the estimated cost, with the per-episode cap (Settings › Video and visual analysis, default $0.50), before anything is sent; an upload whose notes would cost more than the cap is refused; the actual token use is recorded with the notes.
- **What is kept:** per frame, only: shot, camera movement, setting type, furniture, time of day, and numbered people (`person 1`..`person 6`, the same number for the same person in every frame) with position, pose, whom they face, a gesture, an emotion word and whether they seem to be talking. Every field is a fixed list. Anything else in the model's answer (names of people, actors or characters, faces, appearance, clothing, brands, logos, on-screen text, dialogue, free text) is removed and counted. The per-person frames stay on the server (for the cast mapping); the editable ranges are made from them (the speaker is the one person talking), as before. The notes' times are the audio's, so each range shows the recorded lines it covers; moving the Short's window moves the notes, and notes outside the new window are dropped.
- **Notes quality:** the Video notes section shows the people found, how often each person number appears, the frames used and sent, the calls, the actual cost (from the tokens reported) and the items stripped, to judge the identity tracking before relying on it.
- **What is deleted:** the frames, right after the notes are made (whatever happens), and the video, right after its audio is extracted. Nothing visual is stored or backed up (`work/uploads` is temporary and left out of backups).
- **"Inspired by video notes"** (the Video notes section): read the notes, change a range's shot, camera or setting, remove a range, or clear them all, before the scenes are built.
- **How the scenes use them:** as strong suggestions (dialogue and timing stay locked). The AI writer gets each line's note (shot, who reacts, positions) and is told never to change the dialogue; the simple split takes the note's shot and adds reaction cutaways of the silent characters for its reactors. The dialogue is copied from the transcript in both cases, and the characters and sets stay the studio's own.
- **Every field is editable** (shot, camera, setting, furniture, time of day, and each role's position, pose, facing and emotion). The first edit keeps the vision model's unedited notes, so the plan can show both values.
- **Reference plan (accept before building).** The Reference plan section lists, per time range, what the notes will drive:
  - **Set:** the set proposal.
  - **Seating:** who is seated or standing and whom they face. The first scene starts that way, speaker first.
    - **Scene continuity:** a cut to a close-up is the camera, not people leaving.
    - Every later scene starts with the same people on the same seats as the scene before. Its own notes only update the people they show, for example someone now standing.
    - Someone leaves only when the accepted plan has an exit beat for them between the two scenes, and comes back with an enter beat.
    - The first scene also stages everyone the notes show within its span, so a first line in close-up doesn't leave the others out.
    - Everyone staged is in the storyboard scene (seated, never off stage).
  - **Shot:** a strong suggestion to the scene writer.
  - **Reactors:** silent reaction cutaways.

  Each item shows the value it will use, the unedited value when you changed it ("was"), a used/ignored toggle, and a note on anything the renderer cannot do yet (camera moves, lying down, more seated people than seats). The scenes cannot be built until you accept the plan, and editing the notes or a toggle withdraws the acceptance. Roles are mapped to the cast: "speaker" is the range's first speaker; "reactor N" is the N-th other character (silent characters first). Only fixed-list values are ever used.
- **Existing episodes** have no notes: re-upload the video with the box ticked to get them.

## Scenes and production (Stages 2 and 3)

**Rebuild scenes from audio.** This builds the scenes again after the script was approved, for example so a later fix to how scenes start applies. It is in the Script section at "script approved", "storyboard review" and "storyboard approved" only.
- **Before anything changes**, the confirmation lists what is discarded, what is kept, and the AI writer's estimated cost. The simple split is free.
- **Discarded:** the storyboard scenes, which unlinks their stills (the images stay in storage); the approvals of the current script and storyboard (withdrawn, as a script revision request does); and per-scene edits on the storyboard.
- **Reaction beats and shot lists:** when the storyboard has any (Storyboard › Reactions, Shots), the confirmation names how many, and a second confirmation asks to discard them; they cannot be restored. The API refuses the rebuild (409, nothing changed) unless `"discard_reactions": true` is sent as well.
- **Kept:** every script version (the current one stays in the history), poses and sets with their approvals, the episode's chosen set, the Reference plan and its acceptance, and the recording, transcript, speakers and cast.
- **Afterwards**, the episode is back at script review with the new scenes. You approve the script, then generate the storyboard and refresh the stills as usual. Nothing is approved for you.
- **API:** `GET /api/episodes/{id}/audio/rebuild-scenes` for the preview; `POST` with `{"mode": "writer"|"simple", "confirm": true}` to rebuild. Without `confirm`, the POST returns the preview only.

**Hook banner.** Each episode has its own "Hook banner" switch next to "Dialogue on screen".
- **When on**, the banner shows the episode's own text, or the script's hook when the text is empty.
- **When off**, no banner in the stills or the video, from either renderer.
- **Defaults:** audio episodes start with it off. Script-first episodes start with it on.
- **Existing episodes** (migration `0014`): on for script-first episodes and for audio episodes already rendered; off for audio episodes not rendered yet.
- **API:** `PUT /api/episodes/{id}/hook {"enabled": true|false, "text": "..."}`.

**Character size and seated poses.**
- **Size:** the cast is drawn 530 px tall (in the set picture's pixels) unless the set's seats are close together. Then everyone is drawn smaller, at the largest height where seated neighbours' heads overlap by at most a quarter. The Reference plan's Seating note says so.
- **Seated limbs:** legs hang almost straight below the seat, with each knee towards its own side and the feet apart like the character's hips. Hands rest on the thighs.
- **Eyes:** the rig's face finder takes the eyes to be the pair of white shapes most alike in size and height, each at most 40% of the head's width. White hair or a white hat is never taken for an eye. Rigs are rebuilt automatically with the next render after a change to the extractor.

**Storyboard stills.** With the studio rig animator as the motion provider (every audio episode), "Refresh stills" renders the scene with the acting renderer, which also makes the video.
- **What they show:** the episode's own set and its seats, and the episode's dialogue display (no bubble when "Dialogue on screen" is None).
- **The sheet:** up to six frames, the first just after the scene's first line starts and the rest spread over its lines.
- **How they are made:** the frames are drawn in order exactly as for the video, up to the last still. No video is encoded and no audio is needed (a line whose recording slice does not exist yet keeps a closed mouth). It runs on the CPU; nothing is paid.
- **Script-first episodes on the old pose engine** keep the pose engine's stills.

- **Stage 2:** the scenes are runs of consecutive recorded lines (a cut only between two lines); the writer adds staging and acting, the dialogue is locked, and the result goes through the usual script and storyboard approvals.
- **Stage 3:** each line plays at its recorded time; lip sync comes from the recording, cut per line; the original audio goes into the video unchanged; the render must pass the audio QA (video length equals audio length; first mouth cue within 80 ms of the first word).

## People, views and action beats (from the video)

- **One room, two views.** The notes record which side of the room the camera looks at (`view`: main side, reverse side, side-on, overhead, wide). One room filmed from two angles (shot / reverse shot) stays one setting with two views. Short setting flips (under 20 s) are smoothed to the room's setting; the unsmoothed value is shown in the Reference plan as "was". A real move of 20 s or more is kept.
- **People in the video.** The numbered people are mapped to characters by you, in the People / who is who section. The studio suggests a person only when the vision "talking" flag singles one person out often enough; it is never applied by itself.
  - Once you confirm who is who, the speaker of each moment comes from the recorded lines (audio timing), in preference to the talking flag.
  - The ranges and beats are then rebuilt. If you have edited the ranges, use "Rebuild from the video frames" instead, which asks first.
- **Action beats.** These are derived on the server from the per-person frames:
  - movement: enters, exits, sits down, stands up, walks (left/center/right);
  - body and head: leans in or back, turns to someone or away, nods, shakes the head;
  - hands: phone to ear, and other gestures held for at least a second.

  How they behave:
  - A camera cut to the other side is never read as a walk.
  - Lying down and kneeling are listed and **will be skipped**, like hugs, running and camera moves.
  - Every beat can be removed or changed; the derived beats stay as "was".
  - Beats are acted only for confirmed people, at their time on the timeline. Dialogue and timing never change.
- **Reference plan:** two more items per range. **View** shows the side and what a cut to the other side does. **Movement** lists the beats in the range. Both have used/ignored toggles, and ignoring Movement leaves that range's beats out.
- **Costs:** the OpenAI estimate is calibrated ×1.7 from a real run. Anthropic is not yet calibrated: the notes readout shows "actual ÷ estimate" to set it. When nearly all emotions come back neutral, the readout suggests trying the Anthropic vision provider.

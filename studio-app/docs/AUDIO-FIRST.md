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
4. **Label speakers.** In the episode's **Audio** tab:
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
- A Short longer than 60 s uses a 60 s window of the recording, chosen in the Audio tab (or with the upload when video notes are asked for, below).

## Video reference notes ("reference, not copy")

Ticking **"Use the video as a reference for staging notes"** when uploading a video turns a few of its frames into **text-only** staging notes that the scene writer may use as inspiration.

- **Which frames:** only from the part of the video the episode uses: the Short's 60 s window (so a Short longer than 60 s asks for its window with the upload), or the whole clip for a long episode. One frame about every 4.5 s, at most 24, downscaled to 512 px wide.
- **Who reads them:** the studio's API vision provider (Settings → Video and visual analysis: OpenAI or Anthropic with the studio's key). Never a Codex login: without an API vision provider the upload with notes is refused with a clear message. The form shows the number of frames and an estimated cost before anything is sent; the actual token use is recorded with the notes.
- **What is kept:** per time range, only: shot (wide, medium, close), camera movement, setting type, and anonymous roles (`speaker`, `reactor 1`..`reactor 9`) with position, pose, who they face, and an emotion word. Every field is a fixed list. Anything else in the model's answer (names of people, actors or characters, faces, appearance, clothing, brands, logos, on-screen text, dialogue, free text) is removed and counted (`redacted`). The notes' times are the audio's, so each range shows the recorded lines it covers; moving the Short's window moves the notes, and notes outside the new window are dropped.
- **What is deleted:** the frames, right after the notes are made (whatever happens), and the video, right after its audio is extracted. Nothing visual is stored or backed up (`work/uploads` is temporary and left out of backups).
- **"Inspired by video notes"** in the Audio tab: read the notes, change a range's shot, camera or setting, remove a range, or clear them all, before the scenes are built.
- **How the scenes use them:** as soft suggestions only. The AI writer gets each line's note (shot, who reacts, positions) and is told never to change the dialogue; the simple split takes the note's shot and adds reaction cutaways of the silent characters for its reactors. The dialogue is copied from the transcript in both cases, and the characters and sets stay the studio's own.
- **Existing episodes** have no notes: re-upload the video with the box ticked to get them.

## Scenes and production (Stages 2 and 3)

- **Stage 2:** the scenes are runs of consecutive recorded lines (a cut only between two lines); the writer adds staging and acting, the dialogue is locked, and the result goes through the usual script and storyboard approvals.
- **Stage 3:** each line plays at its recorded time; lip sync comes from the recording, cut per line; the original audio goes into the video unchanged; the render must pass the audio QA (video length equals audio length; first mouth cue within 80 ms of the first word).

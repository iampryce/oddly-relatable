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

## Later stages (separate changes, each approved by the owner first)

- **Stage 2:** the writer builds scenes, expressions and camera around the timed, labelled lines. The words and timing are fixed; the writer adds staging and acting.
- **Stage 3:** production plays the uploaded audio's line clips in place of generated voices. Rhubarb lip sync and the existing approval gates stay as they are.

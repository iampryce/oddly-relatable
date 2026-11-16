# Characters and voices: how they work, credentials and running costs

## 1. Story-driven characters (no fixed cast)

1. **The script decides the cast.** The writer reuses saved characters when they fit. Otherwise it introduces the characters the story needs in `new_characters`, each with a name, a visual description, a bubble style and a voice style. The owner can also add or edit them in the script editor.
2. **New characters are registered automatically** for that episode, with no art. They show under Characters → "Introduced by stories" and in the episode's **Cast** panel. The panel lists every character the script needs, its art status, and the expressions the script uses that still lack a pose.
3. **Pose and expression sheet (owner-started).** "Generate missing pose sheets" in the Cast panel, or "Generate sheet" on a character, queues one `character_sheet` job per character:
   - The **neutral** pose is drawn first. Every other expression is drawn with it as the reference image, for consistency. An owner-uploaded reference image anchors the neutral pose when present.
   - A flat background is cut out automatically. Then the feet anchor and figure height are measured, so all poses stand at the same scale. Images that are not clean cut-outs are refused, not used.
   - A labelled sheet image is produced for review. A retry continues where a failure stopped, and finished poses are not regenerated.
4. **Owner approval:**
   - The owner can approve or reject the whole sheet, or single poses.
   - Only approved poses are ever used. Production refuses to start while a character on screen has no approved poses.
   - An expression without its own pose falls back to the closest approved one: the default expression, usually neutral.
5. **Reuse.** "Add to recurring cast" keeps an approved story character for every future story. Recurring characters and any character with approved art are offered to the writer. Character 01 keeps its locked, approved repository artwork and is never regenerated; only its voice can be set.

## 2. Voice production

- **Assignment.** Each character has a **voice**, which is the provider's voice id, and a **voice style** describing how they sound. A **voice preview** button produces a short sample to listen to before production.
- **Dialogue generation.** `scene_voice` jobs voice every line of a scene. Each line gets acting direction built from three things: the character's voice style, the line's expression, and its optional `delivery` note, such as "whispered" or "panicked". OpenAI's `gpt-4o-mini-tts` follows this direction; ElevenLabs takes the voice id and expressive settings.
- **Synchronisation:**
  1. Each line stays on screen until its clip has finished, plus a 0.4 s comedic beat. The length is rounded up, so a clip is never cut.
  2. The engine computes each line's exact start time with its own timing code (`node/line-timings.mjs`).
  3. Each clip is placed at that start in the audio bed. The engine mixes it with a limiter (no clipping), and the renderer's sound effects go on top.
  4. QA checks the final audio.
  5. A clip recorded for different text is refused, so edited dialogue is always re-voiced.

  The tests verify the placement against the engine's timings.
- **No provider configured:** the voice step reports "skipped" and the video carries sound effects only. Nothing is faked.

## 3. Credentials

| Capability | Provider setting | Server environment | Notes |
|---|---|---|---|
| Voices | `openai` | `OPENAI_API_KEY` | Voices such as `alloy`, `onyx`, `nova`, `shimmer`; supports acting direction |
| Voices | `elevenlabs` | `ELEVENLABS_API_KEY` | Character voice = ElevenLabs voice id (from their voice library) |
| Voices | `piper` | none (`PIPER_BIN`) | Free and local. Install the `piper` binary and `.onnx` voice models on the worker; voice = model path |
| Character art | `openai` | `OPENAI_API_KEY` | Images API, transparent PNG |
| Character art | `codex-cli` | none | ChatGPT subscription; only on a machine where Codex is signed in (see DEPLOYMENT.md §7) |
| Scripts | `openai` / `anthropic` / `codex-cli` | `OPENAI_API_KEY` / `ANTHROPIC_API_KEY` / none | |

Keys live only in `/srv/stickman/shared/.env`. The dashboard shows whether each is configured, never its value.

## 4. Estimated running costs

These are estimates checked on 2026-11-16 from public pricing pages and secondary sources. Provider prices change, so verify on the provider's own page before relying on them.

| Item | Basis | Per 45 s Short | Per 6 min episode |
|---|---|---|---|
| OpenAI `gpt-4o-mini-tts` voices | $0.60 / 1M text tokens + $12 / 1M audio tokens, about $0.015 per minute of speech ([OpenAI model page](https://developers.openai.com/api/docs/models/gpt-4o-mini-tts)) | about $0.01 | about $0.09 |
| ElevenLabs voices (API) | Reported about $0.05–$0.10 per 1,000 characters for Flash/Turbo and Multilingual models; secondary sources disagree, up to $0.30 ([ModelsLab summary](https://modelslab.com/elevenlabs-api-pricing.md)). Subscriptions: Creator $22/month about 100k characters ([summary](https://dev.to/techsifted/elevenlabs-pricing-2026-plans-credits-and-api-costs-explained-1549)) | about $0.05 (about 600 characters) | $0.25–$1.50 (about 5,000 characters) |
| Piper voices | Local CPU | $0 | $0 |
| Script writing (OpenAI/Anthropic API) | A few thousand tokens per script | cents | about $0.05–$0.30 (outline plus scenes) |
| Character sheet | One image per expression, about 6–8 per new character; one-off, then reused | per new character only | per new character only |
| Server, Postgres, Redis, local storage | Existing VPS | $0 extra | $0 extra |

**Monthly example:** 30 Shorts and 4 long episodes with OpenAI voices and an API writer comes to about $2–$5. With ElevenLabs Creator it is $22 plus a few dollars. New character art adds per image. All of these stay well within the $150/month target.

# Rivet AI Studio — style guide and build plan (draft, 2026-11-27)

Built from the owner's research: Mark Ai Guy "Rick's Clips" stickman shorts, the "KnowSense" stickman explainers tutorial,
and the finance stickman tutorial; plus the owner's cartoon-short-kit and our Episode 15 lessons.

## 0. The four categories (owner, 2026-11-27)
1. **Narrated stick-man shorts**; 2. **Real cinematic movies** (original kingdom/power sagas); 3. **Cartoon-short-kit** (Episode 15-style sketches);
4. **Bible stories** (public-domain text only). Categories 2 and 4 share a pipeline; 4 adds a source-text check.
**Decision: build the easy path first**: Gemini TTS + code kit (free), one 30 s short end to end. Wan 2.2 and Omni Flash come after.
Registry: `studio-app/api/oddstudio/categories.py`.

## 1. Our formats
| Format | What it is | Status |
|---|---|---|
| **Narrated stick-man shorts** (main) | One narrator, 1-2 recurring stick-man characters acting out each sentence. Niches: "what if" stories, money, psychology/self-improvement, history, weird facts. 30-60 s vertical (9:16); long-form 16:9 later. | To build ("New short" wizard) |
| **Cinematic films** (parallel) | Realistic invented actors, real acting and dialogue: Bible-based human stories (public-domain text only) and original kingdom/power-struggle sagas. | Being built (cinematic mode) |
| **Cartoon sketches** (Episode 15 type) | Multi-character acted sketches from a reference. | Paused; code-puppet proof in progress |

## 2. Story template (narrated shorts)
1. **Hook** (first line, no setup): a paradox, question or surprising fact. "What if every lie made you smaller?"
2. **Setup** in 1-2 lines: who, where, one concrete detail.
3. **Escalation**, 2-4 beats, each bigger (numbers grow, the character shrinks, the town vanishes).
4. **Pivot**: "But..." / "Here's the thing..."
5. **Payoff / twist**: short, ironic or a one-line lesson, the last words of the video.
- About 3.7 spoken words per second (30 s is about 110 words). Plain spoken English.
- **One scene per sentence**, 3-6 s each (a 30 s short is about 8 scenes).
- Original stories only. Facts are checked before they are presented as true; legends are labelled "legend says".

## 3. Look
- **House characters**: 2-3 recurring stick men from the cast library (approved masters, never changing). The viewer should recognise them across videos.
- **Backgrounds**: clean 3D-style worlds (rooms, streets, towns), bright readable colours.
- **Captions**: bold, high-contrast, in the upper-middle of the frame, a few words at a time.
- **Thumbnail**: the character plus the one visual idea (a tiny man and a giant mug), 3-5 words maximum.

## 4. Sound
- **Narration**: Gemini TTS (free on our key; tested with the "Charon" voice) with a style instruction ("warm, calm narrator", "dramatic"), or the owner's own voice. Not ElevenLabs' free plan (not licensed for commercial use).
- **Music bed** at half the voice level (-6 dB), **SFX** on beats (the kit's mix rules).

## 5. Motion engines (owner picks per video)
| Engine | Cost | Strength | Limit |
|---|---|---|---|
| **Code kit** (cartoon-short-kit on the studio server) | Free | Characters never change; exact timing to the voice | Scene code per video (written by the AI model); renders on CPU (minutes to hours) |
| **Wan 2.2 image-to-video** on rented GPU | about $0.05 per clip + session start | Already built | Open model; can drift on long moves |
| **Omni Flash** (Google) | Needs Google billing (price to confirm); or Flow's free daily credits used by hand | Most natural acting, native sound | Credit-limited |

## 6. Rules
- No real people's likeness; invented characters only.
- YouTube: avoid repetitive mass-produced content; vary stories. Tick "altered or synthetic content" for realistic AI people (cinematic).
- Licences checked for every tool (commercial use).
- Cost shown and approved before any paid step (studio rule).

## 7. Build plan: the "New short" wizard in the dashboard
1. Choose **niche**, **character** (cast library), **format** (9:16 / 16:9 / 1:1), **length** (30 s to 10 min).
2. **10 ideas** (GPT) or the owner's own idea, then the **script** (story template above), owner approves.
3. **Scenes**: one per sentence, with picture prompts using the approved characters as references; owner approves the pictures.
4. **Motion**: pick the engine (code kit / Wan / Omni Flash); cost shown first.
5. **Voice**: Gemini TTS (free) or upload; owner listens and approves.
6. **Timing**: every scene is fitted to the narration's word timings (no speeding clips up by hand).
7. **Music, SFX, captions** (style presets).
8. **Thumbnail, 5 titles, description, hashtags**.
9. **Final review**, then publish.
Reuses: cast library, prompt writer, stills, GPU sessions, assembly, autopilot and the chat under each item. New: the TTS step, scene-per-sentence timing, caption styles, the thumbnail/title step, the engine selector including the code-kit renderer on the server.

## 8. First tests
- **One 30 s short end to end** on the free path: Gemini TTS + code kit (free).
- The same script on Wan 2.2 (about $0.50 with a small Runpod top-up), to compare engines.
- Omni Flash later, when Google billing is on.

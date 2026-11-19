# AI handoff: Fish Audio voice provider (branch `feat/fish-audio-voice`)

Date: 2026-11-19. For the owner (final approver) and the lead engineer reviewing this work.
Nothing was deployed, restarted or migrated on the server. Every server command in this session was read-only, apart from `pg_dump`, which is also read-only.

## 1. Phase A findings (production server)

| Item | Finding |
|---|---|
| Server | `ssh studio` (root, key only). Docker Compose project `oddstudio`, with six containers: proxy (Caddy 2.10), web, api, worker, postgres 16, redis 7 |
| Source on the server | `/srv/stickman/releases/<tree sha>/` holds a read-only `git archive` of `bible/ production/ skills/ studio-app/`. `/srv/stickman/current` points to `releases/cf43210764335a4dd4a6b2332384f654b7ea49ca` |
| Source of truth | `iampryce/oddly-relatable` `main` at `34cb68a`, whose `HEAD^{tree}` is `cf43210…`. I checked this independently: all 795 files in the live release match the checkout by SHA-256, and the running api image matches the release (except 8 `.mp4` files that the dockerignore excludes) |
| Stack | API and worker share one image (`studio-app/api/Dockerfile`, Node 22 base): Python FastAPI, SQLAlchemy and Alembic, Redis queue (`oddstudio.worker`). The image also contains the Node render engine (`production/`, `skills/directing-stickman-videos/`), ffmpeg, Piper 1.8 with 5 voices, kokoro-onnx, faster-whisper, Rhubarb 1.14 and Codex CLI. The web app is Next.js 16 with React 19 |
| Deploy method | `studio-app/deploy/deploy.sh <sha>` runs backup, then build, then switches `current`, then `up -d`, then a health check (`127.0.0.1:3000/api/health`), and rolls back automatically on failure. `rollback.sh` and `backup.sh` (nightly, keeps 14) sit beside it. The API runs `alembic upgrade head` every time it starts |
| Secrets | `/srv/stickman/shared/.env` and `admin-credentials.txt` (mode 600). The variable names are listed in `studio-app/deploy/.env.example` |
| Credentials mechanism | `studio-app/api/oddstudio/secrets_store.py` stores keys Fernet-encrypted in the `settings` table, in the row keyed `_secrets`. The encryption key is derived from `SESSION_SECRET` in `shared/.env`; there is no separate key file. `secret(name)` uses the value saved in Settings first and the env var from the `SECRETS` map second, with a 5-second cache. The API reports only whether a key is set and where from |
| Voice providers | Registry in `capabilities.py`. Allowed choices in `settings_store.VOICE_PROVIDERS`. Generation in `providers.speak()` / `_speak_one()` (primary, then fallback with that provider's default voice). A character's voice is stored in `characters.voice` as `<engine>:<id>`, which pins that engine. The worker test is `tasks_providers.provider_test` (target `voice:<provider>`), which stores the clip and reports `seconds` |
| Caching | No TTS clip cache existed. Rhubarb cues are cached by clip SHA-256 (`acting.py`) |
| Rhubarb and render | `analysis.lipsync()` converts any non-WAV input to WAV. Clips are placed at the engine's line timings in the audio bed (`tasks._voice_audio`, `tasks_long.place_voices`) |
| Use of the old repo's contents | The server uses `production/` (CLI, lib, animation, registries), `skills/directing-stickman-videos/` (renderer and fonts) and `bible/concepts/lookdev-richenv/` (art). All of it is inside the release and in `main`. All 13 asset paths referenced by the registries exist. Nothing used is missing |

## 2. Backups taken (B2, private, not in git)

`~/Backups/oddstudio/2026-11-19/` on the owner's Mac (folder 700, files 600):

| File | Size | Notes |
|---|---|---|
| `db.sql.gz` | 94 KB | 15 tables; dump complete |
| `shared.env` | 967 B | Checksum matches the server. Includes `SESSION_SECRET`, from which the credential encryption key is derived |
| `admin-credentials.txt` | 120 B | Checksum matches the server |

The media volume `oddstudio_work_data` is 1.3 GB and was not copied, pending the owner's decision. It contains `work` 545 MB, `models` 479 MB, `migrate` 241 MB and `codex` 38 MB. `codex/` holds the Codex CLI login, so treat it as a secret.

## 3. What was committed and pushed

- Repo: `https://github.com/iampryce/oddly-relatable.git`
- Branch: `feat/fish-audio-voice`, branched from `main` at `34cb68a`. Not merged and not deployed.
- Commits:
  - `02fd803`: feat(voice): add Fish Audio as a voice provider
  - The commit that adds this handoff file. See `git log` on the branch.

## 4. Fish Audio changes

The API was checked against docs.fish.audio on 2026-11-19:
- TTS: `POST https://api.fish.audio/v1/tts` with headers `Authorization: Bearer`, `Content-Type: application/json` and `model`. Valid models include `s2-pro` and `s2.1-pro-free`. The response is the raw audio stream. `prosody.speed` must be between 0.5 and 2.0.
- Credit check: `GET https://api.fish.audio/wallet/self/api-credit`, which returns `credit`.

| File | Change |
|---|---|
| `studio-app/api/oddstudio/providers.py` | Adds `fish_speak()`. The body sends `text`, `reference_id`, `format: wav`, `sample_rate: 44100`, `latency: normal` and `prosody.speed`. The model is the voice Model setting or `s2-pro`. 429, 5xx and network errors are retried at most twice (backoff 1 s, then 3 s). 401 gives a "key rejected" message and 402 gives a "no API credit" message. The key is redacted from every error. A WAV that isn't 16-bit PCM is converted with ffmpeg so Rhubarb takes it like Piper or Kokoro output. Clips are cached in `<work dir>/voice-cache/fish/<sha256>.wav`, keyed by model, voice, speed, sample rate and text; only complete WAVs are cached. Also adds `fish_credit()`, `fish` in the `speak()` voice prefix, and `speed=` passed through to Fish |
| `secrets_store.py` | `fish_api_key`, with `FISH_API_KEY` as the env fallback |
| `settings_store.py` | `fish` in `VOICE_PROVIDERS`, `voice.fish_default_voice` (used when Fish is the fallback), and `fish_api_key` in `integrations_status` |
| `capabilities.py` | Voice provider `fish` labelled "Fish Audio", with `default_model` set to `s2-pro` |
| `tasks_providers.py` | `voice:fish` test. It runs the free credit check first, then voices one line with the first character whose voice is `fish:…` (and that character's speed), falling back to the Fish default voice. It bypasses the cache read so the line is really synthesised, and reports `seconds`, `voice`, `model`, `credit` and `character` |
| `models.py`, `migrations/versions/0004_character_voice_speed.py` | Nullable `characters.voice_speed` (Float). Additive only |
| `routes_characters.py`, `serialize.py`, `tasks.py` | `voice_speed` in the API (0.5 to 2.0, or empty). Voice previews and scene voicing pass it through |
| `deploy/docker-compose.yml`, `deploy/.env.example` | `FISH_API_KEY` passed through to the containers (optional) |
| `web/app/(studio)/settings/page.tsx` | "Fish Audio API key" credential and a "Fish Audio default voice" field |
| `web/app/(studio)/characters/page.tsx` | Voice hint `fish:<Fish voice id>` and a "Voice speed" field |
| `docs/VOICE-AND-CASTING.md` | Fish row in the credentials table |
| `api/tests/test_fish_voice.py` | 16 tests with mocked HTTP (no network calls). They cover the request shape and default model, the Model override, the `fish:` prefix, a missing key, the env fallback (and that a key saved in Settings wins), key redaction, 401/402, retries (429 then 503 then 200, all-500, network error), non-audio answers, the non-PCM WAV refusal, cache hit and miss per field, failures not being cached, settings and speed validation, character speed in a voice preview, Fish as the fallback, and the worker provider test (credit check first, cache bypass, model) |

### Test results (local Mac, Python 3.12.16, `cd studio-app/api/tests && python -m unittest`)

- Baseline on `main` before the change: 28 ran, OK, 4 skipped.
- On the branch: **44 ran, OK, 4 skipped** (all 16 Fish tests pass).
- Alembic on a scratch SQLite database: `upgrade head`, then `downgrade -1`, then `upgrade head`. `voice_speed` is added, dropped and re-added, and `0004` is the single head.
- Web: `npx tsc --noEmit` OK, and `next build` OK.

### NOT RUN

- The **4 skipped renderer end-to-end tests** (`test_end_to_end.test_sample_episode`, `test_long_form.JoinTest.test_join_checks`, plus one test each in `test_cast_and_voice` and `test_long_form`). They need FFMPEG/FFPROBE, which isn't installed on this Mac, and downloading a static ffmpeg was blocked by a permission check. They cover `scene_voice`, which now passes `speed=`. Run them in the API image (see below).
- **Real Fish API call**: no Fish key has been saved yet. The brief allows one connection test, after the owner saves the key.
- Alembic against **PostgreSQL** (only SQLite was tested). The migration is a single nullable `add_column`.
- Tests on Linux / in the Docker image.

Command to run the full suite in the image after building it:

```
docker run --rm -e ODD_ENV=test oddstudio-api:<tag> sh -c "cd /app/studio-app/api/tests && python -m unittest"
```

## 5. Deploy plan: the server folder becomes a git checkout

The owner runs these steps after saying "deploy". All of them run on the server as root unless stated otherwise.

### 5.1 One-time setup: read-only deploy key and checkout

```
ssh-keygen -t ed25519 -N "" -C "oddstudio-server-deploy" -f /root/.ssh/oddstudio_deploy
cat /root/.ssh/oddstudio_deploy.pub
```

1. In GitHub, go to iampryce/oddly-relatable, then Settings, Deploy keys, Add deploy key. Paste the public key and leave "Allow write access" unchecked.
2. Add an SSH alias and clone:

```
cat >> /root/.ssh/config <<'CFG'
Host github-oddstudio
  HostName github.com
  User git
  IdentityFile /root/.ssh/oddstudio_deploy
  IdentitiesOnly yes
CFG
ssh -T github-oddstudio            # expect: "Hi iampryce/oddly-relatable! You've successfully authenticated..."
git clone git@github-oddstudio:iampryce/oddly-relatable.git /srv/stickman/repo
cd /srv/stickman/repo && git checkout main
```

### 5.2 Check that the checkout matches what is running, before switching anything

```
cd /srv/stickman/repo
git status --porcelain                                   # expect: no output
git rev-parse HEAD^{tree}                                # expect: the same as the next line
basename "$(readlink -f /srv/stickman/current)"          # cf43210764335a4dd4a6b2332384f654b7ea49ca
(cd /srv/stickman/current && find . -type f -print0 | xargs -0 sha256sum) | sha256sum -c --quiet && echo "release == checkout"
docker inspect oddstudio-api-1 --format '{{.Config.Image}}'   # oddstudio-api:cf43210764335a4dd4a6b2332384f654b7ea49ca
```

Do not continue unless all of these hold. The last `sha256sum -c` runs from the checkout and must print only `release == checkout`.

### 5.3 Deploy the Fish branch

1. The owner reviews the branch and merges it into `main` on GitHub. This session does not merge it.
2. On the server:

```
cd /srv/stickman/repo
git pull --ff-only
git status --porcelain                                   # expect: no output
/srv/stickman/current/studio-app/deploy/backup.sh        # DB dump + media before the change
REL=$(git rev-parse HEAD^{tree})
C=(docker compose -p oddstudio --env-file /srv/stickman/shared/.env -f studio-app/deploy/docker-compose.yml -f studio-app/deploy/docker-compose.public.yml)
RELEASE=$REL "${C[@]}" up -d --build --remove-orphans
for i in $(seq 1 30); do curl -fsS http://127.0.0.1:3000/api/health && break; sleep 5; done
docker logs oddstudio-api-1 2>&1 | grep -i "alembic\|0004" | tail -3      # expect: "Running upgrade 0003 -> 0004"
ln -sfn repo /srv/stickman/current                       # backup.sh / rollback paths now read the checkout
```

3. Notes on this step:
   - The migration (`0004`, a nullable column) runs automatically when the API starts.
   - postgres and redis are not recreated, because their configuration is unchanged and their volumes keep the same names.
   - `FISH_API_KEY` in `shared/.env` is optional. A key saved in Settings works without any restart.

From now on, every deploy is the same `git pull --ff-only` followed by `up -d --build`, with the release tag set to the tree hash. No files are edited on the server directly.

### 5.4 After the deploy: the single paid Fish test

1. Settings → Credentials: save the "Fish Audio API key".
2. Characters: set one character's voice to `fish:<Fish voice id>` and, optionally, a speed.
3. Settings → Voice generation → Fish Audio → Test. This runs the free credit check, then one line, then shows its length.
4. `s2-pro` needs paid credit. On the free tier, select Fish and set Model to `s2.1-pro-free` before testing.

### 5.5 Rollback

The previous images are still on the host, tagged `cf43210…`.

```
cd /srv/stickman/repo && git checkout 34cb68a
C=(docker compose -p oddstudio --env-file /srv/stickman/shared/.env -f studio-app/deploy/docker-compose.yml -f studio-app/deploy/docker-compose.public.yml)
RELEASE=cf43210764335a4dd4a6b2332384f654b7ea49ca "${C[@]}" up -d --remove-orphans     # no --build: reuses the old images
ln -sfn releases/cf43210764335a4dd4a6b2332384f654b7ea49ca /srv/stickman/current
git checkout main                                         # after fixing forward
```

No database restore is needed. Migration `0004` only adds a nullable column, which the old code ignores. If the column must be removed anyway, run `docker exec oddstudio-api-1 alembic downgrade 0003` before switching images back.

`studio-app/deploy/rollback.sh <tree sha>` still works for the releases under `/srv/stickman/releases/`.

## 6. Open risks and questions

1. **Emotion tags in dialogue text.** Fish reads `[whisper]` and similar tags inline, but the same line text is shown in speech bubbles and captions. It is also passed to Rhubarb as a guide and spoken literally by other providers. Until tags are stripped for display, don't put tags in dialogue. A small follow-up would fix this.
2. **Default model.** The brief asked for `s2-pro`, but Fish's docs now name `s2.1-pro` as the API's own default, and `s2-pro` needs paid credit.
3. **Retries add up.** A Fish failure after 2 retries is marked transient, so the job queue may retry the whole job (up to `max_job_attempts`). 429 and 5xx answers are presumably not billed.
4. **Fish's WAV encoding is unverified** without a real call. The code converts non-16-bit WAV with ffmpeg, which is present in the image.
5. **The clip cache has no size limit.** It lives in the `work_data` volume (about 90 KB per second of speech) and goes into `backup.sh`'s media tarball.
6. **Model field bug in the existing test.** The provider test for the other voice providers sends the Model field even when that field belongs to a different selected provider. This bug predates this branch and is not changed here; Fish avoids it.
7. **A competing branch exists.** `feat/fish-voice` (2 commits, another session, 2026-11-19) adds Fish to the old Node `studio/`, not to `studio-app`. Recommend closing or deleting it so there is one Fish implementation.
8. **Server disk is 70% full**, with 11 GB of local backups.
9. **Media backup is still open.** The owner needs to decide whether to copy `work_data` (1.3 GB) off the server.

# Registry promotion: design (AP-84B2, documentation only)

**Status:** design only. Nothing in this document is implemented. The studio does not write to `production/characters/*.json`, `production/environments/environments.json`, `bible/` or any artwork, and AP-84B2 changed no registry entry. Implementing promotion needs a separately approved milestone.

## 1. Purpose

AP-84B1 lets a person approve a quarantined candidate. Approval creates a versioned **registry proposal** (`gen_registry_proposals`) and nothing else. This document describes how an approved proposal could later become a real registry entry without weakening the rules that protect approved artwork.

## 2. Principles

1. **Never overwrite.** Promotion adds a new version of an entry. It never replaces or edits an existing version, and never changes the file of an existing version.
2. **Human-gated twice.** Approval of the candidate (AP-84B1) and promotion into the registry are two separate decisions, each with a named person and a note. QA and validation never promote.
3. **Provenance travels with the asset.** The registry entry records the job, candidate SHA-256, reference pack (ID and pack SHA-256), validation report ID, review ID and proposal ID.
4. **Synthetic fixtures are never promotable.** Proposals recorded with `promotable = 0` are refused.
5. **Stories choose versions explicitly.** Promoting a new version does not change what an existing story renders until the story is updated and reviewed. This keeps every existing render reproducible.

## 3. Proposed flow

| Step | Who | What happens | Writes |
|---|---|---|---|
| 1. Approve candidate | Owner | AP-84B1 review with a note | `gen_reviews`, `gen_registry_proposals` (exists today) |
| 2. Pre-promotion checks | Studio | Re-hash the quarantined file and compare it with the proposal; require a latest validation report with no `fail`; re-verify the reference pack; confirm the target version number is still free | none |
| 3. Promotion decision | Owner | Explicit "promote" decision with a note, naming the approval class (e.g. `APPROVED_WORKING_TEST_ASSET`) and, for poses, the feet anchor and figure height | `gen_promotions` (new, append-only) |
| 4. Copy into the asset library | Studio | Copy the candidate to a new, versioned path, e.g. `bible/concepts/lookdev-richenv/generated/<character>/pose-07_v2.png`. Write-once: refuse if the path exists | one new file |
| 5. Registry entry | Studio | Add a new version entry under the pose or environment, with `file`, `sha256`, `source{jobId, candidateSha256, referencePack, validationId, reviewId, proposalId}`, `feet`, `figureHeight`, `approval`, `version`, `promotedAt`, `promotedBy` | registry JSON |
| 6. Verify | Studio | Re-hash the copied file against the registry entry; re-run `requirementsFor` for every story using the character | none |
| 7. Record | Owner / Claude | Update `ASSET_REGISTER.md` and the project records; commit after review | docs |

## 4. Registry shape (proposed)

Today a pose entry is a single object (version 1 by default). A future shape keeps the existing object as version 1 and adds versions beside it, so current readers keep working:

```json
"07": {
  "name": "surprised",
  "file": "…/pose-07_v1.png", "sha256": "…", "approval": "APPROVED_WORKING_TEST_ASSET", "version": 1,
  "versions": {
    "2": {"file": "…/pose-07_v2.png", "sha256": "…", "approval": "PROPOSED_PROMOTION", "source": {"jobId": "g-…", "proposalId": 12}}
  },
  "current": 1
}
```

- `current` names the version that stories get by default.
- Changing `current` is its own reviewed decision.
- A story can pin a version (`"pose": "07@2"`), which would need a small, separate change to the production engine's cast resolver.

## 5. Safety requirements for the future implementation

- **Allowed writes:** writes go only to the one registry file named in the proposal, and the new asset file under an allowed library folder. Path traversal and symlinks are refused, and nothing is written under `skills/` (the renderer).
- **Atomic, two-phase registry write:** write a temporary file, verify it parses and that every existing entry is byte-identical in value, then rename it into place. Keep a backup of the previous registry and its hash.
- **Concurrency:** refuse to promote if the registry's hash changed since the pre-promotion checks.
- **Audit:**
  - The promotion row is append-only, using database triggers as for `gen_reviews`.
  - Any rollback is a new, recorded decision that sets `current` back. It never deletes a version.
- **Tests:**
  - A promotion test runs against temporary registries only (the AP-84B2 test pattern) and asserts that real registries, stories and artwork are byte-identical afterwards.
  - Tests also cover: no overwrite, a refused synthetic fixture, a refused changed candidate, a refused stale version number, a refused validation `fail`, and a rollback that keeps history.

## 6. Out of scope

- Automatic promotion.
- Promotion from QA or validation results.
- Editing approved artwork.
- Changing stories to use new versions.
- Any GPU, model or external service.

## 7. Owner decisions (2026-11-13)

The owner answered the open questions on 2026-11-13, following ChatGPT's recommendations. These decisions set the rules for a future implementation. **They do not authorise implementing promotion**, which still needs its own approved milestone.

1. **Initial approval class:** a promoted generated pose starts as `APPROVED_WORKING_TEST_ASSET`.
2. **Location:** promoted files live under `bible/concepts/lookdev-richenv/generated/` (write-once, versioned names), separate from existing canonical artwork.
3. **Preview render before `current`:** a promoted version can become `current` only after a successful preview render that uses it.
   - **The render is a prerequisite, never an automatic approval.**
   - The owner still explicitly approves the promotion (step 3 in §3), and separately approves changing `current` (§4).
4. **Generated pose canvas:** newly generated poses use **1024×1536**, matching master v3. It is enforced as the `canvas-dimensions` validation check (`studio/config/canonical-references.json`). Existing approved poses are unchanged.

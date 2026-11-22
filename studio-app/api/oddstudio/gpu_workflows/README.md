# Pinned ComfyUI workflows for the self-hosted models

There is one file per self-hosted model in `shot_compare.GPU_MODELS`, named after its `workflow`:

- `infinitetalk-480p.json`
- `wan-2.2-s2v-480p.json`
- `latentsync-1.6.json`

Each file is ComfyUI's API-format graph. The studio sends it to the GPU worker with its SHA-256, and the clip's result
records that hash, so every clip traces back to the exact graph. **A model without its file cannot run** (the studio
says so in the comparison).

**Placeholders.** A placeholder is always a whole string. The worker refuses a graph that has a placeholder it cannot
fill.

| Placeholder | Filled with |
|---|---|
| `{{input:image.png}}` | the first frame (avatar models) |
| `{{input:video.mp4}}` | this line's Kling clip (lip-sync model) |
| `{{input:audio.wav}}` | the line's own recorded audio |
| `{{param:seconds}}` | `shot_compare.gpu_params` |
| `{{param:fps}}` | `shot_compare.gpu_params` |
| `{{param:prompt}}` | `shot_compare.gpu_params` |
| `{{param:negative}}` | `shot_compare.gpu_params` |
| `{{param:seed}}` | `shot_compare.gpu_params` |

The graphs are written and pinned in the $0 step before the paid proof of concept (see `studio-app/gpu-worker/README.md`).

"""The people cut out of an approved picture with rembg (birefnet-general) on the rented GPU session (owner-proven
method, 2026-11-26: the family-wall repaint of Episode 15, ep15-stills/fam-fireplace-12.png).

Why on the GPU session and not on the studio server: rembg[gpu] pulls onnxruntime-gpu and a ~1 GB BiRefNet model; the
session is already rented for the masked repaint, so cutting the people out there costs a few minutes of the same
session and nothing has to be installed on the studio server (the owner's internet can be very slow).

How (the same pattern as pose_remote.py): the studio copies the ONE picture to the pod over SSH with the session's
throwaway ed25519 key (its public half went to the pod as PUBLIC_KEY, the private half is kept encrypted in the GPU
ledger and dropped when the session ends), runs the script below, copies back one greyscale PNG (the people's alpha,
same size as the picture) and deletes both files on the pod. The picture is one of the studio's own generated images
(never a reference-video frame).

SSH host keys: each pod is new and its host key cannot be known in advance, so host-key checking is off for these
throwaway pods (StrictHostKeyChecking=no, no known_hosts file); the key works only on that one pod.
"""
from __future__ import annotations

import os
import shlex
import subprocess
import tempfile
from pathlib import Path

from .pose_remote import _ssh_opts

REMOTE_DIR = "/root/oddcut"
REMBG = "rembg[gpu]==2.0.67"
MODEL = "birefnet-general"

# Runs on the pod: picture.png -> alpha.png (L, 0 = background, 255 = a person), same size as the picture.
REMOTE_SCRIPT = r'''
import sys
from PIL import Image
from rembg import new_session, remove
im = Image.open("picture.png").convert("RGB")
m = remove(im, session=new_session(sys.argv[1]), only_mask=True)
m = m.convert("L")
if m.size != im.size:
    m = m.resize(im.size)
m.save("alpha.png")
print("alpha", m.size, flush=True)
'''

runner = subprocess.run     # tests replace this


def cut_out(host: str, port: int, private_key: str, picture: Path, dest: Path, log=print) -> Path:
    """Copy the picture to the pod, run rembg there, bring back the alpha PNG to `dest`. Returns dest."""
    work = Path(tempfile.mkdtemp(prefix="oddcut-"))
    key_file = work / "id"
    script = work / "cut.py"
    pic = work / "picture.png"
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(private_key if private_key.endswith("\n") else private_key + "\n")
        script.write_text(REMOTE_SCRIPT)
        from PIL import Image
        with Image.open(picture) as im:
            size = im.size
            im.convert("RGB").save(pic)
        target = f"root@{host}"
        o = _ssh_opts(key_file)

        def run(cmd: list[str], timeout: int, what: str):
            r = runner(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            if r.returncode != 0:
                raise RuntimeError(f"{what} failed: {(r.stderr or r.stdout or '')[-300:]}")
            return r

        run(["ssh", *o, "-p", str(port), target, f"rm -rf {REMOTE_DIR} && mkdir -p {REMOTE_DIR}"], 120, "connecting to the GPU over SSH")
        run(["scp", *o, "-P", str(port), str(pic), str(script), f"{target}:{REMOTE_DIR}/"], 600, "copying the picture")
        log("Cutting the people out on the GPU (rembg, BiRefNet)")
        remote = (f"cd {REMOTE_DIR} && (python3 -m pip install -q {shlex.quote(REMBG)} >/dev/null 2>&1 || true) && "
                  f"python3 cut.py {shlex.quote(MODEL)}")
        run(["ssh", *o, "-p", str(port), target, remote], 1800, "rembg on the GPU")
        run(["scp", *o, "-P", str(port), f"{target}:{REMOTE_DIR}/alpha.png", str(dest)], 300, "copying the cut-out back")
        runner(["ssh", *o, "-p", str(port), target, f"rm -rf {REMOTE_DIR}"], capture_output=True, text=True, timeout=120,
               stdin=subprocess.DEVNULL)
        with Image.open(dest) as m:
            m.load()
            if m.size != size:
                raise RuntimeError("the cut-out does not match the picture's size")
        return dest
    finally:
        for p in work.glob("*"):
            p.unlink(missing_ok=True)
        work.rmdir()

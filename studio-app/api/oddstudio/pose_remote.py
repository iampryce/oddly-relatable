"""The actor's pose points (no picture) read with MediaPipe 0.10.14 on the rented GPU session (owner-proven method,
2026-11-26: talk-run/pod_pose.py).

Why on the GPU session and not on the studio server: MediaPipe 0.10.14 ships wheels for Python 3.8-3.12 only, and the
API image (Debian trixie) runs Python 3.13, so it cannot be installed there. The session is already rented for the
render, so reading the poses there costs a few minutes of the same session.

How: the studio cuts the needed frames from the private reference video itself (FFmpeg, 16 fps, 480 px wide JPEGs), packs
them, copies them to the pod over SSH with a throwaway ed25519 key made for that session only (its public half goes to
the pod as PUBLIC_KEY, the private half is kept encrypted in the ledger and dropped when the session ends), runs the
script below, copies back one JSON file of points and deletes the frames on the pod. Only numbers come back. The frames
never reach ComfyUI or any generator: the movement guide sent to the model is drawn from the points (talking.py).

SSH host keys: each pod is new and its host key cannot be known in advance, so host-key checking is off for these
throwaway pods (StrictHostKeyChecking=no, no known_hosts file). The risk is limited: what travels is reference frames of
the owner's own upload and pose numbers, and the key works only on that one pod.
"""
from __future__ import annotations

import json
import os
import shlex
import subprocess
import tarfile
import tempfile
from pathlib import Path

REMOTE_DIR = "/root/oddpose"
MEDIAPIPE = "mediapipe==0.10.14"

# Runs on the pod. Input: frames/<window>/<nnnn>.jpg. Output: poses.json {window: {"size": [w, h], "seq": [points |
# null per frame]}}; each frame's points are 33 landmarks [x_px, y_px, visibility] in that frame's pixels.
REMOTE_SCRIPT = r'''
import glob, json, os, sys
import mediapipe as mp, numpy as np
from PIL import Image
out = {}
for d in sorted(glob.glob("frames/*")):
    pose = mp.solutions.pose.Pose(static_image_mode=False, model_complexity=1, min_detection_confidence=0.4)
    seq, size = [], [0, 0]
    for f in sorted(glob.glob(d + "/*.jpg")):
        im = Image.open(f).convert("RGB")
        w, h = im.size
        size = [w, h]
        r = pose.process(np.asarray(im))
        seq.append([[round(l.x * w, 2), round(l.y * h, 2), round(l.visibility, 3)] for l in r.pose_landmarks.landmark]
                   if r.pose_landmarks else None)
    pose.close()
    out[os.path.basename(d)] = {"size": size, "seq": seq}
    print(os.path.basename(d), len(seq), "frames", sum(1 for x in seq if x), "with a pose", flush=True)
json.dump(out, open("poses.json", "w"))
'''

runner = subprocess.run     # tests replace this


def new_keypair() -> tuple[str, str]:
    """(private key in OpenSSH PEM, public key line) of a fresh ed25519 key."""
    from cryptography.hazmat.primitives import serialization
    from cryptography.hazmat.primitives.asymmetric.ed25519 import Ed25519PrivateKey
    k = Ed25519PrivateKey.generate()
    priv = k.private_bytes(serialization.Encoding.PEM, serialization.PrivateFormat.OpenSSH, serialization.NoEncryption()).decode()
    pub = k.public_key().public_bytes(serialization.Encoding.OpenSSH, serialization.PublicFormat.OpenSSH).decode()
    return priv, pub + " oddstudio-throwaway"


def extract_frames(ffmpeg: str, video: Path, windows: dict[str, tuple[float, int]], folder: Path) -> Path:
    """Cut each window {name: (start seconds, frames)} at 16 fps into folder/frames/<name>/ and pack them as frames.tar."""
    root = folder / "frames"
    for name, (t0, n) in windows.items():
        d = root / name
        d.mkdir(parents=True, exist_ok=True)
        r = runner([ffmpeg, "-v", "error", "-y", "-ss", f"{max(0.0, t0):.3f}", "-i", str(video), "-frames:v", str(int(n)),
                    "-vf", "fps=16,scale=480:-2", "-q:v", "4", str(d / "%04d.jpg")],
                   capture_output=True, text=True, timeout=600, stdin=subprocess.DEVNULL)
        if r.returncode != 0:
            raise RuntimeError(f"frames for {name} could not be cut: {(r.stderr or '')[-200:]}")
    tar = folder / "frames.tar"
    with tarfile.open(tar, "w") as t:
        t.add(root, arcname="frames")
    return tar


def _ssh_opts(key_file: Path) -> list[str]:
    return ["-i", str(key_file), "-o", "StrictHostKeyChecking=no", "-o", "UserKnownHostsFile=/dev/null", "-o", "BatchMode=yes",
            "-o", "ConnectTimeout=20", "-o", "LogLevel=ERROR"]


def read_poses(host: str, port: int, private_key: str, frames_tar: Path, log=print) -> dict:
    """Copy the frames to the pod, run MediaPipe there, bring back the points. Returns {window: [points | None]}."""
    work = Path(tempfile.mkdtemp(prefix="oddpose-"))
    key_file = work / "id"
    script = work / "pose.py"
    try:
        fd = os.open(key_file, os.O_WRONLY | os.O_CREAT | os.O_EXCL, 0o600)
        with os.fdopen(fd, "w") as f:
            f.write(private_key if private_key.endswith("\n") else private_key + "\n")
        script.write_text(REMOTE_SCRIPT)
        target = f"root@{host}"
        o = _ssh_opts(key_file)

        def run(cmd: list[str], timeout: int, what: str):
            r = runner(cmd, capture_output=True, text=True, timeout=timeout, stdin=subprocess.DEVNULL)
            if r.returncode != 0:
                raise RuntimeError(f"{what} failed: {(r.stderr or r.stdout or '')[-300:]}")
            return r

        run(["ssh", *o, "-p", str(port), target, f"rm -rf {REMOTE_DIR} && mkdir -p {REMOTE_DIR}"], 120, "connecting to the GPU over SSH")
        run(["scp", *o, "-P", str(port), str(frames_tar), str(script), f"{target}:{REMOTE_DIR}/"], 900, "copying the frames")
        log("Reading the actor's pose points on the GPU (MediaPipe)")
        remote = (f"cd {REMOTE_DIR} && tar xf frames.tar && "
                  f"(python3 -m pip install -q {shlex.quote(MEDIAPIPE)} >/dev/null 2>&1 || true) && python3 pose.py")
        run(["ssh", *o, "-p", str(port), target, remote], 1800, "MediaPipe on the GPU")
        out = work / "poses.json"
        run(["scp", *o, "-P", str(port), f"{target}:{REMOTE_DIR}/poses.json", str(out)], 300, "copying the pose points back")
        runner(["ssh", *o, "-p", str(port), target, f"rm -rf {REMOTE_DIR}"], capture_output=True, text=True, timeout=120,
               stdin=subprocess.DEVNULL)
        data = json.loads(out.read_text())
        if not isinstance(data, dict):
            raise RuntimeError("the pose points file was not readable")
        return data
    finally:
        for p in work.glob("*"):
            p.unlink(missing_ok=True)
        work.rmdir()

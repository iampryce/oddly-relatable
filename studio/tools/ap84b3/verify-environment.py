#!/usr/bin/env python3
"""AP-84B3 environment check (owner decision A5: Option A, two-tier environment lock).

Runs on the Pod, with the image's own Python. It is copied into the Pod bundle next to environment.lock.

  verify-environment.py probe --out facts.json
      Collect facts about the running environment: Python, PyTorch, torchvision, torchaudio, the CUDA runtime
      PyTorch sees, the GPU, the driver, the image fingerprint and the installed package inventory. A tiny CUDA
      operation is attempted to prove the GPU works. Nothing is installed or changed.

  verify-environment.py check --lock environment.lock --facts facts.json --stage pre|post
      Compare facts with the environment lock. Exit 0 only if every tier 1 rule holds. The "post" stage runs after
      the ComfyUI requirements are installed and also requires the package inventory to be recorded.

  verify-environment.py run --lock environment.lock --stage pre|post --out record.json
      probe, then check, then write a record holding both (tier 2: inventory and its SHA-256, GPU, driver, CUDA).

The check is pure: it reads two JSON files and decides. That is what the local tests exercise, with clearly
synthetic facts. Nothing here can prove the real image or GPU locally; that happens only on the Pod.
"""
import argparse
import hashlib
import json
import os
import platform
import subprocess
import sys

PROBE_SCHEMA = "ap84b3-environment-facts/1"


def probe():
    facts = {"schema": PROBE_SCHEMA, "python": "%d.%d.%d" % sys.version_info[:3], "pythonExecutable": sys.executable,
             "platform": platform.platform(), "env": {k: os.environ.get(k) for k in ("CUDA_VERSION", "NV_CUDNN_VERSION")}, "errors": []}
    try:
        import torch  # noqa: imported only on the Pod
        facts["torch"] = torch.__version__
        facts["torchCuda"] = torch.version.cuda
        facts["float8"] = hasattr(torch, "float8_e4m3fn")
        facts["cudaAvailable"] = bool(torch.cuda.is_available())
        if facts["cudaAvailable"]:
            p = torch.cuda.get_device_properties(0)
            facts["gpuName"] = p.name
            facts["gpuComputeCapability"] = "%d.%d" % (p.major, p.minor)
            facts["gpuTotalMemoryBytes"] = int(p.total_memory)
            facts["gpuCount"] = torch.cuda.device_count()
            try:
                x = torch.ones(4, device="cuda") * 2
                facts["cudaOpOk"] = bool(float(x.sum().item()) == 8.0)
            except Exception as e:  # recorded, never hidden
                facts["cudaOpOk"] = False
                facts["errors"].append("cuda operation failed: %s" % e)
    except Exception as e:
        facts["errors"].append("torch import failed: %s" % e)
    for mod in ("torchvision", "torchaudio"):
        try:
            facts[mod] = __import__(mod).__version__
        except Exception as e:
            facts["errors"].append("%s import failed: %s" % (mod, e))
    try:
        out = subprocess.run(["nvidia-smi", "--query-gpu=driver_version,name", "--format=csv,noheader"], capture_output=True, text=True, timeout=60)
        facts["driverVersion"] = out.stdout.strip().splitlines()[0].split(",")[0].strip() if out.returncode == 0 and out.stdout.strip() else None
    except Exception as e:
        facts["driverVersion"] = None
        facts["errors"].append("nvidia-smi failed: %s" % e)
    try:
        out = subprocess.run([sys.executable, "-m", "pip", "freeze", "--all"], capture_output=True, text=True, timeout=300)
        inv = "\n".join(sorted(l for l in out.stdout.splitlines() if l.strip())) + "\n"
        facts["packageInventory"] = inv
        facts["packageInventorySha256"] = hashlib.sha256(inv.encode("utf-8")).hexdigest()
    except Exception as e:
        facts["errors"].append("pip freeze failed: %s" % e)
    return facts


def check(lock, facts, stage):
    """Return a list of problems (empty = the environment matches tier 1)."""
    p = []
    t1, img, gpu = lock.get("tier1", {}), lock.get("image", {}), lock.get("gpu", {})
    if facts.get("schema") != PROBE_SCHEMA:
        return ["the facts file is not an environment probe"]
    if stage not in ("pre", "post"):
        return ["stage must be pre or post"]
    for e in facts.get("errors") or []:
        p.append("probe error: %s" % e)
    if ".".join(str(facts.get("python", "")).split(".")[:2]) != t1.get("python"):
        p.append("Python is %s, the environment lock requires %s" % (facts.get("python"), t1.get("python")))
    for k in ("torch", "torchvision", "torchaudio"):
        if facts.get(k) != t1.get(k):
            p.append("%s is %s, the environment lock requires %s%s" % (k, facts.get(k), t1.get(k), " (it was replaced during installation)" if stage == "post" else ""))
    if facts.get("torchCuda") != t1.get("torchCuda"):
        p.append("PyTorch was built for CUDA %s, the environment lock requires %s" % (facts.get("torchCuda"), t1.get("torchCuda")))
    fp = img.get("fingerprint", {})
    for k in ("CUDA_VERSION", "NV_CUDNN_VERSION"):
        if (facts.get("env") or {}).get(k) != fp.get(k):
            p.append("image fingerprint %s is %s, expected %s: this does not look like the pinned image" % (k, (facts.get("env") or {}).get(k), fp.get(k)))
    if facts.get("cudaAvailable") is not True:
        p.append("PyTorch cannot use the GPU (torch.cuda.is_available() is false)")
    elif facts.get("cudaOpOk") is not True:
        p.append("a test operation on the GPU failed")
    allowed = gpu.get("allowed", {})
    name = facts.get("gpuName")
    if name not in allowed:
        p.append("GPU %r is not one of the approved GPUs (%s)" % (name, ", ".join(sorted(allowed))))
    elif facts.get("gpuComputeCapability") != allowed[name].get("computeCapability"):
        p.append("GPU compute capability is %s, expected %s for %s" % (facts.get("gpuComputeCapability"), allowed[name].get("computeCapability"), name))
    if not isinstance(facts.get("gpuTotalMemoryBytes"), int) or facts["gpuTotalMemoryBytes"] < gpu.get("minTotalMemoryBytes", 0):
        p.append("GPU memory %s bytes is below the required %s" % (facts.get("gpuTotalMemoryBytes"), gpu.get("minTotalMemoryBytes")))
    if facts.get("gpuCount") not in (None, 1) and isinstance(facts.get("gpuCount"), int) and facts["gpuCount"] != 1:
        p.append("expected exactly one GPU, found %s" % facts.get("gpuCount"))
    if gpu.get("requireFloat8Dtype") and facts.get("float8") is not True:
        p.append("this PyTorch build has no float8_e4m3fn type, which the FP8 Qwen model needs")
    if not facts.get("driverVersion"):
        p.append("the GPU driver version could not be read (tier 2 requires it to be recorded)")
    if stage == "post":
        inv, sha = facts.get("packageInventory"), facts.get("packageInventorySha256")
        if not inv or not sha or hashlib.sha256(inv.encode("utf-8")).hexdigest() != sha:
            p.append("the installed package inventory was not recorded, or its SHA-256 does not match")
    return p


def main(argv):
    ap = argparse.ArgumentParser(description=__doc__.splitlines()[0])
    sub = ap.add_subparsers(dest="cmd", required=True)
    a = sub.add_parser("probe"); a.add_argument("--out", required=True)
    b = sub.add_parser("check"); b.add_argument("--lock", required=True); b.add_argument("--facts", required=True); b.add_argument("--stage", required=True)
    c = sub.add_parser("run"); c.add_argument("--lock", required=True); c.add_argument("--stage", required=True); c.add_argument("--out", required=True)
    args = ap.parse_args(argv)
    if args.cmd == "probe":
        with open(args.out, "x", encoding="utf-8") as f:
            json.dump(probe(), f, indent=1)
        return 0
    lock = json.load(open(args.lock, encoding="utf-8"))
    facts = json.load(open(args.facts, encoding="utf-8")) if args.cmd == "check" else probe()
    problems = check(lock, facts, args.stage)
    result = {"stage": args.stage, "ok": not problems, "problems": problems}
    if args.cmd == "run":
        record = {"schema": "ap84b3-environment-record/1", **result, "facts": facts}
        with open(args.out, "x", encoding="utf-8") as f:
            json.dump(record, f, indent=1)
    print(json.dumps(result, indent=1))
    return 0 if not problems else 1


if __name__ == "__main__":
    sys.exit(main(sys.argv[1:]))

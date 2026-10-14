#!/usr/bin/env python3
"""Check that the pinned official Prithvi flood task bundle is present."""

from __future__ import annotations

import json
import os
import sys
import tempfile
from pathlib import Path

from dotenv import load_dotenv

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT))
DEFAULT_DIR = ROOT / "models" / "prithvi" / "flood_sen1floods11"
CHECKPOINT = "Prithvi-EO-V2-300M-TL-Sen1Floods11.pt"
SAMPLE = Path("examples/India_900498_S2Hand.tif")
load_dotenv(ROOT / ".env")


def main() -> int:
    model_dir = Path(os.getenv("PRITHVI_MODEL_DIR", str(DEFAULT_DIR)))
    if not model_dir.is_absolute():
        model_dir = ROOT / model_dir
    print("OSEAS Prithvi Sen1Floods11 bundle")
    print(f"Model directory: {model_dir}")
    metadata_path = ROOT / "models" / "prithvi" / "flood_model.json"
    try:
        metadata = json.loads(metadata_path.read_text(encoding="utf-8"))
    except (OSError, json.JSONDecodeError) as error:
        print(f"NOT READY: model metadata is missing or invalid: {error}")
        return 1
    required = [model_dir / CHECKPOINT, model_dir / "config.yaml", model_dir / "inference.py", model_dir / SAMPLE]
    missing = [str(path) for path in required if not path.is_file() or path.stat().st_size == 0]
    if missing:
        print("NOT READY: missing model bundle files:")
        for path in missing:
            print(f"  - {path}")
        print("Run `npm run oseas:prithvi:setup` to fetch the pinned official bundle.")
        return 1
    try:
        import torch
        if not torch.cuda.is_available():
            print("Runtime: CPU (inference will be slower)")
        else:
            print(f"Runtime: CUDA ({torch.cuda.get_device_name(0)})")
    except ImportError:
        print("NOT READY: PyTorch is missing; install requirements.txt")
        return 1
    print(f"Checkpoint: {metadata['model_id']} @ {metadata['model_revision']}")
    print(f"Task: {metadata['task']} | sensor: {metadata['sensor']} | bands: {', '.join(metadata['bands'])}")
    print(f"Checkpoint size: {required[0].stat().st_size / 1024**3:.2f} GiB")
    print("Bundle files: PASS")
    try:
        from scripts.run_prithvi_flood import _configure_proj_data, _run_official_inference
        _configure_proj_data()
        with tempfile.TemporaryDirectory(prefix="oseas-prithvi-smoke-") as output_dir:
            prediction = _run_official_inference(model_dir / SAMPLE, Path(output_dir), model_dir, [1, 2, 3, 8, 11, 12])
            if not prediction.is_file() or prediction.stat().st_size == 0:
                print("NOT READY: official Prithvi smoke test did not produce a prediction raster")
                return 1
        print("Official model load and sample inference: PASS")
    except Exception as error:
        print(f"NOT READY: official model inference failed: {type(error).__name__}: {error}")
        return 1
    print("Kenya validation: NOT EVALUATED")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

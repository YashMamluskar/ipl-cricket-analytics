"""
Phase 6f - Crop Power BI Desktop window captures down to the report canvas.

The canvas is found automatically as the bounding box of the page-background colour (#1A0F2E),
so the crops stay correct if the window size changes. Originals are kept in dashboard/screenshots/raw/.

    python python/06f_crop_screenshots.py
"""
from pathlib import Path
import shutil
import sys

import numpy as np
from PIL import Image

sys.path.insert(0, str(Path(__file__).resolve().parent))
import ipl_config as cfg  # noqa: E402

SHOTS = cfg.PROJECT_ROOT / "dashboard" / "screenshots"
BG = np.array([0x1A, 0x0F, 0x2E])


def crop(path: Path):
    img = Image.open(path).convert("RGB")
    a = np.asarray(img).astype(int)
    mask = (np.abs(a - BG).sum(axis=2) <= 6)
    rows = np.where(mask.sum(axis=1) > a.shape[1] * 0.25)[0]
    cols = np.where(mask.sum(axis=0) > a.shape[0] * 0.25)[0]
    if len(rows) == 0 or len(cols) == 0:
        raise RuntimeError(f"canvas not found in {path.name}")
    x0, x1, y0, y1 = int(cols.min()), int(cols.max()) + 1, int(rows.min()), int(rows.max()) + 1
    # the page is 1280 x 720 (16:9) and sits vertically centred in the background-coloured area
    h = round((x1 - x0) * 720 / 1280)
    top = y0 + max(0, ((y1 - y0) - h) // 2)
    box = (x0, top, x1, min(y1, top + h))
    return img.crop(box), box


def main():
    raw = SHOTS / "raw"
    raw.mkdir(parents=True, exist_ok=True)
    for p in sorted(SHOTS.glob("0*.png")):
        src = raw / p.name
        if not src.exists():
            shutil.copy2(p, src)
        out, box = crop(src)
        out.save(p)
        print(f"{p.name}: canvas {box} -> {out.size}")


if __name__ == "__main__":
    main()

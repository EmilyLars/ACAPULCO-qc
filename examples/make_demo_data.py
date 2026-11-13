#!/usr/bin/env python3
"""
Make a small synthetic dataset so you can try the QC app without real data.

  python3 examples/make_demo_data.py
  python3 app/qc_app.py --data QC_data/demo --rater ME

Creates 40 fake subjects with ACAPULCO-style file names in examples/demo_acapulco/, two with
planted problems (a missing lobule, and one lobule swallowing its neighbor), then runs the prep.
The images are geometric shapes, not brains.
"""
import os, subprocess, sys
import numpy as np
import nibabel as nib

HERE = os.path.dirname(os.path.abspath(__file__))
ROOT = os.path.dirname(HERE)
OUT = os.path.join(HERE, "demo_acapulco")
LABELS = [12, 33, 36, 43, 46, 53, 56, 60, 63, 66, 70, 73, 74, 75, 76, 77, 78, 80, 83, 84, 86, 87, 90, 93, 96, 100, 103, 106]

rng = np.random.default_rng(0)
shape = (120, 110, 100)
aff = np.diag([1.0, 1.0, 1.0, 1.0]); aff[:3, 3] = [-60, -90, -60]
x, y, z = np.meshgrid(*[np.arange(n) for n in shape], indexing="ij")
for i in range(40):
    sub = "sub-%02d" % (i + 1)
    d = os.path.join(OUT, sub); os.makedirs(d, exist_ok=True)
    s = 1 + rng.normal(0, 0.05)
    t1 = 800 * np.exp(-(((x - 60) / 50) ** 2 + ((y - 55) / 50) ** 2 + ((z - 50) / 45) ** 2)) + rng.normal(0, 15, shape)
    r = np.sqrt(((x - 60) / (35 * s)) ** 2 + ((y - 35) / (20 * s)) ** 2 + ((z - 35) / (18 * s)) ** 2)
    m = r < 1
    t1[m] += 250
    seg = np.zeros(shape, np.uint8)
    ang = np.arctan2(z[m] - 35, x[m] - 60)
    edges = np.linspace(-np.pi, np.pi, len(LABELS) + 1)[1:-1] + rng.normal(0, 0.03, len(LABELS) - 1)
    seg[m] = np.array(LABELS, np.uint8)[np.searchsorted(edges, ang)]
    if i == 3: seg[seg == 53] = 0
    if i == 7: seg[seg == 74] = 73
    base = os.path.join(d, sub + "_T1")
    nib.save(nib.Nifti1Image(t1.astype(np.float32), aff), base + ".nii.gz")
    nib.save(nib.Nifti1Image(seg, aff), base + "_n4_mni_seg_post_inverse.nii.gz")
    with open(base + "_n4_mni_seg_post_volumes.csv", "w") as f:
        f.write("name,label,volume\n")
subprocess.check_call([sys.executable, os.path.join(ROOT, "prep", "qc_prep.py"),
                       "--seg-glob", os.path.join(OUT, "*", "*_n4_mni_seg_post_inverse.nii.gz"),
                       "--out", os.path.join(ROOT, "QC_data", "demo")])
print("\nNow run:  python3 app/qc_app.py --data QC_data/demo --rater ME")

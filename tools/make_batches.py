#!/usr/bin/env python3
"""
Split a dataset's subjects into one batch file per rater.

  python3 make_batches.py --data QC_data/CENC --raters JS AB CD
  -> batch_CENC_JS.txt, batch_CENC_AB.txt, batch_CENC_CD.txt (in the current folder)

Subjects are dealt out in turn (1st to JS, 2nd to AB, ...) after sorting by ID, so every
batch gets a similar mix of sites and of flagged subjects. Each subject is in exactly one batch.
Add --overlap 10 to also give every rater the same 10 extra subjects for inter-rater agreement.
"""
import argparse, json, os, random

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
ap.add_argument("--raters", nargs="+", required=True)
ap.add_argument("--overlap", type=int, default=0, help="number of shared subjects every rater also rates")
ap.add_argument("--seed", type=int, default=1)
a = ap.parse_args()

subs = [s for s in json.load(open(os.path.join(a.data, "index.json")))["subjects"]]
flagged = sorted(s["id"] for s in subs if s.get("flags"))
clean = sorted(s["id"] for s in subs if not s.get("flags"))
ordered = flagged + clean  # deal flagged first so they spread evenly too
ds = os.path.basename(os.path.normpath(a.data))
batches = {r: [] for r in a.raters}
for i, sid in enumerate(ordered):
    batches[a.raters[i % len(a.raters)]].append(sid)
shared = sorted(random.Random(a.seed).sample(ordered, min(a.overlap, len(ordered)))) if a.overlap else []
for r, ids in batches.items():
    ids = sorted(set(ids) | set(shared))
    fn = "batch_%s_%s.txt" % (ds, r)
    with open(fn, "w") as f:
        f.write("\n".join(ids) + "\n")
    print("%s: %d subjects" % (fn, len(ids)))
if shared:
    with open("batch_%s_overlap.txt" % ds, "w") as f:
        f.write("\n".join(shared) + "\n")
    print("Shared subjects rated by everyone: batch_%s_overlap.txt (%d)" % (ds, len(shared)))

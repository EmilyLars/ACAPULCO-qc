#!/usr/bin/env python3
"""
Combine every rater's ratings for one dataset into a single CSV.

  python3 merge_ratings.py --data QC_data/CENC
  -> QC_data/CENC/ratings_all.csv  (one row per subject per rater)

Put each RA's ratings_<initials>.json for that dataset into QC_data/CENC/ratings/ first.
Prints subjects rated by more than one rater and subjects nobody has rated yet.
"""
import argparse, csv, glob, json, os

ap = argparse.ArgumentParser()
ap.add_argument("--data", required=True)
a = ap.parse_args()
index = json.load(open(os.path.join(a.data, "index.json")))
names = [l["name"] for l in index["labels"]]
flags = {s["id"]: "; ".join(s.get("flags", [])) for s in index["subjects"]}
rows, by_sub = [], {}
for jp in sorted(glob.glob(os.path.join(a.data, "ratings", "ratings_*.json"))):
    rater = os.path.basename(jp)[len("ratings_"):-len(".json")]
    for sub, r in json.load(open(jp)).items():
        lob = r.get("lobules", {})
        rows.append([sub, rater, r.get("timestamp", ""), r.get("overall", ""),
                     sum(v == "Under" for v in lob.values()), sum(v == "Over" for v in lob.values())]
                    + [lob.get(n, "") for n in names] + [r.get("notes", ""), flags.get(sub, "")])
        if r.get("overall"):
            by_sub.setdefault(sub, []).append(rater)
out = os.path.join(a.data, "ratings_all.csv")
with open(out, "w", newline="") as f:
    w = csv.writer(f)
    w.writerow(["subject", "rater", "timestamp", "overall", "n_under", "n_over"] + names + ["notes", "auto_flags"])
    w.writerows(sorted(rows))
multi = {s: r for s, r in by_sub.items() if len(r) > 1}
unrated = [s["id"] for s in index["subjects"] if s["id"] not in by_sub]
print("Wrote %s: %d ratings from %d raters" % (out, len(rows), len({r[1] for r in rows})))
print("Subjects rated by more than one rater: %d" % len(multi))
print("Subjects not yet rated by anyone: %d" % len(unrated))

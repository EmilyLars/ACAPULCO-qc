#!/usr/bin/env python3
"""
Prepare ACAPULCO outputs for the interactive QC app.

For each subject: crops the T1 and native-space label image to the cerebellum plus a margin,
rescales the T1 to 8-bit for display, computes per-label volumes and centroids, and flags
likely problems. Writes a small, portable QC folder that the app reads.

Runs on Python 3.6+ with numpy and nibabel only (works inside acapulco-0.2.1.sif).

Subject ID = the name of the folder holding each label image (ACAPULCO's output folder per subject).
T1 = --t1-pattern if given, otherwise the ACAPULCO input image left in that folder
     (label file name with "_n4_mni_seg_post_inverse.nii.gz" replaced by ".nii.gz").

Examples:
  # T1 still in each ACAPULCO output folder
  python3 prep/qc_prep.py --seg-glob "acapulco_out/MyStudy/*/*_n4_mni_seg_post_inverse.nii.gz" --out QC_data/MyStudy

  # T1s stored elsewhere, with ages for age-adjusted flags
  python3 prep/qc_prep.py --seg-glob "acapulco_out/MyStudy/*/*_n4_mni_seg_post_inverse.nii.gz" \\
      --t1-pattern "/data/MyStudy/{sub}/anat/{sub}_T1w.nii.gz" --demo ages.csv --out QC_data/MyStudy
"""
import argparse, csv, glob, json, os, sys
import numpy as np
import nibabel as nib

SEG_SUFFIX = "_n4_mni_seg_post_inverse.nii.gz"


def read_lut(path):
    lut = {}
    if path:
        with open(path) as f:
            for row in csv.reader(f):
                if not row or row[0].strip().lower() in ("value", "label", ""):
                    continue
                lut[int(float(row[0]))] = row[1].strip()
    return lut


def read_demo(path):
    """CSV with a 'subject' column and an 'age' or 'age_y' column. Other columns ignored."""
    demo = {}
    if path:
        with open(path) as f:
            r = csv.DictReader(f)
            agecol = "age_y" if "age_y" in r.fieldnames else ("age" if "age" in r.fieldnames else None)
            for row in r:
                demo[row["subject"]] = float(row[agecol]) if agecol and row[agecol] not in ("", "NA") else None
    return demo


def robust_z(x):
    x = np.asarray(x, float)
    med = np.nanmedian(x)
    mad = np.nanmedian(np.abs(x - med)) * 1.4826
    if not np.isfinite(mad) or mad == 0:
        mad = np.nanstd(x) or 1.0
    return (x - med) / mad


def resid_z(y, age):
    """Robust z of residuals after a quadratic age fit, where age is available."""
    y = np.asarray(y, float)
    ok = np.isfinite(y) & np.isfinite(age)
    out = np.full(len(y), np.nan)
    if ok.sum() >= 20:
        X = np.column_stack([np.ones(ok.sum()), age[ok], age[ok] ** 2])
        beta = np.linalg.lstsq(X, y[ok], rcond=None)[0]
        res = y - np.column_stack([np.ones(len(y)), age, age ** 2]).dot(beta)
        out[ok] = robust_z(res[ok])
        no_age = np.isfinite(y) & ~np.isfinite(age)
        if no_age.any():
            out[no_age] = robust_z(y)[no_age]
    else:
        out[np.isfinite(y)] = robust_z(y[np.isfinite(y)])
    return out


def crop_subject(sub, seg_path, t1_path, outdir, margin_mm):
    seg_img = nib.load(seg_path)
    t1_img = nib.load(t1_path)
    seg = np.asanyarray(seg_img.dataobj).astype(np.int32)
    if seg.shape != t1_img.shape[:3] or not np.allclose(seg_img.affine, t1_img.affine, atol=1e-3):
        raise ValueError("label image and T1 are not in the same space (shape or affine differ)")
    nz = np.argwhere(seg > 0)
    if nz.size == 0:
        raise ValueError("label image is empty")
    zooms = np.array(seg_img.header.get_zooms()[:3], float)
    pad = np.ceil(margin_mm / zooms).astype(int)
    lo = np.maximum(nz.min(0) - pad, 0)
    hi = np.minimum(nz.max(0) + pad + 1, seg.shape)
    sl = tuple(slice(a, b) for a, b in zip(lo, hi))
    seg_c = seg[sl]
    t1_c = np.asanyarray(t1_img.dataobj)[sl].astype(np.float32)
    aff = seg_img.affine.copy()
    aff[:3, 3] = seg_img.affine[:3, :3].dot(lo) + seg_img.affine[:3, 3]

    p1, p99 = np.percentile(t1_c[t1_c > 0], [0.5, 99.5]) if (t1_c > 0).any() else (0, 1)
    t1_u8 = np.clip((t1_c - p1) / max(p99 - p1, 1e-6) * 255, 0, 255).astype(np.uint8)

    os.makedirs(outdir, exist_ok=True)
    for name, arr in (("t1.nii.gz", t1_u8), ("seg.nii.gz", seg_c.astype(np.uint8))):
        img = nib.Nifti1Image(arr, aff)
        img.set_qform(aff, 1)
        img.set_sform(aff, 1)
        nib.save(img, os.path.join(outdir, name))

    vox_mm3 = float(np.prod(zooms))
    vols, cents = {}, {}
    for v in np.unique(seg_c):
        if v == 0:
            continue
        idx = np.argwhere(seg_c == v)
        vols[int(v)] = idx.shape[0] * vox_mm3
        c = idx.mean(0)
        cents[int(v)] = [float(x) for x in aff[:3, :3].dot(c) + aff[:3, 3]]
    return vols, cents


def main():
    ap = argparse.ArgumentParser(description=__doc__, formatter_class=argparse.RawDescriptionHelpFormatter)
    ap.add_argument("--seg-glob", required=True, help="glob for *_T1_n4_mni_seg_post_inverse.nii.gz files (quote it)")
    ap.add_argument("--t1-pattern", default=None,
                    help="path to each subject's T1 with {sub} in place of the subject ID; omit if the T1 is still in the ACAPULCO output folder")
    ap.add_argument("--out", required=True, help="output QC folder")
    ap.add_argument("--lut", default=os.path.join(os.path.dirname(os.path.abspath(__file__)), "acapulco_labels.csv"),
                    help="CSV of label value,name (default: acapulco_labels.csv next to this script)")
    ap.add_argument("--demo", default=None, help="CSV with subject and age (or age_y) columns, for age-adjusted flags")
    ap.add_argument("--margin-mm", type=float, default=8.0)
    ap.add_argument("--z-flag", type=float, default=3.0)
    ap.add_argument("--redo", action="store_true", help="re-crop subjects that already have cropped images")
    a = ap.parse_args()

    lut, demo = read_lut(a.lut), read_demo(a.demo)
    segs = sorted(glob.glob(a.seg_glob))
    if not segs:
        sys.exit("No label images matched --seg-glob")
    os.makedirs(a.out, exist_ok=True)
    cache_path = os.path.join(a.out, "volumes_cache.json")
    cache = json.load(open(cache_path)) if os.path.exists(cache_path) and not a.redo else {}

    subjects, skipped = [], []
    for i, sp in enumerate(segs):
        sub = os.path.basename(os.path.dirname(os.path.abspath(sp)))
        t1p = a.t1_pattern.format(sub=sub) if a.t1_pattern else sp[: -len(SEG_SUFFIX)] + ".nii.gz"
        sdir = os.path.join(a.out, "subjects", sub)
        vol_csv = sp[: -len("_inverse.nii.gz")] + "_volumes.csv"
        if os.path.getsize(sp) == 0 or not os.path.exists(vol_csv):
            skipped.append([sub, "ACAPULCO did not finish (empty label file or no volumes CSV)"])
            continue
        rec = {"id": sub, "age": demo.get(sub), "error": None}
        if sub in cache and os.path.exists(os.path.join(sdir, "seg.nii.gz")):
            rec["vol"], rec["cent"] = cache[sub]["vol"], cache[sub]["cent"]
        else:
            try:
                if not os.path.exists(t1p):
                    raise ValueError("T1 not found: " + t1p)
                vols, cents = crop_subject(sub, sp, t1p, sdir, a.margin_mm)
                rec["vol"] = {str(k): v for k, v in vols.items()}
                rec["cent"] = {str(k): v for k, v in cents.items()}
                cache[sub] = {"vol": rec["vol"], "cent": rec["cent"]}
            except Exception as e:
                rec["error"] = str(e)
                rec["vol"], rec["cent"] = {}, {}
        subjects.append(rec)
        if (i + 1) % 25 == 0 or i + 1 == len(segs):
            print("processed %d/%d" % (i + 1, len(segs)), flush=True)
    json.dump(cache, open(cache_path, "w"))

    ok = [s for s in subjects if not s["error"]]
    all_labels = sorted({int(k) for s in ok for k in s["vol"]})
    common = [v for v in all_labels if sum(str(v) in s["vol"] for s in ok) >= 0.9 * len(ok)]
    age = np.array([s["age"] if s["age"] is not None else np.nan for s in ok], float)
    total = np.array([sum(s["vol"].values()) for s in ok])

    # Flags: total cerebellar volume vs age, each label's share of the total vs age, missing labels
    z_total = resid_z(total, age)
    zs = {}
    for v in all_labels:
        frac = np.array([s["vol"].get(str(v), np.nan) for s in ok]) / total
        zs[v] = resid_z(frac, age)
    for j, s in enumerate(ok):
        s["z_total"] = None if not np.isfinite(z_total[j]) else round(float(z_total[j]), 2)
        s["z"] = {str(v): round(float(zs[v][j]), 2) for v in all_labels if np.isfinite(zs[v][j])}
        flags = []
        if s["z_total"] is not None and abs(s["z_total"]) > a.z_flag:
            flags.append("total volume z=%.1f" % s["z_total"])
        for v in common:
            if str(v) not in s["vol"]:
                flags.append("%s missing" % lut.get(v, "Label %d" % v))
            elif abs(s["z"].get(str(v), 0)) > a.z_flag:
                flags.append("%s z=%+.1f" % (lut.get(v, "Label %d" % v), s["z"][str(v)]))
        s["flags"] = flags
    for s in subjects:
        if s["error"]:
            s["flags"] = ["prep error: " + s["error"]]
            s.setdefault("z", {})
            s["z_total"] = None

    index = {
        "labels": [{"value": v, "name": lut.get(v, "Label %d" % v)} for v in all_labels],
        "z_flag": a.z_flag,
        "subjects": subjects,
    }
    with open(os.path.join(a.out, "index.json"), "w") as f:
        json.dump(index, f)

    with open(os.path.join(a.out, "flags.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subject", "age", "n_flags", "flags"])
        for s in subjects:
            w.writerow([s["id"], s["age"], len(s["flags"]), "; ".join(s["flags"])])

    with open(os.path.join(a.out, "skipped.csv"), "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["subject", "reason"])
        w.writerows(skipped)
    print("Skipped %d subjects where ACAPULCO did not finish (listed in skipped.csv)" % len(skipped))
    n_flag = sum(1 for s in subjects if s["flags"])
    print("Done: %d subjects, %d flagged, %d prep errors. Output in %s"
          % (len(subjects), n_flag, sum(1 for s in subjects if s["error"]), a.out))


if __name__ == "__main__":
    main()

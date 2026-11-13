#!/bin/bash
#SBATCH --job-name=acapulco-qc-prep
#SBATCH --time=01:00:00
#SBATCH --ntasks=1
#SBATCH --mem=8G
#SBATCH --account=YOUR_ACCOUNT      # edit
#SBATCH --partition=YOUR_PARTITION  # edit
#
# Run the QC prep for one dataset on a Slurm cluster.
#
#   sbatch prep/run_prep_slurm.sh <dataset name>            (run from the repo folder)
#   sbatch prep/run_prep_slurm.sh MyStudy ages.csv          (optional ages CSV)
#
# Expects ACAPULCO outputs in $ACAPULCO_OUT/<dataset>/<subject>/ and writes QC_data/<dataset>/.
# Edit the settings below once for your cluster.

ACAPULCO_OUT=/path/to/acapulco/output        # folder holding one subfolder per dataset
SIF=/path/to/acapulco-0.2.1.sif              # ACAPULCO container (has numpy + nibabel); leave empty to use your own Python
T1_PATTERN=""                                # e.g. "/data/{sub}/anat/{sub}_T1w.nii.gz"; empty = T1 left in the ACAPULCO folder

DS=${1:?give the dataset folder name under $ACAPULCO_OUT}
DEMO=${2:-}
ARGS=(--seg-glob "$ACAPULCO_OUT/$DS/*/*_n4_mni_seg_post_inverse.nii.gz" --out "QC_data/$DS")
[ -n "$T1_PATTERN" ] && ARGS+=(--t1-pattern "$T1_PATTERN")
[ -n "$DEMO" ] && ARGS+=(--demo "$DEMO")

export PYTHONNOUSERSITE=1   # keep packages in ~/.local out of the container
if [ -n "$SIF" ]; then
  module load singularity 2>/dev/null || module load apptainer 2>/dev/null || true
  RUN=$(command -v singularity || command -v apptainer)
  # Bind the repo, the ACAPULCO outputs, and the T1 location so the container can see them
  BINDS="-B $PWD:$PWD -B $ACAPULCO_OUT:$ACAPULCO_OUT"
  [ -n "$T1_PATTERN" ] && BINDS="$BINDS -B $(echo "$T1_PATTERN" | cut -d/ -f1-3):$(echo "$T1_PATTERN" | cut -d/ -f1-3)"
  $RUN exec $BINDS "$SIF" python3 prep/qc_prep.py "${ARGS[@]}"
else
  python3 prep/qc_prep.py "${ARGS[@]}"
fi

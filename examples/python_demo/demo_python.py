"""
Baobab HPC demo (Python).

Analyses the synthetic sessions in ../demo_data: dF/F, event detection, event
rates and stimulus-triggered responses. Writes, per session, a CSV summary and
a PNG figure into the results folder.

On Baobab:  BAOBAB_DATA / BAOBAB_RESULTS point to the job's data and results.
            In a job array, the task number arrives as sys.argv[1] and selects
            one session (array range 1-4).
Locally:    python demo_python.py [session]   (uses ../demo_data and ./results)

Checkpoints: the sessions already analysed are recorded in BAOBAB_CHECKPOINT_DIR.
When the file named by BAOBAB_TIME_UP appears (shortly before the time limit),
the script stops and exits with code 3; with "Continue automatically" ticked, the
next run skips the finished sessions. To try it, set SECONDS_PER_SESSION = 120
below and submit with a wall time of 00:05:00.
"""
import csv
import os
import platform
import sys
import time
from pathlib import Path

import numpy as np
import matplotlib
matplotlib.use("Agg")                  # no display on the cluster
import matplotlib.pyplot as plt

from utils.analysis import delta_f_over_f, detect_events, triggered_average

SECONDS_PER_SESSION = 0        # set to 120 to try automatic continuation (see above)
SECONDS_PER_SESSION = float(os.environ.get("DEMO_SECONDS_PER_SESSION", SECONDS_PER_SESSION))
CONTINUE_LATER = 3             # exit code: "checkpoint saved, run me again"

here = Path(__file__).resolve().parent
data_dir = Path(os.environ.get("BAOBAB_DATA") or here.parent / "demo_data")
out_dir = Path(os.environ.get("BAOBAB_RESULTS") or here / "results")
out_dir.mkdir(parents=True, exist_ok=True)

sessions = sorted(data_dir.glob("session_*.csv"))
if not sessions:
    sys.exit(f"No session_*.csv found in {data_dir}")
if len(sys.argv) > 1:                  # job array: one session per task
    task = int(sys.argv[1])
    sessions = [p for p in sessions if p.stem == f"session_{task:02d}"]
    if not sessions:
        sys.exit(f"No session number {task} in {data_dir}")

onsets = np.loadtxt(data_dir / "stimulus_onsets.csv", skiprows=1, ndmin=1)

# checkpoint: which sessions are already done (kept between the runs of a job on
# Baobab; a local run always starts from scratch)
ckpt_dir = os.environ.get("BAOBAB_CHECKPOINT_DIR")
progress = (Path(ckpt_dir) / ("demo_progress.txt" if len(sys.argv) <= 1
                              else f"demo_progress_{sys.argv[1]}.txt")) if ckpt_dir else None
done = set(progress.read_text().split()) if progress and progress.exists() else set()


def time_up() -> bool:
    """True once Baobab has warned that the time limit is close."""
    flag = os.environ.get("BAOBAB_TIME_UP")
    return bool(flag) and os.path.exists(flag)


print(f"Python {platform.python_version()} on {platform.node()}, "
      f"{os.environ.get('SLURM_CPUS_PER_TASK', '1')} CPU(s); data: {data_dir}")

for path in sessions:
    if path.stem in done:
        print(f"{path.stem}: done in an earlier run - skipped")
        continue
    if time_up():
        print(f"Time is almost up: {len(done)} of {len(sessions)} session(s) done, "
              "the next run continues from here")
        sys.exit(CONTINUE_LATER)
    t0 = time.time()
    table = np.loadtxt(path, delimiter=",", skiprows=1)
    t, traces = table[:, 0], table[:, 1:]
    fs = 1 / np.median(np.diff(t))
    dff = delta_f_over_f(traces)
    events = detect_events(dff, fs)
    rates = np.array([len(e) / (t[-1] - t[0]) for e in events])
    axis, avg = triggered_average(dff, t, onsets)
    base = avg[axis < 0].mean(axis=0)
    response = avg[(axis > 0) & (axis < 1.5)].max(axis=0) - base

    name = path.stem
    with open(out_dir / f"{name}_summary.csv", "w", newline="") as f:
        w = csv.writer(f)
        w.writerow(["cell", "event_rate_hz", "mean_dff", "stim_response_dff"])
        for c in range(traces.shape[1]):
            w.writerow([c + 1, f"{rates[c]:.4f}", f"{dff[:, c].mean():.4f}", f"{response[c]:.4f}"])

    fig, ax = plt.subplots(1, 2, figsize=(11, 4.5), gridspec_kw={"width_ratios": [2, 1]})
    im = ax[0].imshow(dff.T, aspect="auto", cmap="magma", vmin=0,
                      vmax=np.percentile(dff, 99.5), extent=[t[0], t[-1], dff.shape[1] + 0.5, 0.5])
    for on in onsets:
        ax[0].axvline(on, color="c", lw=0.8, alpha=0.7)
    ax[0].set(xlabel="time (s)", ylabel="cell", title=f"{name}: dF/F (cyan = stimulus)",
              yticks=np.arange(1, traces.shape[1] + 1, 2))
    fig.colorbar(im, ax=ax[0], label="dF/F")
    ax[1].bar(np.arange(1, traces.shape[1] + 1), response, color="#3b6fe0")
    ax[1].set(xlabel="cell", ylabel="peak dF/F after stimulus", title="stimulus response")
    fig.tight_layout()
    fig.savefig(out_dir / f"{name}_overview.png", dpi=120)
    plt.close(fig)
    if SECONDS_PER_SESSION:
        time.sleep(SECONDS_PER_SESSION)            # pretend the analysis is long
    done.add(path.stem)
    if progress:
        progress.write_text("\n".join(sorted(done)))   # checkpoint after each session
    n_events = sum(len(e) for e in events)
    responsive = int((response > 0.3).sum())
    print(f"{name}: {n_events} events, {responsive} responsive cells, {time.time() - t0:.1f} s")

print(f"Results written to {out_dir}")

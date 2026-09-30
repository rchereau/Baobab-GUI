"""Regenerates the synthetic demo dataset in demo_data/ (numpy only).

4 sessions x 20 cells, fluorescence sampled at 30 Hz for 60 s, with calcium
transients (fast rise, exponential decay), slow baseline drift and noise.
Cells 1-8 respond to the stimulus. Same seed -> same files.
"""
import json
from pathlib import Path
import numpy as np

FS, DURATION, N_CELLS, N_SESSIONS = 30.0, 60.0, 20, 4
out = Path(__file__).parent / "demo_data"
out.mkdir(exist_ok=True)
rng = np.random.default_rng(2026)
t = np.arange(0, DURATION, 1 / FS)
kernel_t = np.arange(0, 3, 1 / FS)
kernel = (1 - np.exp(-kernel_t / 0.05)) * np.exp(-kernel_t / 0.6)   # GCaMP-like transient

onsets = np.arange(5.0, DURATION - 5, 8.0)                           # stimulus every 8 s
for s in range(1, N_SESSIONS + 1):
    traces = np.empty((t.size, N_CELLS))
    for c in range(N_CELLS):
        spikes = (rng.random(t.size) < 0.15 / FS).astype(float)          # ~0.15 Hz spontaneous
        if c < 8:                                                        # responsive cells
            for on in onsets:
                if rng.random() < 0.8:
                    spikes[int((on + rng.uniform(0.1, 0.3)) * FS)] += rng.uniform(1.5, 3)
        calcium = np.convolve(spikes, kernel)[: t.size]
        f0 = rng.uniform(200, 800)
        drift = 1 + 0.03 * np.sin(2 * np.pi * t / rng.uniform(40, 90) + rng.uniform(0, 6))
        traces[:, c] = f0 * drift * (1 + 0.6 * calcium) + rng.normal(0, 0.02 * f0, t.size)
    header = "time_s," + ",".join(f"cell_{c + 1:02d}" for c in range(N_CELLS))
    np.savetxt(out / f"session_{s:02d}.csv", np.column_stack([t, traces]), delimiter=",",
               header=header, comments="", fmt="%.4f")
np.savetxt(out / "stimulus_onsets.csv", onsets, header="onset_s", comments="", fmt="%.2f")
(out / "info.json").write_text(json.dumps({
    "description": "Synthetic calcium-imaging-like traces for testing Baobab HPC",
    "sampling_rate_hz": FS, "duration_s": DURATION, "n_cells": N_CELLS,
    "n_sessions": N_SESSIONS, "responsive_cells": list(range(1, 9)),
    "files": [f"session_{s:02d}.csv" for s in range(1, N_SESSIONS + 1)] + ["stimulus_onsets.csv"],
}, indent=2))
print("demo data written to", out)

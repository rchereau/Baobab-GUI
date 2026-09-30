"""Small calcium-imaging helpers used by demo_python.py."""
import numpy as np


def delta_f_over_f(traces: np.ndarray, percentile: float = 10) -> np.ndarray:
    """dF/F per cell, with F0 = a low percentile of each trace."""
    f0 = np.percentile(traces, percentile, axis=0)
    return (traces - f0) / f0


def detect_events(dff: np.ndarray, fs: float, k: float = 4.0, refractory_s: float = 0.5):
    """Upward threshold crossings above median + k * MAD; returns one index array per cell."""
    med = np.median(dff, axis=0)
    mad = np.median(np.abs(dff - med), axis=0) * 1.4826
    above = dff > med + k * mad
    refractory = int(refractory_s * fs)
    events = []
    for c in range(dff.shape[1]):
        onsets = np.flatnonzero(above[1:, c] & ~above[:-1, c]) + 1
        kept, last = [], -refractory
        for i in onsets:
            if i - last >= refractory:
                kept.append(i)
                last = i
        events.append(np.array(kept, dtype=int))
    return events


def triggered_average(dff: np.ndarray, t: np.ndarray, onsets, pre_s=1.0, post_s=3.0):
    """Stimulus-triggered average: (time axis, mean response [time x cell])."""
    fs = 1 / np.median(np.diff(t))
    pre, post = int(pre_s * fs), int(post_s * fs)
    snippets = []
    for on in onsets:
        i = int(np.searchsorted(t, on))
        if i - pre >= 0 and i + post <= len(t):
            snippets.append(dff[i - pre:i + post])
    axis = np.arange(-pre, post) / fs
    return axis, np.mean(snippets, axis=0)

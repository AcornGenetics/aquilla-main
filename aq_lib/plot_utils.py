import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from aq_curve.curve import Curve
from aq_curve.pcr_curve_helpers import get_curve_data


def _smooth_curve(values: np.ndarray, window: int = 3) -> np.ndarray:
    if window <= 1:
        return values
    window = min(window, len(values))
    if window <= 1:
        return values
    kernel = np.ones(window) / float(window)
    pad = window // 2
    if pad == 0:
        return np.convolve(values, kernel, mode="same")
    padded = np.pad(values, (pad, pad), mode="edge")
    smoothed = np.convolve(padded, kernel, mode="valid")
    return smoothed[: len(values)]


def _trim_edges(values: np.ndarray, window: int) -> tuple[np.ndarray, int]:
    pad = window // 2
    if pad == 0 or len(values) <= pad * 2:
        return values, 0
    return values[pad:-pad], pad


def generate_optics_plot(optics_path: str, output_path: str, labels: dict | None = None) -> None:
    curve = Curve()
    fig, ax = plt.subplots(figsize=(6, 3))
    labels = labels or {}
    fam_label = labels.get("fam") or "FAM"
    rox_label = labels.get("rox") or "ROX"
    smooth_window = 3
    max_cycle = None

    for index in range(4):
        x_fam, fam_curve, _ = get_curve_data(curve, optics_path, "fam", index + 1)
        x_rox, rox_curve, _ = get_curve_data(curve, optics_path, "rox", index + 1)
        fam_curve = _smooth_curve(fam_curve, window=smooth_window)
        rox_curve = _smooth_curve(rox_curve, window=smooth_window)
        fam_curve, fam_offset = _trim_edges(fam_curve, smooth_window)
        rox_curve, rox_offset = _trim_edges(rox_curve, smooth_window)
        x_fam = x_fam[fam_offset:fam_offset + len(fam_curve)]
        x_rox = x_rox[rox_offset:rox_offset + len(rox_curve)]
        fam_curve = np.clip(fam_curve, 1e-2, None)
        rox_curve = np.clip(rox_curve, 1e-2, None)
        ax.plot(x_fam, fam_curve, label=f"{fam_label} {index + 1}")
        ax.plot(x_rox, rox_curve, label=f"{rox_label} {index + 1}")
        if len(x_fam):
            max_cycle = float(x_fam[-1]) if max_cycle is None else max(max_cycle, float(x_fam[-1]))
        if len(x_rox):
            max_cycle = float(x_rox[-1]) if max_cycle is None else max(max_cycle, float(x_rox[-1]))

    ax.set_xlabel("Cycle")
    ax.set_ylabel("log ΔRn (mV)")
    ax.set_yscale("log")
    ax.set_ylim(bottom=1e-2)
    if max_cycle is not None:
        max_cycle = min(max_cycle, 35)
        ax.set_xlim(left=0, right=max_cycle)
        ax.margins(x=0)
    ax.grid(True, alpha=0.2)
    ax.legend(ncol=2, fontsize=6, frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

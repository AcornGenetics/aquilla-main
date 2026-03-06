import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from aq_curve.curve import Curve


def generate_optics_plot(optics_path: str, output_path: str, labels: dict | None = None) -> None:
    curve = Curve()
    fig, ax = plt.subplots(figsize=(6, 3))
    labels = labels or {}
    fam_label = labels.get("fam") or "FAM"
    rox_label = labels.get("rox") or "ROX"

    for index in range(4):
        fam_curve = curve.get_curve(optics_path, "fam", index + 1)
        rox_curve = curve.get_curve(optics_path, "rox", index + 1)
        x_fam = np.arange(len(fam_curve))
        x_rox = np.arange(len(rox_curve))
        fam_curve = np.clip(fam_curve, 1e-2, None)
        rox_curve = np.clip(rox_curve, 1e-2, None)
        ax.plot(x_fam, fam_curve, label=f"{fam_label} {index + 1}")
        ax.plot(x_rox, rox_curve, label=f"{rox_label} {index + 1}")

    ax.set_xlabel("Cycle")
    ax.set_ylabel("log ΔRn (mV)")
    ax.set_yscale("log")
    ax.set_ylim(bottom=1e-2)
    ax.grid(True, alpha=0.2)
    ax.legend(ncol=2, fontsize=6, frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

import matplotlib

matplotlib.use("Agg")

import matplotlib.pyplot as plt
import numpy as np

from aq_curve.curve import Curve


def generate_optics_plot(optics_path: str, output_path: str) -> None:
    curve = Curve()
    fig, ax = plt.subplots(figsize=(6, 3))

    for index in range(4):
        fam_curve = curve.get_curve(optics_path, "fam", index + 1)
        rox_curve = curve.get_curve(optics_path, "rox", index + 1)
        x_fam = np.arange(len(fam_curve))
        x_rox = np.arange(len(rox_curve))
        ax.plot(x_fam, fam_curve, label=f"FAM {index + 1}")
        ax.plot(x_rox, rox_curve, label=f"ROX {index + 1}")

    ax.set_xlabel("Cycle")
    ax.set_ylabel("V/mV")
    ax.grid(True, alpha=0.2)
    ax.legend(ncol=2, fontsize=6, frameon=False)
    fig.tight_layout()
    fig.savefig(output_path, dpi=150)
    plt.close(fig)

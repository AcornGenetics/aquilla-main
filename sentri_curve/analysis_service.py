"""
AnalysisService — public entry point for the Analysis bounded context.

Callers (Web API, Run Orchestrator) use this class instead of importing
Curve or generate_optics_plot directly, keeping the Analysis domain
boundary clean.
"""
from pathlib import Path

from sentri_curve.curve import Curve
from sentri_curve.plot_utils import generate_optics_plot


class AnalysisService:

    def __init__(self, results_dir: str | Path) -> None:
        self._results_dir = str(results_dir)

    def process_run(
        self,
        optics_path: str,
        results_filename: str,
        plot_path: str,
        labels: dict | None = None,
        rox_unavailable: bool = False,
    ) -> None:
        """Generate results JSON and optics plot from a completed run log."""
        curve = Curve(src_basedir=self._results_dir)
        curve.results_to_json(optics_path, results_filename, rox_unavailable=rox_unavailable)
        generate_optics_plot(optics_path, plot_path, labels=labels)

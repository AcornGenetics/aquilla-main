from statistics import mean
import numpy
import os
import json
import logging
from pathlib import Path
from aq_curve.evaluator import evaluate_curve
from aq_curve import pcr_curve_config as config
from aq_curve.pcr_curve_helpers import compute_cq, get_curve_data, get_threshold
from config import get_src_basedir

logger = logging.getLogger("aquila")


class Curve:
    """
    Unified PCR curve processing class.
    Consolidates data extraction, baseline correction, cross-talk correction, and detection.
    """

    DEFAULT_CROSS_TALK_MATRIX = [
        [
            [1, -0.1],
            [0, 1]
        ],
        [
            [1, -0.1],
            [0, 1]
        ],
        [
            [1, -0.1],
            [0, 1]
        ],
        [
            [1, -0.1],
            [0, 1]
        ],
    ]

    DEFAULT_THRESHOLDS = [
        [0.2, 0.2],
        [0.2, 0.2],
        [0.2, 0.2],
        [0.2, 0.2],
    ]

    def __init__(
        self,
        src_basedir=None,
        cross_talk_matrix=None,
        thresholds=None,
        baseline_slice=(5, 15),
    ):
        self.src_basedir = src_basedir if src_basedir is not None else get_src_basedir()
        self.cross_talk_matrix = cross_talk_matrix if cross_talk_matrix is not None else self.DEFAULT_CROSS_TALK_MATRIX
        self.thresholds = thresholds if thresholds is not None else self.DEFAULT_THRESHOLDS
        self.baseline_slice = baseline_slice
        self.test_run = False

    @staticmethod
    def _reject_outliers(data, m=2.0):
        d = numpy.abs(data - numpy.median(data))
        mdev = numpy.median(d)
        s = d / mdev if mdev else numpy.zeros(len(d))
        return data[s < m]

    def _load_data(self, fname):
        with open(os.path.join(self.src_basedir, fname), "r") as fp:
            for i in range(1):
                next(fp)
            data = [line.split() for line in fp]
            return data[:-1]

    def extract_data(self, logfilename, dye, well):
        data = self._load_data(logfilename)
        dye_subdata = [d for d in data if d[4] == dye]

        if dye == "fam":
            dpos = 1
        elif dye == "rox":
            dpos = -1

        position = well + dpos

        sub_data = [d for n, d in enumerate(dye_subdata) if ((n % 10) > 5)]
        max_cycle = max([int(d[5]) for d in sub_data])
        y0 = [0] * max_cycle
        y1 = [0] * max_cycle
        xdata = list(range(1, max_cycle + 1))

        for cycle in range(max_cycle):
            sub_data2 = [d for d in sub_data if (int(d[5]) == cycle + 1) and (int(d[6]) == position)]

            try:
                # fluorescence value is in col2. 
                # On off designator is in col 3. 
                y0_valid = self._reject_outliers(numpy.array([float(d[2]) for d in sub_data2 if (int(d[3]) == 0)]))
                y0[cycle] = mean(y0_valid)
                y1_valid = self._reject_outliers(numpy.array([float(d[2]) for d in sub_data2 if (int(d[3]) == 1)]))
                y1[cycle] = mean(y1_valid)
            except ZeroDivisionError:
                continue
        return (xdata, y0, y1,)

    def baseline(self, xdata, ydata):
        """
        Calculate baseline for a curve.
        Fits a line to cycles in baseline_slice, filters outliers, then refits.
        """
        xdata = numpy.array(xdata)
        ydata = numpy.array(ydata)

        if len(xdata) < 2:
            self.test_run = True
            return numpy.array([0.0, float(ydata[0]) if len(ydata) else 0.0])

        start, end = self.baseline_slice
        start = max(0, min(start, len(xdata) - 1))
        end = max(start + 1, min(end, len(xdata)))
        if end - start < 2:
            self.test_run = True
            start = 0
            end = min(2, len(xdata))
        # Linear fit on baseline window
        coeffs = numpy.polyfit(xdata[start:end], ydata[start:end], 1)

        # Error across all data
        err = ydata - coeffs[0] * xdata - coeffs[1]
        std_dev = numpy.std(err)

        # Filter out outliers (keep points within 2 std dev)
        mask = numpy.abs(err) < 2 * std_dev

        # Refit using filtered points within the baseline window
        baseline_mask = numpy.zeros(len(xdata), dtype=bool)
        baseline_mask[start:end] = True
        combined_mask = mask & baseline_mask

        if numpy.sum(combined_mask) >= 2:
            filtered_coeffs = numpy.polyfit(xdata[combined_mask], ydata[combined_mask], 1)
        else:
            # Fallback to original fit if too few points remain
            filtered_coeffs = coeffs

        return filtered_coeffs

    @staticmethod
    def _matrix_mul(matrix, vector):
        return (
            vector[0] * matrix[0][0] + vector[1] * matrix[0][1],
            vector[0] * matrix[1][0] + vector[1] * matrix[1][1],
        )

    def get_curve(self, run_id, dye, channel):
        xdata, y0, y1 = self.extract_data(run_id, dye, channel)
        xdata = numpy.array(xdata)
        if len(xdata) < 20:
            self.test_run = True
        coeffs = self.baseline(xdata, y1)
        y_baseline_corrected = y1 - coeffs[0] * xdata - coeffs[1]

        return y_baseline_corrected

    def is_detected(self, run_id, well):
        try:
            curve1 = self.get_curve(run_id, "fam", well)
            curve2 = self.get_curve(run_id, "rox", well)

            z1, z2 = self._matrix_mul(
                self.cross_talk_matrix[well - 1],
                (curve1[-1], curve2[-1],)
            )

            th = self.thresholds[well - 1]

            return (
                z1 >= th[0],
                z2 >= th[1],
            )
        except Exception as e:
            print("Error")
            logging.error(e)
            raise e

    def results_to_json(self, raw_logfile, results_logfile):
        self.test_run = False
        src = raw_logfile
        # Previous endpoint-based detection (kept for reference):
        # detections = {well: self.is_detected(src, well) for well in range(1, 5)}
        #
        # def resolve_status(dye_index, dye_name, well):
        #     evaluation = evaluate_curve(self, src, dye_name, well)
        #     status = evaluation["status"]
        #     if status == "detected":
        #         detected = detections[well][dye_index]
        #         return "Detected" if detected else "Not Detected"
        #     if status == "undetected":
        #         return "Not Detected"
        #     return "Inconclusive"

        def resolve_status(_, dye_name, well):
            evaluation = evaluate_curve(self, src, dye_name, well)
            status = evaluation["status"]
            if status == "detected":
                return "Detected"
            if status == "undetected":
                return "Not Detected"
            return "Inconclusive"

        def resolve_cq(dye_name, well):
            xdata, y_corrected, _ = get_curve_data(self, src, dye_name, well)
            threshold, _ = get_threshold(y_corrected, self.baseline_slice)
            min_consecutive = config.get_int("PCR_SUSTAINED_CYCLES")
            cq = compute_cq(xdata, y_corrected, threshold, min_consecutive)
            if cq is None:
                return None
            return round(float(cq), 2)

        result = {
            "1": {
                "1": resolve_status(0, "fam", 1),
                "2": resolve_status(0, "fam", 2),
                "3": resolve_status(0, "fam", 3),
                "4": resolve_status(0, "fam", 4),
            },
            "2": {
                "1": resolve_status(1, "rox", 1),
                "2": resolve_status(1, "rox", 2),
                "3": resolve_status(1, "rox", 3),
                "4": resolve_status(1, "rox", 4),
            }
        }

        result["cq"] = {
            "1": {
                "1": resolve_cq("fam", 1),
                "2": resolve_cq("fam", 2),
                "3": resolve_cq("fam", 3),
                "4": resolve_cq("fam", 4),
            },
            "2": {
                "1": resolve_cq("rox", 1),
                "2": resolve_cq("rox", 2),
                "3": resolve_cq("rox", 3),
                "4": resolve_cq("rox", 4),
            }
        }

        base_dir = Path(self.src_basedir).resolve()
        target_path = (base_dir / results_logfile).resolve()
        if base_dir != target_path and base_dir not in target_path.parents:
            raise ValueError("results_logfile must stay within src_basedir")

        if self.test_run:
            result["test"] = True

        with open(target_path, "w") as f:
            json.dump(result, f)

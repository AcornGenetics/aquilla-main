import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os
from pathlib import Path
from config import get_src_basedir

from aq_curve.curve import Curve
from aq_curve.pcr_curve_helpers import get_curve_data

# root_dir = Path("/home/pi/aquilla-main/logs/optics")
root_dir = Path(get_src_basedir()) / "logs" / "optics"

get_curve_dir = "logs/optics/"

# Initialize Curve instance
curve = Curve()

selected_logs = None

st.write("# PCR Plot - SN02")


logs = sorted ( os.listdir ( root_dir ), reverse = True)
selected_logs = st.selectbox("Select PCR log to plot", logs)
    
if selected_logs is not None:

    def _max_cycle_from_log(log_path: str) -> int | None:
        max_cycle = None
        try:
            with open(log_path, "r") as handle:
                for line in handle:
                    if line.startswith("#"):
                        continue
                    parts = line.split()
                    if len(parts) <= 5:
                        continue
                    try:
                        cycle = int(parts[5])
                    except ValueError:
                        continue
                    if cycle <= 0:
                        continue
                    max_cycle = cycle if max_cycle is None else max(max_cycle, cycle)
        except OSError:
            return None
        return max_cycle

    x_cols = "V/mV"
    y_cols  =[ "Cycle" ]

    if st.button("Plot the graph"):
        fig,ax = plt.subplots()
        fam_array = []
        rox_array = []
        new_dir = os.path.join(get_curve_dir, selected_logs)
        max_cycle = _max_cycle_from_log(new_dir)
        for i in range ( 4 ):
            xdata_fam, ydata_fam, _ = get_curve_data(curve, new_dir, "fam", i + 1)
            xdata_rox, ydata_rox, _ = get_curve_data(curve, new_dir, "rox", i + 1)
            fam_array.append((xdata_fam, ydata_fam))
            rox_array.append((xdata_rox, ydata_rox))
             
        for index, (xdata, ydata) in enumerate(fam_array):
            #st.write(a)
            ax.plot(xdata, ydata, label= f"FAM {index + 1}" )
        
        for index, (xdata, ydata) in enumerate(rox_array):
            #st.write(a)
            ax.plot(xdata, ydata, label= f"ROX {index + 1}" )

        ax.set_xlabel("Cycle")
        ax.set_ylabel("V/mV")
        ax.set_title(f"{selected_logs}")
        ax.grid(True)
        ax.legend()
        if max_cycle is not None:
            ax.set_xlim(left=0, right=max_cycle)
            ax.margins(x=0)
        #plt.legend(selected_logs, loc = "center", bbox_to_anchor = (1,.85))

        st.pyplot(fig)

    else:
        st.write("Waiting on selection...")
else: 
    st.write("Select a dock to proceed")

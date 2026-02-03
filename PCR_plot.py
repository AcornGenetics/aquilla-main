import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import numpy as np
import os

from aq_curve.main import get_curve

root_dir = "/home/pi/aquila/logs/optics"

get_curve_dir = "logs/optics/"

selected_logs = None

st.write("# PCR Plot - SN02")


logs = sorted ( os.listdir ( root_dir ), reverse = True)
selected_logs = st.selectbox("Select PCR log to plot", logs)
    
if selected_logs is not None:

    x_cols = "V/mV"
    y_cols  =[ "Cycle" ]

    if st.button("Plot the graph"):
        fig,ax = plt.subplots()
        fam_array = []
        rox_array = []
        new_dir = os.path.join(get_curve_dir, selected_logs)
        for i in range ( 4 ):
            curve1 = get_curve( new_dir, "fam", i + 1 )
            curve2 = get_curve( new_dir, "rox", i + 1 )
            fam_array.append(curve1)
            rox_array.append(curve2)
             
        for index, a in enumerate(fam_array):
            #st.write(a)
            x = np.arange(len(a))
            ax.plot(x, a, label= f"FAM {index + 1}" )
        
        for index, a in enumerate(rox_array):
            #st.write(a)
            x = np.arange(len(a))
            ax.plot(x, a, label= f"ROX {index + 1}" )

        ax.set_xlabel("Cycle")
        ax.set_ylabel("V/mV")
        ax.set_title(f"{selected_logs}")
        ax.grid(True)
        ax.legend()
        #plt.legend(selected_logs, loc = "center", bbox_to_anchor = (1,.85))

        st.pyplot(fig)

    else:
        st.write("Waiting on selection...")
else: 
    st.write("Select a dock to proceed")


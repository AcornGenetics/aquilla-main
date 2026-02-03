import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os

#root_dir = "/home/pi/server/dock1/stc_logs"
root_dir = "/home/pi/Server"

new_dir = ""

st.write("# Pressure Plot Overlay in PSI")



docks = [ "Select Dock", "dock1" , "dock2" , "dock3", "dock4", "dock5" ]


def select_dock(new_dir, docks, logs):
    selected_dock = st.selectbox( "Select a Dock", docks )
    new_dir = os.path.join(root_dir, selected_dock, logs)
    return selected_dock, new_dir

logs = "pressure_logs"

selected_dock, new_dir = select_dock(new_dir,docks,logs)

if selected_dock != "Select Dock":
    logs = sorted ( os.listdir ( new_dir ), reverse = True)
    st.markdown("""
        <style>
            .stMultiSelect [data-baseweb=select] span{
                max-width: 250px;
                font-size: 0.6rem;
            }
        </style>
        """, unsafe_allow_html=True)
    selected_logs = st.multiselect("Select Files To Overlay", logs)
    
    #TODO Add functionality to select multiple graphs
    #and overlay them. 

    #TODO select and deselect columns
    # this will all probably have to be done in pyplot

    #min_row = st.number_input("Start time", min_value=0, value=0, step=1)
    #max_row = st.number_input("End time", min_value=min_row + 1, value=10000, step=1)
    
    if new_dir != "":

        x_cols = "Time"
        y_cols  =[ "Pressure (PSI)" ]

        if "min_row" not in st.session_state:
            st.session_state.min_row = 0
        if "max_row" not in st.session_state:
            st.session_state.max_row = 10000

        with st.form("plot_form"):
            st.session_state.min_row = st.number_input(
                    "Start time",
                    min_value=0,
                    value=st.session_state.min_row,
                    step=1,
                    key="min_row_input"
            )
            
            st.session_state.max_row = st.number_input(
                    "End time",
                    min_value=st.session_state.min_row + 1,
                    value=st.session_state.max_row,
                    step=1,
                    key="max_row_input"
            )
            plot_button = st.form_submit_button("Plot the graph")

        if plot_button:
            fig,ax = plt.subplots()
             
            for logs in selected_logs:
                new_dir = os.path.join(new_dir, logs)
                df = pd.read_csv(new_dir, 
                                 sep=r"\s+",
                                 engine="python",
                                 quotechar='"',
                                 header=None,
                                 skiprows=3,
                                 usecols=[1,4],
                                 on_bad_lines="skip")

                df.columns = ["Time", "Pressure (PSI)"]

                min_row = st.session_state.min_row
                max_row = st.session_state.max_row
                df = df.iloc[int(min_row * 2):int(max_row * 2)]

                for col in y_cols:
                    ax.plot(df[x_cols], df[col],label=col)
                new_dir = os.path.dirname(new_dir)

            ax.set_xlabel("Time")
            ax.set_ylabel("Pressure (PSI)")
            ax.set_title("Pressure Overlay")
            plt.legend(selected_logs, loc = "center", bbox_to_anchor = (1,.85))

            st.pyplot(fig)

        else:
            st.write("Waiting on selection...")
    else: 
        st.write("Select a dock to proceed")


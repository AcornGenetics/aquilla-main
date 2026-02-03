import streamlit as st
import streamlit as st
import pandas as pd
import matplotlib.pyplot as plt
import os

#root_dir = "/home/pi/server/dock1/stc_logs"
root_dir = "/home/pi/Server"

new_dir = ""

st.write("# TEST ONLY")


docks = [ "Select Dock", "dock1" , "dock2" , "dock3", "dock4", "dock5" ]


def select_dock(new_dir, docks, logs):
    selected_dock = st.selectbox( "Select a Dock", docks )
    new_dir = os.path.join(root_dir, selected_dock, logs)
    return selected_dock, new_dir

logs = "pcr_data"

selected_dock, new_dir = select_dock(new_dir,docks,logs)

if selected_dock != "Select Dock":
    stc_logs = sorted ( os.listdir ( new_dir ), reverse = True)
    st.markdown("""
        <style>
            .stMultiSelect [data-baseweb=select] span{
                max-width: 250px;
                font-size: 0.6rem;
            }
        </style>
        """, unsafe_allow_html=True)
    selected_logs = st.multiselect("Select Files To Overlay", stc_logs)
    
    #TODO Add functionality to select multiple graphs
    #and overlay them. 

    #TODO select and deselect columns
    # this will all probably have to be done in pyplot

    if new_dir != "":

     

        x_cols = "Time"
        y_cols  =[ "All",
                    "Actual TEC Temp",
                    "Target TEC Temp", 
                    "Actual Ouput Current",
                    "Actual Output Voltage"]
        selected_y_cols = st.multiselect("Select Y-columns", y_cols)
        
        if st.button("Plot the graph"):
            fig,ax = plt.subplots()
            
            if selected_y_cols[0] ==  "All":
                y_cols = [ "Actual TEC Temp",
                            "Target TEC Temp", 
                            "Actual Ouput Current",
                            "Actual Output Voltage"]
            elif selected_y_cols != "All":
                y_cols = selected_y_cols
            elif "All" in selected_y_cols:
                remove_value_all = [k for k, v in selected_y_cols.items() if v =="All"]
                if remove_value_all:
                    selected_y_cols.pop(remove_value_all[0])
            
            for logs in selected_logs:
                new_dir = os.path.join(new_dir, logs)
                df = pd.read_csv(new_dir, 
                                 sep=r"\s+",
                                 engine="python",
                                 quotechar='"',
                                 header=None,
                                 skiprows=2,
                                 usecols=[0,1,5,7,9],
                                 on_bad_lines="skip")

                df.columns = ["Time", 
                          "Actual TEC Temp",
                          "Target TEC Temp", 
                          "Actual Ouput Current",
                          "Actual Output Voltage"]

                for col in y_cols:
                    ax.plot(df[x_cols], df[col],label=col)
                new_dir = os.path.dirname(new_dir)

            ax.set_xlabel("Time")
            ax.set_ylabel("Temp (Celsius)")
            ax.set_title(selected_y_cols)
            plt.legend(selected_logs)

            st.pyplot(fig)

        else:
            st.write("Waiting on selection...")
    else: 
        st.write("Select a dock to proceed")


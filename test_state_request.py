import time
import aq_lib.state_requests as sr
from aq_lib.utils import LogFileName 

#sr.send_state_request(state = "1")

def button_logic(state = "ready"):
    ret = sr.wait_for_button()
    
    if(state == "end"):
        screens = ["8","3","9","1"]
    elif(state == "ready"):
        screens = ["6","1","7","4"]    

    while True:
        run = ret.get("run_requested")
        profile = ret.get("profile")
        drawer_open = ret.get("drawer_open_status")
        drawer_close = ret.get("drawer_close_status")
        exit_status = ret.get("exit_button_status")
        print("run: %s, pro: %s, open: %s, close %s, exit: %s" % (run, profile, drawer_open, drawer_close, exit_status))
        if( run == True and profile is not None ):
            break
        elif( drawer_open == True and drawer_close == False ):
            sr.change_screen( screens[0] )
            #self.drawer.open()
            time.sleep(5) #simulate drawer opening
            sr.change_screen( screens[1] ) 
            ret = sr.wait_for_button()
        elif( drawer_open == False and drawer_close == True ): 
            sr.change_screen( screens[2] )
            #self.drawer.read()
            time.sleep(5) #simulate drawer close
            sr.change_screen( screens[1] ) 
            ret = sr.wait_for_button()
        elif( run == True and profile == None ):
            sr.change_screen( screens[3] )
            if( state == "ready" ): 
                ret = sr.wait_for_button()
            elif( state == "end" ):
                break
        elif( exit_status is True ):
            ret = sr.wait_for_button()
            if(ret.get("exit_button_status")):
                ret = sr.wait_for_button()
                if(ret.get("exit_button_status")):
                    #TODO add something to close GUI
                    print("Add logic to exit out of gui")
                    sr.change_screen("-4")
                    exit(1)
                else:
                    pass
            else:
                pass

#lfn = LogFileName()
#path = lfn.get_results_json_filename()
sr.change_screen("0")
time.sleep(5)
sr.change_screen("1")
while True:
    button_logic( state = "ready" ) 
    sr.change_screen("2")
    time.sleep(1)
    sr.timer_control( status = "start" )
    time.sleep(5)
    sr.timer_control( "stop" )
    time.sleep(2)
    sr.timer_control( "reset" )
    #path = "logs/results/results.json"
    path = "logs/results/results_2.json"
    sr.update_results_path(path)
    time.sleep(1)
    sr.change_screen("3")
    button_logic( state = "end" ) 






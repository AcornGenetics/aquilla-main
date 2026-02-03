import sys
import numpy
import json
import os
import logging

from aq_curve.calculate import extract_data 
from aq_curve.calculate import baseline 

logger = logging.getLogger("aquila")

src_basedir = "/home/pi/aquila/"

def matrix_mul( Matrix, vector ):

    return (
        vector[0] * Matrix[0][0]  + vector[1] * Matrix[0][1] ,
        vector[0] * Matrix[1][0]  + vector[1] * Matrix[1][1] ,
        )

cross_talk_matrix = [
    [
        [ 1, -0.1],
        [ 0,    1]
    ],
    [
        [ 1, -0.1],
        [ 0,    1]
    ],
    [
        [ 1, -0.1],
        [ 0,    1]
    ],
    [
        [ 1, -0.1],
        [ 0,    1]
    ],
]

thresholds = [
    [2,1,],
    [2,1,],
    [2,1,],
    [2,1,],
]

def get_curve( run_id, dye, channel ):
    xdata, y0, y1 = extract_data( src_basedir, run_id, dye, channel )
    xdata = numpy.array ( xdata )
    if len ( xdata ) < 20:
        raise Exception("PCR curve too short")
    coeffs = baseline ( xdata, y1 )
    y_baseline_corrected = y1 - coeffs[0]*xdata - coeffs[1]

    return y_baseline_corrected

def is_detected( run_id, well ):
    try:
        curve1 = get_curve( run_id, "fam", well )
        curve2 = get_curve( run_id, "rox", well )

        z1,z2 = matrix_mul ( 
                        cross_talk_matrix[ well-1 ], 
                        (curve1[-1], curve2[-1],) 
        )

        th = thresholds[ well-1 ]

        return (
            z1>=th[0],
            z2>=th[1],
        )
    except Exception as e:
        print ( "Error" )
        logging.error ( e )
        raise e 
        return ( False, False, )

            

def results_to_json( raw_logfile, results_logfile ):

    #src = sys.argv[1]
    src = raw_logfile

    a = is_detected( src, 1 )
    b = is_detected( src, 2 )
    c = is_detected( src, 3 )
    d = is_detected( src, 4 )

    result = {
        "1":{
            "1":"Detected" if a[0] else "Not Detected",
            "2":"Detected" if b[0] else "Not Detected",
            "3":"Detected" if c[0] else "Not Detected",
            "4":"Detected" if d[0] else "Not Detected",
            },
        "2":{
            "1":"Detected" if a[1] else "Not Detected",
            "2":"Detected" if b[1] else "Not Detected",
            "3":"Detected" if c[1] else "Not Detected",
            "4":"Detected" if d[1] else "Not Detected",
            }
        }
    
    fp = os.path.join("/home/pi/aquila", results_logfile)
    with open( fp, "w") as f:
        json.dump( result, f )
    #print ( result )


if __name__ == "__main__":
    main()

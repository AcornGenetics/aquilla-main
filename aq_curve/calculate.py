from statistics import mean, stdev
import numpy
import os

def reject_outliers(data, m = 2.):
    d = numpy.abs(data - numpy.median(data))
    mdev = numpy.median(d)
    s = d/mdev if mdev else numpy.zeros(len(d))
    return data[s<m]

def load_data( basedir, fname ):
    with open ( os.path.join ( basedir, fname ), "r" ) as fp:
        for i in range ( 1 ):
            next( fp )
        data = [ line.split() for line in fp ] 
        return data[:-1]

def extract_data( basedir, logfilename, dye, well ):
    
    data = load_data ( basedir, logfilename )
    dye_subdata = [ d for d in data if d[4]==dye ]

    if dye == "fam": dpos = 1
    elif dye == "rox": dpos = -1
    
    position = well + dpos
    
    sub_data = [ d for n,d in enumerate ( dye_subdata ) if ((n%10)>5) ]
    max_cycle = max ( [ int(d[5]) for d in sub_data ] )
    y0 = [0]*max_cycle
    y1 = [0]*max_cycle
    xdata = list ( range( 1, max_cycle+1 ) )
    
    for cycle in range ( max_cycle ):
        sub_data2 = [ d for d in sub_data if (int(d[5])== cycle+1) and (int(d[6])==position) ]
        
        try:
            # fluorescence value is in col2. 
            # On off designator is in col 3. 
            y0_valid = reject_outliers ( numpy.array([ float(d[2]) for d in sub_data2 if  (int(d[3])==0) ] ))
            y0[cycle]  = mean ( y0_valid )
            y1_valid = reject_outliers ( numpy.array([ float(d[2]) for d in sub_data2 if  (int(d[3])==1) ] ))
            y1[cycle]  = mean ( y1_valid )
        except ZeroDivisionError:
            continue
    return ( xdata, y0, y1,)


def baseline( xdata, ydata ):

    xdata = numpy.array ( xdata )
    ydata = numpy.array ( ydata )

    coeffs = numpy.polyfit(xdata[5:15], ydata[5:15], 1)

    err = ydata - coeffs[0]*xdata - coeffs[1]
    std_dev = numpy.std ( err )

    filtered_xdata = xdata[  numpy.abs(err) < 2*std_dev ]
    filtered_ydata = ydata[  numpy.abs(err) < 2*std_dev ]
    filtered_coeffs = numpy.polyfit(xdata[5:15], ydata[5:15], 1)
    return filtered_coeffs



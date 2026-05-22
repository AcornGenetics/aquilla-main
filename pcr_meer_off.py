from aq_lib.meerstetter import MeerStetter

meer1091 = (0x0403, 0x6001, 1089 )
device = MeerStetter.find_meer( * meer1091 )

print ( device )


meer = MeerStetter ( device, timeout = 1 )
meer.set_temperature ( 25.0 )

meer.output_stage_enable ( 0 )



exit ( 0 ) 


try:
    meer1161 = (0x0403, 0x6001, 1089 )
    device = MeerStetter.find_meer( * meer1161 )


    meer = MeerStetter ( device, timeout = 1 )

    meer.setTargetObjectTemperature ( 25.0 )
    meer.output_stage_enable ( 0 )
except exception as e:
    print ( e )
    pass

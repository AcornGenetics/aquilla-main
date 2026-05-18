from aq_curve.main import get_curve


ret = get_curve("logs/optics/2025-11-25_16-14-55.log", "fam", 1)

new_dir = "logs/optics/2025-11-25_16-14-55.log" 

fam_array = []
rox_array = []

for i in range ( 4 ):
    curve1 = get_curve( new_dir, "fam", i + 1 )
    curve2 = get_curve( new_dir, "rox", i + 1 )
    
    fam_array.append(curve1)
    rox_array.append(curve2)

print(fam_array)
print(fam_array[2].size)

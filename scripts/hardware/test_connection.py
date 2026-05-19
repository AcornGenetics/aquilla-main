from serial import Serial
import json
import time

iface = Serial(baudrate=115200,port="/dev/ttyS0",timeout=1)

"""data = {
        "id":"1",
        "command":"GET_VERSION",
        "timestamp":1,
        "status":"success",
        "data": {
                "firmware":"Poop",
                "protocol":"In",
                "hardware":"toilet"
                }
        }
data = {
        "firmware":"Poop",
        "protocol":"In",
        "hardware":"toilet"
        }
json_data = json.dumps(data) + '\n'
json_bytes = json_data.encode('utf-8')"""

request = None
request_id = None
while True:
    request = iface.readline()
    print ( request )
    if request: 
        request_id = request.decode()[7:23]
        print(request_id)
        break

string = (f'{{"id":"{request_id}","firmware":"1.0.0","protocol":"1.0.0"}}')
byte_string = string.encode('utf-8')
iface.write(byte_string)
print(byte_string)

while True:
    request = iface.readline()
    print ( request )
    if request: break


import serial, re
ser = serial.Serial('/dev/tty.usbmodem213201',115200)


ser.write("?\n")
ser.write("stream=1\n")
ser.write("format=txt\n")


buf = ''
while True:
    buf += ser.read(ser.in_waiting or 1).decode(errors='ignore')
    if '' in buf:
        lines = buf.split('')
        buf = lines.pop()
        for line in lines:
            m = re.search(r"\{([^}]+)\}", line)
            if m:row = m.group(1).split(',')
            print([float(row[0])] + list(map(int,row[1:])))
from datetime import datetime
import sys

first_time = None

header = sys.argv[1]
time_col = int(sys.argv[2])

print(header)
for line in sys.stdin.readlines()[1:]:
    sp = line.strip().split(" ")
    d = datetime.strptime(sp[time_col], "%H:%M:%S.%f")
    if first_time is None:
        first_time = d
    sp[time_col] = (d - first_time).total_seconds()
    print(*sp)

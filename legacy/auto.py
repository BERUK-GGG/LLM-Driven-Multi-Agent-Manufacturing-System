import json
import time
from pymodbus.client import ModbusTcpClient

client = ModbusTcpClient('127.0.0.1')


def read_input(address):
    result = client.read_holding_registers(address=address, count= 1)
    return result.registers[0]

# --- Modbus Write Functions ---
def write_output(address, value):
    client.write_register(address, value)
    print(f"Wrote {value} to address {address}")

def move_crane(x, y):
    write_output(1, x)  # setX
    write_output(2, y)  # setY
    print(f"Moving crane to X={x}, Y={y}")
    time.sleep(3)

# --- Load JSON File ---
def load_actions(file_path):
    with open(file_path, "r") as f:
        data = json.load(f)
    return data["actions"], data["actions2"]

# --- Execute Actions ---
def execute_actions(actions, pid, type):
    vacuum = 0
    for action in actions:
        if "vacuum" in action:
            write_output(3, action["vacuum"])
            print(f"Vacuum {'ON' if action['vacuum'] == 1 else 'OFF'}")
            vacuum =action['vacuum']
        elif "setX" in action and "setY" in action:
            move_crane(action["setX"], action["setY"])
            log_system.add_entry(pid, type ,action['setX'], action['setY'], vacuum )
        elif "process1" in action:
            write_output(4, action["process1"])
            print(f"Process1 {'running' if action['process1'] == 1 else 'stopped'}")
            time.sleep(3)


        elif "process2" in action:
            write_output(5, action["process2"])
            print(f"Process2 {'running' if action['process2'] == 1 else 'stopped'}")
            time.sleep(3)


        else:
            print(f"Unknown action: {action}")


#        time.sleep(3)


from collections import deque

# --- Queue System ---
class PartQueue:
    def __init__(self):
        self.queue = deque()
        self.next_id = 1

    def add_part(self, part_type):
        part = {"id": self.next_id, "type": part_type, "status": "waiting"}
        self.queue.append(part)
        self.next_id += 1
        print(f"Added part {part['id']} (type {part['type']}) to queue")

    def get_next_part(self):
        if self.queue:
            return self.queue[0]  # peek
        return None

    def complete_part(self):
        if self.queue:
            finished = self.queue.popleft()
            print(f" Completed part {finished['id']} (type {finished['type']})")

import csv
import datetime
import os


class Log:
    def __init__(self, filename="log.csv"):
        self.filename = filename
        # Create file and header if not exists
        if not os.path.exists(self.filename):
            with open(self.filename, "w", newline="") as f:
                writer = csv.writer(f)
                writer.writerow([ "ProductID", "type" ,"Timestamp", "X", "Y", "Vacuum"])

    def add_entry(self, product_id, type , x, y, vacuum):
        timestamp = datetime.datetime.now().strftime("%Y-%m-%d %H:%M:%S")
        with open(self.filename, "a", newline="") as f:
            writer = csv.writer(f)
            writer.writerow([product_id, type ,timestamp, type, x, y, vacuum])
        print(f" Logged: Product {product_id} at X={x}, Y={y}")


if __name__ == "__main__":

    client.connect()
    action1, action2= load_actions("actions.json")

    part_queue = PartQueue()
    log_system = Log()


    print(" Simulation running...")

    while True:
        # Check sensor at Source 1 (address 17)
        source_sensor = read_input(17)

        # Check sensor at Source 2 (address 17)
        source_sensor2 = read_input(18)

        # If new part detected at Source 1 → add to queue
        if source_sensor == 1:
            part_queue.add_part(part_type=1)
            time.sleep(2)  # debounce / prevent double detection
        if source_sensor2 == 1:
            part_queue.add_part(part_type=2)
            time.sleep(2)  # debounce / prevent double detection

        # If crane is idle and queue is not empty → process next part
        next_part = part_queue.get_next_part()
        if next_part:
            if next_part['type'] == 1:
                print(f" Processing part {next_part['id']}...")
                execute_actions(action1, next_part['id'], next_part['type'])
                part_queue.complete_part()
            else:
                print(f" Processing part {next_part['id']}...")
                execute_actions(action2, next_part['id'], next_part['type'] )
                part_queue.complete_part()
        time.sleep(2)
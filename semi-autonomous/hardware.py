"""
Hardware abstraction layer.

All Modbus I/O goes through here. The key safety guarantee lives in safe_move():
the crane ALWAYS rises to TRAVEL_Y before any horizontal movement, enforced in
Python — the LLM cannot bypass it.
"""

import time
from pymodbus.client import ModbusTcpClient
from config import MODBUS_HOST, TRAVEL_Y, MOVE_DELAY

# --- Register map ---
REG_CRANE_X       = 1
REG_CRANE_Y       = 2
REG_VACUUM        = 3
REG_PROCESS1      = 4
REG_PROCESS2      = 5
REG_SENSOR1       = 17
REG_SENSOR2       = 18
REG_PROC1_STATUS  = 19
REG_PROC2_STATUS  = 20

_modbus = ModbusTcpClient(MODBUS_HOST)
_modbus.connect()

# Tracked crane state (write-side only — simulation has no position readback)
_x:      int = 0
_y:      int = TRAVEL_Y
_vacuum: int = 0


def _write(reg: int, val: int) -> None:
    _modbus.write_register(reg, val)
    print(f"  [MODBUS] reg[{reg}] ← {val}")


def _read(reg: int) -> int:
    return _modbus.read_holding_registers(address=reg, count=1).registers[0]


def initialize() -> None:
    """Send crane to travel height on startup to establish a known safe state."""
    global _y
    print("[INIT] Raising crane to travel height...")
    _write(REG_CRANE_Y, TRAVEL_Y)
    _y = TRAVEL_Y
    time.sleep(MOVE_DELAY * 2)
    print("[INIT] Ready.\n")


def safe_move(target_x: int, target_y: int) -> tuple[int, int]:
    """
    Move the crane in three safe steps:
      1. Rise to TRAVEL_Y  (skip if already there)
      2. Move horizontally (skip if already at target_x)
      3. Lower to target_y (skip if target_y == TRAVEL_Y)

    This is intentionally not bypassable by the LLM — the tool always calls
    safe_move regardless of what coordinates were requested.
    """
    global _x, _y

    if _y != TRAVEL_Y:
        print(f"  [SAFETY] Rising from Y={_y} to Y={TRAVEL_Y} before horizontal move")
        _write(REG_CRANE_Y, TRAVEL_Y)
        _y = TRAVEL_Y
        time.sleep(MOVE_DELAY)

    if _x != target_x:
        _write(REG_CRANE_X, target_x)
        _x = target_x
        time.sleep(MOVE_DELAY)

    if target_y != TRAVEL_Y:
        _write(REG_CRANE_Y, target_y)
        _y = target_y
        time.sleep(MOVE_DELAY)

    return _x, _y


def set_vacuum(on: bool) -> None:
    global _vacuum
    val = 1 if on else 0
    _write(REG_VACUUM, val)
    _vacuum = val


def set_process(process_id: int, on: bool) -> None:
    reg = REG_PROCESS1 if process_id == 1 else REG_PROCESS2
    _write(reg, 1 if on else 0)
    time.sleep(MOVE_DELAY)


def read_sensors() -> dict:
    return {
        "source1_sensor":   _read(REG_SENSOR1),
        "source2_sensor":   _read(REG_SENSOR2),
        "process1_running": _read(REG_PROC1_STATUS),
        "process2_running": _read(REG_PROC2_STATUS),
        "crane_x": _x,
        "crane_y": _y,
        "vacuum":  _vacuum,
    }


def get_position() -> tuple[int, int]:
    return _x, _y

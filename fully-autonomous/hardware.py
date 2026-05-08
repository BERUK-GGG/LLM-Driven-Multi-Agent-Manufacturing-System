"""
Async hardware abstraction layer.

Identical register map and safe_move safety logic as the parent project's
hardware.py — only time.sleep → asyncio.sleep and ModbusTcpClient →
AsyncModbusTcpClient. The safety guarantee (always rise to TRAVEL_Y before
horizontal movement) is enforced here in Python, not in the LLM.
"""

import asyncio
from pymodbus.client import AsyncModbusTcpClient
from config import MODBUS_HOST, TRAVEL_Y, MOVE_DELAY

# --- Register map ---
REG_CRANE_X      = 1
REG_CRANE_Y      = 2
REG_VACUUM       = 3
REG_PROCESS1     = 4
REG_PROCESS2     = 5
REG_SENSOR1      = 17
REG_SENSOR2      = 18
REG_PROC1_STATUS = 19
REG_PROC2_STATUS = 20

_modbus: AsyncModbusTcpClient | None = None   # created inside the running event loop

_x:      int = 0
_y:      int = TRAVEL_Y
_vacuum: int = 0


async def _write(reg: int, val: int) -> None:
    await _modbus.write_register(reg, val)
    print(f"  [MODBUS] reg[{reg}] ← {val}")


async def _read(reg: int) -> int:
    result = await _modbus.read_holding_registers(address=reg, count=1)
    return result.registers[0]


async def initialize() -> None:
    """Connect to Modbus and raise crane to travel height for a known safe state."""
    global _modbus, _y
    _modbus = AsyncModbusTcpClient(MODBUS_HOST)   # must be created inside the event loop
    await _modbus.connect()
    print("[INIT] Raising crane to travel height...")
    await _write(REG_CRANE_Y, TRAVEL_Y)
    _y = TRAVEL_Y
    await asyncio.sleep(MOVE_DELAY * 2)
    print("[INIT] Ready.\n")


async def safe_move(target_x: int, target_y: int) -> tuple[int, int]:
    """
    Three-step safe movement — cannot be bypassed by the LLM:
      1. Rise to TRAVEL_Y if not already there
      2. Move horizontally to target_x
      3. Lower to target_y (skipped if target_y == TRAVEL_Y)
    """
    global _x, _y

    if _y != TRAVEL_Y:
        print(f"  [SAFETY] Rising from Y={_y} to Y={TRAVEL_Y} before horizontal move")
        await _write(REG_CRANE_Y, TRAVEL_Y)
        _y = TRAVEL_Y
        await asyncio.sleep(MOVE_DELAY)

    if _x != target_x:
        await _write(REG_CRANE_X, target_x)
        _x = target_x
        await asyncio.sleep(MOVE_DELAY)

    if target_y != TRAVEL_Y:
        await _write(REG_CRANE_Y, target_y)
        _y = target_y
        await asyncio.sleep(MOVE_DELAY)

    return _x, _y


async def set_vacuum(on: bool) -> None:
    global _vacuum
    val = 1 if on else 0
    await _write(REG_VACUUM, val)
    _vacuum = val


async def set_process(process_id: int, on: bool) -> None:
    reg = REG_PROCESS1 if process_id == 1 else REG_PROCESS2
    await _write(reg, 1 if on else 0)


async def read_sensors() -> dict:
    return {
        "source1_sensor":   await _read(REG_SENSOR1),
        "source2_sensor":   await _read(REG_SENSOR2),
        "process1_running": await _read(REG_PROC1_STATUS),
        "process2_running": await _read(REG_PROC2_STATUS),
        "crane_x": _x,
        "crane_y": _y,
        "vacuum":  _vacuum,
    }


def get_position() -> tuple[int, int]:
    return _x, _y

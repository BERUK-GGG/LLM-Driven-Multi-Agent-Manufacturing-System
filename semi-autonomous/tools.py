"""
Tool implementations and OpenAI function-call schema.

Each tool function calls hardware.py. The LLM sees only the schema; Python
enforces the safety constraints (e.g. safe_move always rises before horizontal
travel).
"""

import json
import datetime
import csv
import os

import hardware

# Soft state — sensor cache and log; hardware position lives in hardware.py
state: dict = {
    "source1_sensor":   False,
    "source2_sensor":   False,
    "process1_running": False,
    "process2_running": False,
    "log": [],
}


# --- Tool functions ---

def tool_move_crane(x: int, y: int) -> str:
    cx, cy = hardware.safe_move(x, y)
    return f"Crane at X={cx}, Y={cy}"


def tool_set_vacuum(on: bool) -> str:
    hardware.set_vacuum(on)
    return f"Vacuum {'ON' if on else 'OFF'}"


def tool_set_process(process_id: int, on: bool) -> str:
    hardware.set_process(process_id, on)
    state[f"process{process_id}_running"] = on
    return f"Process {process_id} {'started' if on else 'stopped'}"


def tool_read_sensors() -> str:
    data = hardware.read_sensors()
    state["source1_sensor"]   = bool(data["source1_sensor"])
    state["source2_sensor"]   = bool(data["source2_sensor"])
    state["process1_running"] = bool(data["process1_running"])
    state["process2_running"] = bool(data["process2_running"])
    return json.dumps(data)


def tool_log_action(part_id: int, part_type: int, note: str) -> str:
    cx, cy = hardware.get_position()
    entry = {
        "part_id":   part_id,
        "part_type": part_type,
        "timestamp": datetime.datetime.now().isoformat(),
        "crane_x":   cx,
        "crane_y":   cy,
        "note":      note,
    }
    state["log"].append(entry)
    path = "agent_log.csv"
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=entry.keys())
        if write_header:
            w.writeheader()
        w.writerow(entry)
    return f"Logged: {note}"


# --- OpenAI function-call schema ---

TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "move_crane",
            "description": (
                "Move the crane to a target position. "
                "Safe vertical sequencing is automatic: the crane always rises to "
                "travel height (Y=200) before any horizontal movement. "
                "Specify only the final destination X and Y."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {
                        "type": "integer",
                        "description": (
                            "Target X (mm). Known positions: "
                            "source1=55, source2=158, process1=450, process2=650, output=945"
                        ),
                    },
                    "y": {
                        "type": "integer",
                        "enum": [82, 200],
                        "description": "Target Y: 82=pick/place height, 200=travel/park height",
                    },
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_vacuum",
            "description": "Turn the vacuum gripper on (to pick a part) or off (to release).",
            "parameters": {
                "type": "object",
                "properties": {"on": {"type": "boolean"}},
                "required": ["on"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_process",
            "description": "Start or stop a process machine (1 or 2).",
            "parameters": {
                "type": "object",
                "properties": {
                    "process_id": {"type": "integer", "enum": [1, 2]},
                    "on": {"type": "boolean"},
                },
                "required": ["process_id", "on"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "read_sensors",
            "description": (
                "Read all sensor inputs. Returns source sensors, process machine status, "
                "and current crane position."
            ),
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_action",
            "description": "Record a meaningful event to the CSV log file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "part_id":   {"type": "integer"},
                    "part_type": {"type": "integer"},
                    "note":      {"type": "string"},
                },
                "required": ["part_id", "part_type", "note"],
            },
        },
    },
]


def dispatch_tool(name: str, inputs: dict) -> str:
    match name:
        case "move_crane":   return tool_move_crane(inputs["x"], inputs["y"])
        case "set_vacuum":   return tool_set_vacuum(inputs["on"])
        case "set_process":  return tool_set_process(inputs["process_id"], inputs["on"])
        case "read_sensors": return tool_read_sensors()
        case "log_action":   return tool_log_action(inputs["part_id"], inputs["part_type"], inputs["note"])
        case _:              return f"Unknown tool: {name}"

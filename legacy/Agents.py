"""
Multi-Agent LLM Crane System
============================
Each physical resource becomes its own agent with a focused system prompt.
The Orchestrator reasons about which agent to call and in what order.
Agents talk to Modbus; the Orchestrator talks to agents via a shared state dict.

Uses the OpenAI SDK pointed at NVIDIA's free API endpoint.
Get your key at: https://build.nvidia.com
"""

import json
import time
import datetime
import csv
import os
from openai import OpenAI

client = OpenAI(
    base_url="https://integrate.api.nvidia.com/v1",
    api_key="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",
)

MODEL = "meta/llama-3.1-8b-instruct"

# ---------------------------------------------------------------------------
# Shared state — replaces the hardcoded actions.json
# ---------------------------------------------------------------------------
state = {
    "crane_x": 0,
    "crane_y": 200,
    "vacuum": 0,
    "process1_running": False,
    "process2_running": False,
    "source1_sensor": False,
    "source2_sensor": False,
    "part_queue": [],          # list of {"id": int, "type": 1|2}
    "log": [],
}

# ---------------------------------------------------------------------------
# Modbus stub (swap for real pymodbus calls)
# ---------------------------------------------------------------------------

from pymodbus.client import ModbusTcpClient
_modbus = ModbusTcpClient("127.0.0.1")
_modbus.connect()




def _read_reg(address: int) -> int:

    r = _modbus.read_holding_registers(address=address, count=1)
    return r.registers[0]

def _write_reg(address: int, value: int):
    _modbus.write_register(address, value)
    print(f"  [MODBUS] write reg {address} = {value}")


# ---------------------------------------------------------------------------
# Tool implementations , what the LLM agents will call
# ---------------------------------------------------------------------------

def tool_move_crane(x: int, y: int) -> str:
    _write_reg(1, x)
    _write_reg(2, y)
    state["crane_x"] = x
    state["crane_y"] = y
    time.sleep(0.5)  # reduced for demo; use 3 for real hardware
    return f"Crane moved to X={x}, Y={y}"


def tool_set_vacuum(on: bool) -> str:
    val = 1 if on else 0
    _write_reg(3, val)
    state["vacuum"] = val
    return f"Vacuum {'ON' if on else 'OFF'}"


def tool_set_process(process_id: int, on: bool) -> str:
    addr = 4 if process_id == 1 else 5
    val = 1 if on else 0
    _write_reg(addr, val)
    key = f"process{process_id}_running"
    state[key] = on
    time.sleep(0.5)
    return f"Process {process_id} {'started' if on else 'stopped'}"


def tool_read_sensors() -> str:
    s1 = _read_reg(17)
    s2 = _read_reg(18)
    p1_running = _read_reg(19)
    p2_running = _read_reg(20)
    state["source1_sensor"] = bool(s1)
    state["source2_sensor"] = bool(s2)
    state["process1_running"] = bool(p1_running)
    state["process2_running"] = bool(p2_running)
    return json.dumps({
        "source1_sensor": s1,
        "source2_sensor": s2,
        "process1_isRunning": p1_running,
        "process2_isRunning": p2_running,
        "crane_x": state["crane_x"],
        "crane_y": state["crane_y"],
        "vacuum": state["vacuum"],
    })


def tool_log_action(part_id: int, part_type: int, note: str) -> str:
    entry = {
        "part_id": part_id,
        "part_type": part_type,
        "timestamp": datetime.datetime.now().isoformat(),
        "crane_x": state["crane_x"],
        "crane_y": state["crane_y"],
        "vacuum": state["vacuum"],
        "note": note,
    }
    state["log"].append(entry)
    # Also write to CSV
    path = "agent_log.csv"
    write_header = not os.path.exists(path)
    with open(path, "a", newline="") as f:
        w = csv.DictWriter(f, fieldnames=entry.keys())
        if write_header:
            w.writeheader()
        w.writerow(entry)
    return f"Logged: {note}"


# ---------------------------------------------------------------------------
# Tool schema — OpenAI function-calling format
# ---------------------------------------------------------------------------
TOOLS = [
    {
        "type": "function",
        "function": {
            "name": "move_crane",
            "description": "Move the crane to an absolute X/Y position. Blocks until complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "x": {"type": "integer", "description": "X position (mm)"},
                    "y": {"type": "integer", "description": "Y position (mm)"},
                },
                "required": ["x", "y"],
            },
        },
    },
    {
        "type": "function",
        "function": {
            "name": "set_vacuum",
            "description": "Turn the vacuum gripper on or off.",
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
            "description": "Read all sensor inputs and return current system state as JSON.",
            "parameters": {"type": "object", "properties": {}},
        },
    },
    {
        "type": "function",
        "function": {
            "name": "log_action",
            "description": "Log a meaningful event to the CSV log file.",
            "parameters": {
                "type": "object",
                "properties": {
                    "part_id": {"type": "integer"},
                    "part_type": {"type": "integer"},
                    "note": {"type": "string"},
                },
                "required": ["part_id", "part_type", "note"],
            },
        },
    },
]


def dispatch_tool(name: str, inputs: dict) -> str:
    if name == "move_crane":
        return tool_move_crane(inputs["x"], inputs["y"])
    elif name == "set_vacuum":
        return tool_set_vacuum(inputs["on"])
    elif name == "set_process":
        return tool_set_process(inputs["process_id"], inputs["on"])
    elif name == "read_sensors":
        return tool_read_sensors()
    elif name == "log_action":
        return tool_log_action(inputs["part_id"], inputs["part_type"], inputs["note"])
    return f"Unknown tool: {name}"


# ---------------------------------------------------------------------------
# Agent base class — OpenAI chat completions + tool loop
# ---------------------------------------------------------------------------
class Agent:
    def __init__(self, name: str, system_prompt: str):
        self.name = name
        self.system_prompt = system_prompt
        self.history = []

    def run(self, task: str, force_tool: str = None) -> str:
        """Run the agent on a task, executing tool calls until done.

        force_tool: name of a tool to force on the FIRST API call.
        Critical for smaller models (like Solar) that describe tool calls
        in plain text instead of actually invoking them.
        """
        print(f"\n[{self.name}] Task: {task}")
        self.history.append({"role": "user", "content": task})
        first_call = True

        while True:
            # Force first tool on small models that ignore tool_choice="auto"
            if force_tool and first_call:
                tool_choice = {"type": "function", "function": {"name": force_tool}}
            else:
                tool_choice = "auto"
            first_call = False

            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    *self.history,
                ],
                tools=TOOLS,
                tool_choice=tool_choice,
                max_tokens=1024,
            )

            msg = response.choices[0].message
            finish_reason = response.choices[0].finish_reason

            self.history.append(msg)

            if finish_reason == "stop" or not msg.tool_calls:
                text = msg.content or ""
                print(f"[{self.name}] Done: {text}")
                return text

            if finish_reason == "tool_calls" or msg.tool_calls:
                for tc in msg.tool_calls:
                    inputs = json.loads(tc.function.arguments)
                    result = dispatch_tool(tc.function.name, inputs)
                    print(f"  [{self.name}] {tc.function.name}({inputs}) -> {result}")
                    self.history.append({
                        "role": "tool",
                        "tool_call_id": tc.id,
                        "content": result,
                    })

    def reset(self):
        self.history = []


# ---------------------------------------------------------------------------
# Agent system prompts
# Tuned for smaller instruction-tuned models (Solar 10.7b):
#   - Imperative, rule-based language ("You MUST call X")
#   - No narrative or explanation in the prompt
#   - One job per agent, stated explicitly
#   - Expected output format stated precisely
# ---------------------------------------------------------------------------

SOURCE_AGENT_PROMPT = """You are a sensor reading agent.
RULE 1: When the user asks you to check sensors, you MUST call the read_sensors tool. Do not write code. Do not describe what you will do. Call the tool immediately.
RULE 2: After read_sensors returns, respond with ONLY this JSON and nothing else:
{"source1": <true or false>, "source2": <true or false>}
Use true if the sensor value is 1, false if it is 0.
RULE 3: Do not call any other tool. Do not explain anything."""

CRANE_AGENT_PROMPT = """You are a crane control agent.
You MUST use tool calls to move the crane. Never describe movements in text.

POSITIONS (mm):
- Travel height: Y=200
- Pick/place height: Y=82
- Source 1: X=55
- Source 2: X=158
- Process 1: X=450
- Process 2: X=650
- Output: X=945

MOVEMENT SEQUENCE - always in this exact order:
1. move_crane(x=current_x, y=200)  <- rise first
2. move_crane(x=target_x, y=200)   <- move horizontally
3. move_crane(x=target_x, y=82)    <- lower
4. set_vacuum(on=true or false)     <- pick or place
5. move_crane(x=target_x, y=200)   <- rise again

PICK = vacuum ON. PLACE = vacuum OFF.
Call log_action after each pick or place."""

PROCESS_AGENT_PROMPT = """You are a process machine control agent.
You MUST use tool calls. Never describe actions in text.

RULES:
1. To start a process: call set_process(process_id=N, on=true)
2. To stop a process: call set_process(process_id=N, on=false)
3. After starting, call read_sensors to confirm isRunning=1
4. Then call set_process(process_id=N, on=false) to stop
5. Call log_action when done

Do NOT move the crane. Do NOT call move_crane or set_vacuum."""

ORCHESTRATOR_PROMPT = """You are a factory orchestrator. You coordinate agents by calling Python methods directly. You do not use tools yourself."""



# ---------------------------------------------------------------------------
# Orchestrator with agent delegation
# ---------------------------------------------------------------------------
class Orchestrator:
    def __init__(self):
        self.source_agent = Agent("SourceAgent", SOURCE_AGENT_PROMPT)
        self.crane_agent = Agent("CraneAgent", CRANE_AGENT_PROMPT)
        self.process_agent = Agent("ProcessAgent", PROCESS_AGENT_PROMPT)
        self.part_counter = 0
        self.history = []

    def _sense(self) -> dict:
        result = self.source_agent.run(
            "Check sensors now.",
            force_tool="read_sensors"   # force small model to actually call the tool
        )
        self.source_agent.reset()
        # Try to parse JSON from anywhere in the response (model may add prose)
        try:
            # Direct parse
            return json.loads(result)
        except Exception:
            pass
        # Fallback: find the last JSON object in the response
        import re
        matches = re.findall(r'\{[^{}]+\}', result)
        for m in reversed(matches):
            try:
                parsed = json.loads(m)
                if "source1" in parsed or "source2" in parsed:
                    return parsed
            except Exception:
                continue
        # Last resort: check if the raw sensor state was updated by the tool call
        print(f"[Orchestrator] WARNING: could not parse sensor result: {result!r}")
        print(f"[Orchestrator] Using live state dict instead")
        return {
            "source1": state.get("source1_sensor", False),
            "source2": state.get("source2_sensor", False),
        }

    def _handle_part(self, part_type: int):
        self.part_counter += 1
        pid = self.part_counter
        print(f"\n{'='*50}")
        print(f"ORCHESTRATOR: Starting part {pid} (type {part_type})")

        if part_type == 1:
            self.crane_agent.run(
                f"Pick up part {pid} from Source 1 (X=55). Then deliver it to Process 1 station (X=450)."
            )
            self.process_agent.run(
                f"Run Process 1 for part {pid}. Start it, wait for completion, then stop it."
            )
            self.crane_agent.run(
                f"Pick up finished part {pid} from Process 1 (X=450). Deliver to output conveyor (X=945). Then return to home position X=450, Y=200."
            )
        else:
            self.crane_agent.run(
                f"Pick up part {pid} from Source 2 (X=158). Then deliver it to Process 2 station (X=650)."
            )
            self.process_agent.run(
                f"Run Process 2 for part {pid}. Start it, wait for completion, then stop it."
            )
            self.crane_agent.run(
                f"Pick up finished part {pid} from Process 2 (X=650). Deliver to output conveyor (X=945). Then return to home position X=450, Y=200."
            )

        # Reset agent conversation history between parts to keep context clean
        self.crane_agent.reset()
        self.process_agent.reset()
        print(f"ORCHESTRATOR: Part {pid} complete.")

    def run_loop(self):
        print("Multi-agent crane system started. Ctrl+C to stop.\n")
        queue = []

        while True:
            # Sense
            sensors = self._sense()
            if sensors.get("source1"):
                queue.append({"id": self.part_counter + 1, "type": 1})
                print(f"ORCHESTRATOR: Queued part type 1 from Source 1")
            if sensors.get("source2"):
                queue.append({"id": self.part_counter + 1, "type": 2})
                print(f"ORCHESTRATOR: Queued part type 2 from Source 2")

            # Process queue
            if queue:
                next_part = queue.pop(0)
                self._handle_part(next_part["type"])

            time.sleep(2)


# ---------------------------------------------------------------------------
# Entry point
# ---------------------------------------------------------------------------
if __name__ == "__main__":
    orchestrator = Orchestrator()
    orchestrator.run_loop()
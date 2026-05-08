"""
Agent base class and system prompts.

Two execution modes:
- run()       : iterative tool-call loop (used by SourceAgent — needs force_tool)
- plan_run()  : one-shot planning (used by Crane/Process agents — 1 API call instead of N)

Prompts are tuned for small instruction-tuned models (Llama 3.1 8B):
- Imperative, rule-based language
- One job per agent
- Expected output format stated inline
"""

import json
import re
from config import MODEL, client
from tools import TOOLS, dispatch_tool


# ---------------------------------------------------------------------------
# System prompts
# ---------------------------------------------------------------------------

SOURCE_AGENT_PROMPT = """\
You are a sensor reading agent.
RULE 1: Call read_sensors immediately. Do not describe what you will do.
RULE 2: After read_sensors returns, respond with ONLY this JSON and nothing else:
{"source1": <true|false>, "source2": <true|false>}
Use true if the sensor value is 1, false if 0. No other text."""


# Used with plan_run() — LLM outputs the full action plan as JSON in one shot.
CRANE_AGENT_PROMPT = """\
You are a crane control agent. Output a JSON plan. Do not explain, output ONLY JSON.

POSITIONS (mm): source1=55, source2=158, process1=450, process2=650, output=945
Heights: pick/place=82, travel/park=200
Safe movement is automatic — just specify the final destination.

OUTPUT FORMAT:
{"steps": [
  {"tool": "move_crane",  "args": {"x": <int>, "y": <int>}},
  {"tool": "set_vacuum",  "args": {"on": <bool>}},
  {"tool": "log_action",  "args": {"part_id": <int>, "part_type": <int>, "note": "<str>"}}
]}

PICK from src_x, DELIVER to dst_x — always this exact sequence:
{"steps": [
  {"tool": "move_crane", "args": {"x": src_x, "y": 82}},
  {"tool": "set_vacuum", "args": {"on": true}},
  {"tool": "log_action", "args": {"part_id": ID, "part_type": TYPE, "note": "Picked part ID from X=src_x"}},
  {"tool": "move_crane", "args": {"x": dst_x, "y": 82}},
  {"tool": "set_vacuum", "args": {"on": false}},
  {"tool": "log_action", "args": {"part_id": ID, "part_type": TYPE, "note": "Delivered part ID to X=dst_x"}},
  {"tool": "move_crane", "args": {"x": 450, "y": 200}}
]}"""


PROCESS_AGENT_PROMPT = """\
You are a process machine control agent. Output a JSON plan. Do not explain, output ONLY JSON.

OUTPUT FORMAT:
{"steps": [
  {"tool": "set_process", "args": {"process_id": <1|2>, "on": <bool>}},
  {"tool": "read_sensors","args": {}},
  {"tool": "log_action",  "args": {"part_id": <int>, "part_type": <int>, "note": "<str>"}}
]}

SEQUENCE — always in this order:
1. set_process on=true
2. read_sensors  (confirm running)
3. set_process on=false
4. log_action"""


# ---------------------------------------------------------------------------
# Agent
# ---------------------------------------------------------------------------

class Agent:
    def __init__(self, name: str, system_prompt: str):
        self.name = name
        self.system_prompt = system_prompt
        self.history: list = []

    def run(self, task: str, force_tool: str | None = None, max_tokens: int = 256) -> str:
        """
        Iterative tool-call loop. Makes one API call per tool invocation.
        Use for SourceAgent where force_tool is needed.
        """
        print(f"\n[{self.name}] {task}")
        self.history.append({"role": "user", "content": task})
        first_call = True

        while True:
            tool_choice = (
                {"type": "function", "function": {"name": force_tool}}
                if force_tool and first_call
                else "auto"
            )
            first_call = False

            response = client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": self.system_prompt},
                    *self.history,
                ],
                tools=TOOLS,
                tool_choice=tool_choice,
                max_tokens=max_tokens,
            )

            msg = response.choices[0].message
            finish_reason = response.choices[0].finish_reason
            self.history.append(msg)

            if finish_reason == "stop" or not msg.tool_calls:
                result = msg.content or ""
                print(f"[{self.name}] → {result}")
                return result

            for tc in msg.tool_calls:
                inputs = json.loads(tc.function.arguments)
                result = dispatch_tool(tc.function.name, inputs)
                print(f"  [{self.name}] {tc.function.name}({inputs}) → {result}")
                self.history.append({
                    "role": "tool",
                    "tool_call_id": tc.id,
                    "content": result,
                })

    def plan_run(self, task: str, max_tokens: int = 512) -> str:
        """
        One-shot planning: one API call returns a JSON {"steps": [...]} plan,
        then Python executes each step sequentially. Avoids the N-roundtrip
        cost of the iterative tool loop.

        Falls back to run() if the LLM output cannot be parsed as a valid plan.
        """
        print(f"\n[{self.name}] (plan) {task}")

        response = client.chat.completions.create(
            model=MODEL,
            messages=[
                {"role": "system", "content": self.system_prompt},
                {"role": "user",   "content": task},
            ],
            max_tokens=max_tokens,
        )

        text = (response.choices[0].message.content or "").strip()
        print(f"  [{self.name}] raw plan: {text[:300]}")

        plan = _parse_json(text)
        if plan is None:
            print(f"  [{self.name}] plan parse failed — falling back to tool loop")
            return self.run(task)

        steps = plan.get("steps", []) if isinstance(plan, dict) else plan
        if not isinstance(steps, list) or not steps:
            print(f"  [{self.name}] empty plan — falling back to tool loop")
            return self.run(task)

        for step in steps:
            tool_name = step.get("tool") or step.get("name")
            args = (
                step.get("args")
                or step.get("arguments")
                or step.get("parameters")
                or {}
            )
            if not tool_name:
                continue
            result = dispatch_tool(tool_name, args)
            print(f"  [{self.name}] {tool_name}({args}) → {result}")

        return "done"

    def reset(self) -> None:
        self.history = []


def _parse_json(text: str) -> dict | list | None:
    """Try to extract and parse a JSON object or array from a string."""
    try:
        return json.loads(text)
    except Exception:
        pass
    for pattern in (r'\{.*\}', r'\[.*\]'):
        m = re.search(pattern, text, re.DOTALL)
        if m:
            try:
                return json.loads(m.group())
            except Exception:
                continue
    return None

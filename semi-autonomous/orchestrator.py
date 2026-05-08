"""
Orchestrator: detects parts, queues them, and delegates to sub-agents.
"""

import json
import re
import time

import hardware
from agents import Agent, SOURCE_AGENT_PROMPT, CRANE_AGENT_PROMPT, PROCESS_AGENT_PROMPT
from tools import state
from config import POSITIONS


class Orchestrator:
    def __init__(self):
        self.source_agent  = Agent("SourceAgent",  SOURCE_AGENT_PROMPT)
        self.crane_agent   = Agent("CraneAgent",   CRANE_AGENT_PROMPT)
        self.process_agent = Agent("ProcessAgent", PROCESS_AGENT_PROMPT)
        self.part_counter  = 0

    def _sense(self) -> dict:
        """Ask SourceAgent to read sensors; parse its JSON response."""
        result = self.source_agent.run("Check sensors now.", max_tokens=128)
        self.source_agent.reset()

        try:
            return json.loads(result)
        except Exception:
            pass

        for m in reversed(re.findall(r'\{[^{}]+\}', result)):
            try:
                parsed = json.loads(m)
                if "source1" in parsed or "source2" in parsed:
                    return parsed
            except Exception:
                continue

        print(f"[Orchestrator] WARNING: could not parse sensor JSON: {result!r}")
        return {
            "source1": state["source1_sensor"],
            "source2": state["source2_sensor"],
        }

    def _handle_part(self, part_type: int) -> None:
        self.part_counter += 1
        pid    = self.part_counter
        src_x  = POSITIONS["source1"]  if part_type == 1 else POSITIONS["source2"]
        proc_n = 1                      if part_type == 1 else 2
        proc_x = POSITIONS["process1"] if part_type == 1 else POSITIONS["process2"]
        out_x  = POSITIONS["output"]

        print(f"\n{'='*55}")
        print(f"ORCHESTRATOR: Part {pid} (type {part_type})")

        self.crane_agent.plan_run(
            f"Part {pid} type {part_type}. Pick from source{part_type} X={src_x}. Deliver to process{proc_n} X={proc_x}."
        )
        self.process_agent.plan_run(
            f"Run process{proc_n} for part {pid} type {part_type}."
        )
        self.crane_agent.plan_run(
            f"Part {pid} type {part_type}. Pick from process{proc_n} X={proc_x}. Deliver to output X={out_x}."
        )

        self.crane_agent.reset()
        self.process_agent.reset()
        print(f"ORCHESTRATOR: Part {pid} complete.")

    def run_loop(self) -> None:
        hardware.initialize()
        print("Multi-agent crane system ready. Ctrl+C to stop.\n")
        queue: list[dict] = []

        while True:
            sensors = self._sense()

            if sensors.get("source1"):
                queue.append({"type": 1})
                print("ORCHESTRATOR: Queued part type 1 from Source 1")
            if sensors.get("source2"):
                queue.append({"type": 2})
                print("ORCHESTRATOR: Queued part type 2 from Source 2")

            if queue:
                self._handle_part(queue.pop(0)["type"])

            time.sleep(2)

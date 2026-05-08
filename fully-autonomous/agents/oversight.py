"""
OversightAgent — the LLM brain.

Subscribes to ALL bus events. Maintains a FactoryState. On each significant
event (PartDetected, WorkOrderComplete, ProcessComplete) it calls GPT-4.1-mini
via AsyncOpenAI to decide the next action, then publishes WorkOrder or
StartProcess to the relevant executor agents.

The LLM is called only when the crane is free (_crane_busy=False) and at most
once per second. This keeps API costs low and decisions timely.
"""

import asyncio
import json
import time
from dataclasses import dataclass, field

from agents.base import BaseAgent
from bus import MessageBus
from messages import (
    PartDetected, WorkOrderComplete, ProcessComplete,
    CraneAcquiredLock, WorkOrder, StartProcess, FactoryIdle,
)
from config import async_client, MODEL, POSITIONS

OVERSIGHT_PROMPT = """\
You are the control brain of an autonomous manufacturing factory.
You receive the current factory state as JSON and decide the single best next action.

FACTORY LAYOUT:
- source1 X=55, source2 X=158  →  incoming parts detected by sensors
- process1 X=450, process2 X=650  →  processing machines
- output X=945  →  final output conveyor
- Crane travels at Y=200, picks/places at Y=82

ROUTING RULES:
- Part type 1 (from source1) → process1 → output
- Part type 2 (from source2) → process2 → output
- After a process completes, the part must go to output
- Two machines can run simultaneously
- The crane can only do ONE pick-and-place at a time

OUTPUT: Respond with EXACTLY ONE JSON object. No explanation. No markdown.

Valid actions:
{"action": "pick_to_process", "part_id": <int>, "part_type": <int>, "pick_x": <int>, "place_x": <int>}
{"action": "pick_to_output",  "part_id": <int>, "part_type": <int>, "pick_x": <int>}
{"action": "wait"}

Choose "pick_to_process" when a part is waiting at a source and the crane is free.
Choose "pick_to_output" when a finished part is at a process station (machine done) and crane is free.
Choose "wait" when the crane is busy or there is nothing actionable right now.
- OPPORTUNISTIC: while a machine is running, use the crane to pick and deliver other waiting source parts.
Prioritise throughput: if a machine is currently running and there are source parts waiting, pick those source parts first (use the crane while the machine works). If a machine is DONE and a source part is also waiting, prefer pick_to_output (clear finished parts first)."""


@dataclass
class FactoryState:
    pending_parts: list = field(default_factory=list)   # [{part_id, part_type, source_x}]
    parts_at_process: dict = field(default_factory=dict) # {proc_id: {part_id, part_type}}
    process_running: dict = field(default_factory=lambda: {1: False, 2: False})
    active_orders: dict = field(default_factory=dict)    # {order_id: WorkOrder}
    crane_busy: bool = False
    next_part_id: int = 1
    next_order_id: int = 1
    completed_parts: int = 0


class OversightAgent(BaseAgent):
    def __init__(self, bus: MessageBus):
        super().__init__("OversightAgent", bus)
        self._state = FactoryState()
        self._needs_decision = False
        self._last_llm_call = 0.0

    async def run(self) -> None:
        print("[OversightAgent] started — LLM brain online")
        while True:
            event = await self.receive()
            await self._handle_event(event)

            if self._needs_decision and not self._state.crane_busy:
                await self._decide()

    # ── Event handling ────────────────────────────────────────────────────────

    async def _handle_event(self, event) -> None:
        match event:
            case PartDetected():
                part = {
                    "part_id":   self._state.next_part_id,
                    "part_type": event.source_id,
                    "source_x":  event.position_x,
                }
                self._state.next_part_id += 1
                self._state.pending_parts.append(part)
                print(f"[OversightAgent] Part {part['part_id']} detected at source{event.source_id} (X={event.position_x})")
                self._needs_decision = True

            case WorkOrderComplete():
                self._state.active_orders.pop(event.order_id, None)
                if event.place_x in (POSITIONS["process1"], POSITIONS["process2"]):
                    proc_id = 1 if event.place_x == POSITIONS["process1"] else 2
                    self._state.parts_at_process[proc_id] = {
                        "part_id":   event.part_id,
                        "part_type": event.part_type,
                    }
                    # Start machine NOW — part has physically arrived at the station
                    self._state.process_running[proc_id] = True
                    await self.publish(StartProcess(
                        source="OversightAgent",
                        process_id=proc_id,
                        part_id=event.part_id,
                        part_type=event.part_type,
                    ))
                    print(f"[OversightAgent] Machine {proc_id} started — part {event.part_id} delivered")
                elif event.place_x == POSITIONS["output"]:
                    self._state.completed_parts += 1
                    print(f"[OversightAgent] ✓ Part {event.part_id} delivered to output. "
                          f"Total completed: {self._state.completed_parts}")
                self._state.crane_busy = False
                self._needs_decision = True

            case ProcessComplete():
                self._state.process_running[event.process_id] = False
                print(f"[OversightAgent] Machine {event.process_id} done — "
                      f"part {event.part_id} ready for output pickup")
                self._needs_decision = True

            case CraneAcquiredLock():
                self._state.crane_busy = True

    # ── LLM decision ──────────────────────────────────────────────────────────

    async def _decide(self) -> None:
        now = time.monotonic()
        if now - self._last_llm_call < 1.0:
            return
        self._last_llm_call = now
        self._needs_decision = False

        # Parts at process that are finished (machine done)
        ready_for_output = {
            pid: info
            for pid, info in self._state.parts_at_process.items()
            if not self._state.process_running.get(pid, False)
        }
        # Parts at process still being machined
        being_processed = {
            pid: info
            for pid, info in self._state.parts_at_process.items()
            if self._state.process_running.get(pid, False)
        }

        state_summary = {
            "pending_parts_at_sources": self._state.pending_parts,
            "parts_finished_at_process_ready_for_output": ready_for_output,
            "parts_currently_being_machined": being_processed,
            "crane_busy": self._state.crane_busy,
            "process_running": self._state.process_running,
            "positions": POSITIONS,
        }

        print(f"[OversightAgent] Asking LLM... state={json.dumps(state_summary, default=str)}")

        try:
            response = await async_client.chat.completions.create(
                model=MODEL,
                messages=[
                    {"role": "system", "content": OVERSIGHT_PROMPT},
                    {"role": "user",   "content": json.dumps(state_summary)},
                ],
                max_tokens=128,
                temperature=0,
            )
            text = (response.choices[0].message.content or "").strip()
            decision = json.loads(text)
        except Exception as e:
            print(f"[OversightAgent] LLM error: {e}")
            return

        print(f"[OversightAgent] LLM decision: {decision}")
        await self._act(decision)

    # ── Action dispatch ───────────────────────────────────────────────────────

    async def _act(self, decision: dict) -> None:
        action = decision.get("action")

        match action:
            case "pick_to_process":
                part_id   = decision["part_id"]
                part_type = decision["part_type"]
                pick_x    = decision["pick_x"]
                place_x   = decision["place_x"]

                # Remove from pending
                self._state.pending_parts = [
                    p for p in self._state.pending_parts if p["part_id"] != part_id
                ]

                order_id = self._state.next_order_id
                self._state.next_order_id += 1

                order = WorkOrder(
                    source="OversightAgent",
                    order_id=order_id,
                    part_id=part_id,
                    part_type=part_type,
                    pick_x=pick_x,
                    place_x=place_x,
                )
                self._state.active_orders[order_id] = order
                self._state.crane_busy = True
                await self.publish(order)   # machine starts on delivery, not here

            case "pick_to_output":
                part_id   = decision["part_id"]
                part_type = decision["part_type"]
                pick_x    = decision["pick_x"]
                place_x   = POSITIONS["output"]

                proc_id = 1 if pick_x == POSITIONS["process1"] else 2
                self._state.parts_at_process.pop(proc_id, None)

                order_id = self._state.next_order_id
                self._state.next_order_id += 1

                order = WorkOrder(
                    source="OversightAgent",
                    order_id=order_id,
                    part_id=part_id,
                    part_type=part_type,
                    pick_x=pick_x,
                    place_x=place_x,
                )
                self._state.active_orders[order_id] = order
                self._state.crane_busy = True
                await self.publish(order)

            case "wait":
                if (not self._state.pending_parts
                        and not self._state.active_orders
                        and not any(self._state.process_running.values())):
                    print("[OversightAgent] Factory idle — waiting for parts")
                    await self.publish(FactoryIdle(source="OversightAgent"))

            case _:
                print(f"[OversightAgent] Unknown action from LLM: {action}")

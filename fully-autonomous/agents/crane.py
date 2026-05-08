"""
CraneAgent — pure hardware executor, no LLM.

Waits for WorkOrder messages, acquires the physical asyncio.Lock, executes the
pick-and-place sequence via hardware.safe_move(), then releases the lock and
publishes WorkOrderComplete. The lock serialises all physical crane operations;
the asyncio.sleep calls inside safe_move() yield to the event loop so other
agents (ProcessAgent, SensorAgent) run concurrently during crane movement.
"""

import asyncio
import csv
import datetime
import os

from agents.base import BaseAgent
from bus import MessageBus
from messages import WorkOrder, WorkOrderComplete, CraneAcquiredLock, CraneReleasedLock
from config import PICK_Y, TRAVEL_Y, HOME_X
import hardware


class CraneAgent(BaseAgent):
    def __init__(self, bus: MessageBus, crane_lock: asyncio.Lock):
        super().__init__("CraneAgent", bus)
        self._lock = crane_lock

    async def run(self) -> None:
        print("[CraneAgent] started, waiting for WorkOrders")
        while True:
            event = await self.receive()
            if isinstance(event, WorkOrder):
                await self._execute(event)

    async def _execute(self, order: WorkOrder) -> None:
        print(f"[CraneAgent] Received WorkOrder {order.order_id}: "
              f"pick X={order.pick_x} → place X={order.place_x} (part {order.part_id})")

        async with self._lock:
            await self.publish(CraneAcquiredLock(source="CraneAgent", order_id=order.order_id))

            # Pick
            await hardware.safe_move(order.pick_x, PICK_Y)
            await hardware.set_vacuum(True)
            self._log(order, f"Picked part {order.part_id} from X={order.pick_x}")

            # Place
            await hardware.safe_move(order.place_x, PICK_Y)
            await hardware.set_vacuum(False)
            self._log(order, f"Delivered part {order.part_id} to X={order.place_x}")

            # Park at travel height
            await hardware.safe_move(HOME_X, TRAVEL_Y)

        await self.publish(CraneReleasedLock(source="CraneAgent", order_id=order.order_id))
        await self.publish(WorkOrderComplete(
            source="CraneAgent",
            order_id=order.order_id,
            part_id=order.part_id,
            part_type=order.part_type,
            pick_x=order.pick_x,
            place_x=order.place_x,
        ))
        print(f"[CraneAgent] WorkOrder {order.order_id} complete")

    def _log(self, order: WorkOrder, note: str) -> None:
        cx, cy = hardware.get_position()
        path = os.path.join(os.path.dirname(__file__), "..", "agent_log.csv")
        write_header = not os.path.exists(path)
        entry = {
            "part_id":   order.part_id,
            "part_type": order.part_type,
            "timestamp": datetime.datetime.now().isoformat(),
            "crane_x":   cx,
            "crane_y":   cy,
            "note":      note,
        }
        with open(path, "a", newline="") as f:
            w = csv.DictWriter(f, fieldnames=entry.keys())
            if write_header:
                w.writeheader()
            w.writerow(entry)
        print(f"  [CraneAgent] {note}")

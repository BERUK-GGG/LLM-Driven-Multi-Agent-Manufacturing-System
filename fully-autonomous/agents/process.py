"""
ProcessAgent — pure hardware executor, no LLM.

Each StartProcess message spawns an independent asyncio.Task that runs the
machine cycle. Both machines can run simultaneously because they don't need
the crane lock — they are independent background tasks. The asyncio.sleep
inside _run_machine yields to the event loop, so the crane continues moving
while the machine runs.
"""

import asyncio
from agents.base import BaseAgent
from bus import MessageBus
from messages import StartProcess, ProcessComplete
from config import PROCESS_TIME
import hardware


class ProcessAgent(BaseAgent):
    def __init__(self, bus: MessageBus):
        super().__init__("ProcessAgent", bus)
        self._tasks: dict[int, asyncio.Task] = {}

    async def run(self) -> None:
        print("[ProcessAgent] started, waiting for StartProcess commands")
        while True:
            event = await self.receive()
            if isinstance(event, StartProcess):
                await self._start(event)

    async def _start(self, event: StartProcess) -> None:
        task = self._tasks.get(event.process_id)
        if task and not task.done():
            print(f"[ProcessAgent] WARNING: machine {event.process_id} already running, ignoring")
            return

        print(f"[ProcessAgent] Starting machine {event.process_id} for part {event.part_id}")
        self._tasks[event.process_id] = asyncio.create_task(
            self._run_machine(event.process_id, event.part_id, event.part_type),
            name=f"machine{event.process_id}_part{event.part_id}",
        )

    async def _run_machine(self, process_id: int, part_id: int, part_type: int) -> None:
        await hardware.set_process(process_id, True)
        print(f"[ProcessAgent] Machine {process_id} running ({PROCESS_TIME}s)...")
        await asyncio.sleep(PROCESS_TIME)
        await hardware.set_process(process_id, False)
        print(f"[ProcessAgent] Machine {process_id} done — part {part_id} ready for pickup")
        await self.publish(ProcessComplete(
            source="ProcessAgent",
            process_id=process_id,
            part_id=part_id,
            part_type=part_type,
        ))

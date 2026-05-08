"""
Fully Autonomous Factory — entry point.

The only human interaction is typing "start factory" at startup.
After that, four concurrent agents communicate through the message bus
and run the factory autonomously:

  SensorAgent   — detects parts at source stations
  CraneAgent    — executes pick-and-place operations (asyncio.Lock)
  ProcessAgent  — runs process machines as concurrent background tasks
  OversightAgent — LLM brain that makes all strategic decisions
"""

import asyncio
import sys
import os

# Make project root importable
sys.path.insert(0, os.path.dirname(__file__))

import hardware
from bus import MessageBus
from messages import WorkOrder, StartProcess, PartDetected, SensorUpdate
from messages import WorkOrderComplete, ProcessComplete, CraneAcquiredLock, CraneReleasedLock
from messages import FactoryIdle
from agents.sensor import SensorAgent
from agents.crane import CraneAgent
from agents.process import ProcessAgent
from agents.oversight import OversightAgent


async def main() -> None:
    print("=" * 55)
    print("  Fully Autonomous Factory Control System")
    print("=" * 55)


    await hardware.initialize()

    bus = MessageBus()
    crane_lock = asyncio.Lock()

    sensor_agent   = SensorAgent(bus)
    crane_agent    = CraneAgent(bus, crane_lock)
    process_agent  = ProcessAgent(bus)
    oversight_agent = OversightAgent(bus)

    # Register subscriptions
    bus.subscribe("SensorAgent")                                              # pure producer
    bus.subscribe("CraneAgent",    [WorkOrder])
    bus.subscribe("ProcessAgent",  [StartProcess])
    bus.subscribe("OversightAgent")                                           # receives ALL

    print("[SYSTEM] All agents online. Factory is fully autonomous.\n")

    tasks = [
        asyncio.create_task(sensor_agent.run(),     name="SensorAgent"),
        asyncio.create_task(crane_agent.run(),      name="CraneAgent"),
        asyncio.create_task(process_agent.run(),    name="ProcessAgent"),
        asyncio.create_task(oversight_agent.run(),  name="OversightAgent"),
    ]

    try:
        await asyncio.gather(*tasks)
    except (KeyboardInterrupt, asyncio.CancelledError):
        pass
    finally:
        print("\n[SYSTEM] Shutdown requested.")
        for t in tasks:
            t.cancel()
        await asyncio.gather(*tasks, return_exceptions=True)
        print("[SYSTEM] Factory stopped.")


if __name__ == "__main__":
    asyncio.run(main())

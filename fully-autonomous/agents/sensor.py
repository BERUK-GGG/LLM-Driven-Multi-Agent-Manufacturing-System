import asyncio
from agents.base import BaseAgent
from bus import MessageBus
from messages import PartDetected, SensorUpdate
from config import SENSOR_POLL, POSITIONS
import hardware


class SensorAgent(BaseAgent):
    def __init__(self, bus: MessageBus):
        super().__init__("SensorAgent", bus)
        self._prev = {"source1": False, "source2": False}

    async def run(self) -> None:
        print("[SensorAgent] started")
        while True:
            await asyncio.sleep(SENSOR_POLL)
            data = await hardware.read_sensors()

            s1 = bool(data["source1_sensor"])
            s2 = bool(data["source2_sensor"])

            # Rising-edge detection: publish only on 0→1 transition
            if s1 and not self._prev["source1"]:
                print("[SensorAgent] Part detected at Source 1")
                await self.publish(PartDetected(
                    source="SensorAgent",
                    source_id=1,
                    position_x=POSITIONS["source1"],
                ))
            if s2 and not self._prev["source2"]:
                print("[SensorAgent] Part detected at Source 2")
                await self.publish(PartDetected(
                    source="SensorAgent",
                    source_id=2,
                    position_x=POSITIONS["source2"],
                ))

            self._prev = {"source1": s1, "source2": s2}

            await self.publish(SensorUpdate(
                source="SensorAgent",
                source1=s1,
                source2=s2,
                process1_running=bool(data["process1_running"]),
                process2_running=bool(data["process2_running"]),
                crane_x=data["crane_x"],
                crane_y=data["crane_y"],
            ))

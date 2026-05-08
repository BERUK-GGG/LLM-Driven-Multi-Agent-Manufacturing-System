from abc import ABC, abstractmethod
from bus import MessageBus


class BaseAgent(ABC):
    def __init__(self, name: str, bus: MessageBus):
        self.name = name
        self.bus = bus

    @abstractmethod
    async def run(self) -> None:
        ...

    async def publish(self, event) -> None:
        await self.bus.publish(event)

    async def receive(self):
        return await self.bus.get(self.name)

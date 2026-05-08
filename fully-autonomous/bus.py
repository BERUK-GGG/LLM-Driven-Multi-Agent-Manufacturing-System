"""
Async publish-subscribe message bus.

Each subscriber gets its own asyncio.Queue. publish() uses put_nowait so the
publisher never blocks on a slow subscriber. Subscribers with event_types=None
receive every event (used by OversightAgent).
"""

import asyncio
from typing import Any, Type


class MessageBus:
    def __init__(self):
        self._queues: dict[str, asyncio.Queue] = {}
        self._subscriptions: dict[str, set[type]] = {}

    def subscribe(self, name: str, event_types: list[Type] | None = None) -> None:
        self._queues[name] = asyncio.Queue()
        self._subscriptions[name] = set(event_types) if event_types else set()

    async def publish(self, event: Any) -> None:
        for name, queue in self._queues.items():
            subs = self._subscriptions[name]
            if not subs or type(event) in subs:
                queue.put_nowait(event)

    async def get(self, subscriber_name: str) -> Any:
        return await self._queues[subscriber_name].get()

import asyncio
import json
import uuid
from typing import AsyncGenerator


class SSEManager:
    """内存 SSE 广播管理器，单进程单例。"""

    def __init__(self):
        self._subscribers: dict[uuid.UUID, list[asyncio.Queue]] = {}

    def subscribe(self, workflow_id: uuid.UUID) -> asyncio.Queue:
        if workflow_id not in self._subscribers:
            self._subscribers[workflow_id] = []
        queue: asyncio.Queue = asyncio.Queue()
        self._subscribers[workflow_id].append(queue)
        return queue

    def unsubscribe(self, workflow_id: uuid.UUID, queue: asyncio.Queue) -> None:
        if workflow_id in self._subscribers:
            try:
                self._subscribers[workflow_id].remove(queue)
            except ValueError:
                pass
            if not self._subscribers[workflow_id]:
                del self._subscribers[workflow_id]

    async def broadcast(self, workflow_id: uuid.UUID, event_data: dict) -> None:
        for queue in self._subscribers.get(workflow_id, []):
            await queue.put(event_data)

    async def stream(self, workflow_id: uuid.UUID) -> AsyncGenerator[str, None]:
        queue = self.subscribe(workflow_id)
        try:
            while True:
                data = await queue.get()
                if data is None:
                    break
                yield f"data: {json.dumps(data, ensure_ascii=False, default=str)}\n\n"
        finally:
            self.unsubscribe(workflow_id, queue)

    async def close_workflow(self, workflow_id: uuid.UUID) -> None:
        for queue in self._subscribers.get(workflow_id, []):
            await queue.put(None)
        self._subscribers.pop(workflow_id, None)


sse_manager = SSEManager()

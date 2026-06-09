import asyncio
from typing import Dict, List

class ProgressManager:
    def __init__(self):
        # 维护一个映射：task_id -> [asyncio.Queue, ...]
        self._subscribers: Dict[str, List[asyncio.Queue]] = {}
        # 缓存每个任务最后推送的进度包：task_id -> last_progress_data
        self._last_progress: Dict[str, dict] = {}

    def publish(self, task_id: str, data: dict):
        """
        向订阅了该 task_id 的所有客户端推送新的进度包，并缓存最新进度
        """
        self._last_progress[task_id] = data
        if task_id in self._subscribers:
            for q in self._subscribers[task_id]:
                q.put_nowait(data)

    async def subscribe(self, task_id: str):
        """
        异步生成器，供 FastAPI SSE 路由调用。
        客户端订阅后，优先向队列中投递当前缓存的最新进度包，使其能立即同步当前进度，
        然后持续接收该 task_id 的推送，直到任务完成或失败。
        """
        queue = asyncio.Queue()
        
        # 如果有缓存进度，优先放入队列，让新客户端连接时立即获得最新状态，避免显示 10%
        if task_id in self._last_progress:
            queue.put_nowait(self._last_progress[task_id])
            
        if task_id not in self._subscribers:
            self._subscribers[task_id] = []
        self._subscribers[task_id].append(queue)
        
        try:
            # 持续监听队列中的推送
            while True:
                data = await queue.get()
                yield data
                # 任务处于终结状态（成功/失败），自动切断 SSE 长连接，释放连接资源并删除缓存
                if data.get("step") in ["completed", "failed"]:
                    self._last_progress.pop(task_id, None)
                    break
        finally:
            # 连接断开时的清理工作，避免内存泄露
            if task_id in self._subscribers:
                self._subscribers[task_id].remove(queue)
                if not self._subscribers[task_id]:
                    del self._subscribers[task_id]

progress_manager = ProgressManager()

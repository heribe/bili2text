import asyncio

from progress import ProgressManager


def test_subscribe_receives_cached_progress_first():
    async def scenario():
        manager = ProgressManager()
        manager.publish("task-1", {"step": "download", "progress": 20})

        stream = manager.subscribe("task-1")
        first = await stream.__anext__()
        await stream.aclose()

        return first

    assert asyncio.run(scenario()) == {"step": "download", "progress": 20}


def test_completed_progress_closes_subscription_and_clears_cache():
    async def scenario():
        manager = ProgressManager()
        stream = manager.subscribe("task-1")

        manager.publish("task-1", {"step": "completed", "progress": 100})
        first = await stream.__anext__()

        try:
            await stream.__anext__()
        except StopAsyncIteration:
            closed = True
        else:
            closed = False

        return first, closed, manager._last_progress, manager._subscribers

    first, closed, last_progress, subscribers = asyncio.run(scenario())

    assert first == {"step": "completed", "progress": 100}
    assert closed is True
    assert last_progress == {}
    assert subscribers == {}

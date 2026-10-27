"""Own a monitor loop and drain its tasks without nested run_until_complete."""
import asyncio


async def listen(client):
    try:
        task = await client.start(
            fetch_room_info=True, fetch_gift_info=False, fetch_live_check=True,
        )
        await task
    except asyncio.CancelledError:
        # disconnect() cancels the receive task on normal room changes.
        pass
    finally:
        try:
            await asyncio.wait_for(client.disconnect(close_client=False), timeout=3)
        except (Exception, asyncio.CancelledError):
            pass
        # close_client=True invokes client.close() -> synchronous _clean_tasks()
        # in TikTokLive 7.0.1. Close the HTTP transport directly instead.
        try:
            await asyncio.wait_for(client.web.close(), timeout=3)
        except (Exception, asyncio.CancelledError):
            pass


def drain_loop(loop):
    async def drain():
        pending = [t for t in asyncio.all_tasks() if t is not asyncio.current_task()]
        for task in pending:
            task.cancel()
        if pending:
            done, remaining = await asyncio.wait(pending, timeout=3)
            for task in done:
                if not task.cancelled():
                    task.exception()
            if remaining:
                print(f"[Battle Monitor Cleanup] {len(remaining)} tasks did not stop", flush=True)
        await loop.shutdown_asyncgens()
    try:
        loop.run_until_complete(drain())
    finally:
        loop.close()

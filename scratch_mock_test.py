import asyncio
import gc
from unittest.mock import AsyncMock

async def main():
    mock_irr = AsyncMock()
    coro = mock_irr.async_cancel_listeners()
    
    mock_func = mock_irr.async_cancel_listeners
    print("mock_func attributes:", dir(mock_func))
    
    # Check if we can find unawaited coroutines in gc.get_objects()
    # that are instances of coroutine and have AsyncMockMixin._execute_mock_call
    for obj in gc.get_objects():
        if type(obj).__name__ == "coroutine":
            if "AsyncMockMixin._execute_mock_call" in str(obj) or "AsyncMock" in str(obj):
                print("Found coroutine in gc:", obj, "status:", obj.cr_running if hasattr(obj, "cr_running") else None)
                # Let's try closing it!
                obj.close()
                print("Closed coroutine found in gc")
    
    # Let's clean up coro to prevent warning in this script if gc didn't close it
    try:
        coro.close()
    except RuntimeError:
        pass

if __name__ == "__main__":
    asyncio.run(main())

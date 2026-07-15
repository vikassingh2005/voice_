## 2024-07-15 - Blocking `async def` in FastAPI
**Learning:** `psutil.cpu_percent(interval=0.5)` blocks the thread for 0.5 seconds. When placed inside an `async def` route handler, it blocks the main asyncio event loop, causing the entire FastAPI server to freeze for half a second. Since the frontend polls this every 2.5s, the server is frozen 20% of the time.
**Action:** Use synchronous `def` for FastAPI routes containing blocking calls like `psutil`, so FastAPI offloads them to a threadpool.

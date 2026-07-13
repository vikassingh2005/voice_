## 2024-05-18 - [FastAPI Event Loop Blockers]
**Learning:** `psutil.cpu_percent(interval=0.5)` called inside a standard `async def` FastAPI route completely blocks the asyncio event loop for 0.5s per hit, severely degrading overall concurrent performance.
**Action:** Always prefer `psutil.cpu_percent(interval=None)` for polling endpoints, initializing it once during app startup to establish the baseline.

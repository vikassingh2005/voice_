## 2024-05-15 - FastAPI Async Def Blocking
**Learning:** In FastAPI, placing a synchronous blocking call (like `time.sleep()` or `psutil.cpu_percent(interval=0.5)`) inside an `async def` route blocks the entire main event loop. This completely freezes the application, causing huge latency spikes for all concurrent requests (including WebSockets and other endpoints).
**Action:** When a route must perform synchronous blocking I/O or computations, define it with `def` instead of `async def`. FastAPI will automatically execute it in an external threadpool, keeping the main event loop responsive.

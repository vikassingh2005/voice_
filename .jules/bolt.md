## 2024-05-24 - Efficient counting in SQLite
**Learning:** The `/api/v1/stats` endpoint in the backend queries `get_recent_logs(1000)` simply to count the total number of commands.
**Action:** Replaced `get_recent_logs(1000)` with a dedicated SQL `COUNT(*)` query to avoid allocating memory for large arrays simply to get their length.

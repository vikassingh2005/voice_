# PRAVAHA Codebase Review & Actionable Insights

Based on a thorough review of the PRAVAHA Voice Assistant codebase, this document highlights architectural strengths, technical debt, potential bugs, and actionable recommendations for improvement, specifically focusing on error handling, documentation, and test coverage.

## 1. Architecture & Strengths
*   **Modular Design**: The system is well-separated into distinct modules (`audio_handler`, `tts`, `stt`, `llm`, `system_control`), making it relatively easy to maintain.
*   **Concurrency Models**: The codebase correctly leverages both `asyncio` for the FastAPI backend/WebSockets and `threading` for background audio processing (TTS streaming, voice assistant loop).
*   **Acoustic Echo Cancellation (AEC)**: Thoughtful implementation of a software AEC toggle (`set_speaking` and attenuation) to prevent the microphone from picking up the assistant's own TTS output.

## 2. Technical Debt & Areas for Improvement

### 2.1 Test Coverage
*   **Issue**: There are currently *no automated tests* (unit tests, integration tests, or end-to-end tests) in the repository.
*   **Recommendation**:
    *   Introduce `pytest`.
    *   Write unit tests for isolated, pure functions like `parse_command` in `command_parser.py`.
    *   Mock external dependencies (`pyaudio`, `sounddevice`, `ollama`, `chromadb`) to test `audio_handler.py`, `tts.py`, and `llm.py` without hardware.
    *   Test the `SystemController` by mocking `subprocess.Popen` and `subprocess.run` to ensure OS commands are constructed correctly.

### 2.2 Error Handling & Robustness
*   **Broad Exception Catching**:
    *   *Observation*: In `main.py`'s `voice_assistant_loop`, exceptions are caught broadly: `except Exception as e: logger.error(...)`. If an error occurs, the loop resets the detector, but the assistant state (`voice_active`) or internal state of engines (like STT or TTS) could be left in an inconsistent state.
    *   *Observation*: In `system_control.py` and `tts.py`, many `except:` blocks catch all exceptions without specifying types, which can swallow `KeyboardInterrupt` or mask important runtime errors.
    *   *Recommendation*: Catch specific exceptions (e.g., `subprocess.CalledProcessError`, `pyaudio.paBadStreamPtr`). Avoid naked `except:` statements.
*   **Thread Safety Issues**:
    *   *Observation*: In `main.py`, `ws_clients` is a global list manipulated across async contexts. While standard CPython lists have some thread-safety via the GIL, iterating over `ws_clients[:]` while modifying it in `except` blocks inside `broadcast_status` is prone to race conditions if multiple websockets disconnect simultaneously.
    *   *Recommendation*: Use `asyncio.Lock()` or carefully handle client disconnections.
*   **Missing Dependency Guards**:
    *   *Observation*: The project relies heavily on C-bindings and system libraries (`pyaudio`, `sounddevice`, `cv2`). While `tts.py` and `wake_word.py` have basic `try/except ImportError` blocks, `main.py` assumes everything imports correctly.
    *   *Recommendation*: Add a robust `check_requirements()` function on startup to verify all audio and system dependencies are met before starting the FastApi server.

### 2.3 Documentation & Typing
*   **Incomplete Type Hints**:
    *   While many functions have type hints, others (especially dict payloads in `main.py` and `command_parser.py`) lack explicit types (e.g., using `Dict[str, Any]` or `TypedDict` for the intent parameters).
*   **Docstrings**:
    *   Most modules have a good module-level docstring, but class methods lack detailed descriptions of parameters and return types.
    *   *Recommendation*: Adopt a consistent docstring standard (like Google or NumPy style) across all methods, especially in `system_control.py`.

### 2.4 Code Quality & Security Bugs
*   **Hardcoded Subprocess Calls (`shell=True`)**:
    *   *Observation*: In `system_control.py` -> `run_terminal_command`, commands are executed via `subprocess.run(command, shell=True)`. This is a significant security risk (Command Injection) if user input is ever passed to this function without strict sanitization.
    *   *Recommendation*: Use `shlex.split()` to parse commands and set `shell=False` wherever possible. If `shell=True` is absolutely necessary for pipelines or shell builtins, ensure stringent sanitization of the input.
*   **Hardcoded Fallback Locations**:
    *   *Observation*: In `system_control.py`, checking for `~/.config` or standard linux paths may fail on Windows or macOS. Although `pathlib.Path.home()` is used, directory names like `Pictures`, `Downloads`, etc., might be localized.
    *   *Recommendation*: Use the `appdirs` or `platformdirs` library for cross-platform directory resolution.
*   **Database Concurrency**:
    *   *Observation*: `database.py` uses `aiosqlite`, but creates a new connection for every query (`async with aiosqlite.connect(DB_PATH) as db:`). While SQLite handles this well, a connection pool or persistent connection would be more performant under load.

### 2.5 State Machine in Audio Handler
*   *Observation*: The audio handler state machine in `audio_handler.py` relies on `buffer.append(frame.tobytes())` continuously. If no endpoint is detected (e.g., continuous background noise above threshold but not speech), the buffer could grow indefinitely, leading to an OOM error.
*   *Recommendation*: Implement a maximum utterance duration limit (e.g., 30 seconds). If `len(buffer)` exceeds the limit, force an `ENDPOINT` transition.

## 3. Summary of Action Items
1.  **Add `pytest`** and write unit tests for `command_parser.py`.
2.  **Refactor `subprocess.run`** calls in `system_control.py` to avoid `shell=True` where possible.
3.  **Implement a timeout/max buffer size** in `AudioHandler.record_utterance()`.
4.  **Replace generic `except Exception:`** blocks with specific exceptions.

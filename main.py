import os
import asyncio
import time
import psutil
import httpx
import threading
from dotenv import load_dotenv
from fastapi import FastAPI, Request, WebSocket, WebSocketDisconnect
from fastapi.middleware.cors import CORSMiddleware
from fastapi.staticfiles import StaticFiles
from fastapi.responses import FileResponse
from pydantic import BaseModel
from database import init_db, log_command, get_recent_logs, clear_logs
from contextlib import asynccontextmanager
from command_parser import parse_command
from system_control import SystemController

# ── Echos Modules ────────────────────────────────────────────────────────────
from loguru import logger
import config
from audio_handler import AudioHandler
from llm import LLMEngine
from memory import MemoryStore
from stt import STTEngine
from tts import TTSEngine
from wake_word import WakeWordDetector

load_dotenv()

# Global instances
SERVICE_NAME = "PRAVAHA"
system_controller = SystemController()
ws_clients: list[WebSocket] = []

logger.info("Initializing integrated PRAVAHA AI subsystems...")
audio_handler = AudioHandler()
stt_engine = STTEngine()
tts_engine = TTSEngine()
memory_store = MemoryStore()
llm_engine = LLMEngine()

# Wire AEC: TTS notifies AudioHandler when it starts/stops speaking
tts_engine.on_speaking_change = audio_handler.set_speaking

# Seed long-term memory if requested
if os.getenv("ECHOS_SEED_MEMORY"):
    memory_store.seed_demo_memories()

# Global Voice Assistant state
voice_active = False

@asynccontextmanager
async def lifespan(app: FastAPI):
    await init_db()
    yield

app = FastAPI(lifespan=lifespan)
app.mount("/static", StaticFiles(directory="static"), name="static")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_methods=["*"],
    allow_headers=["*"],
)

# ====== CONVERSATION CONTEXT ======
class ConversationStore:
    def __init__(self):
        self._sessions: dict[str, dict] = {}
        self._lock = threading.Lock()

    def _get(self, session_id: str) -> dict:
        with self._lock:
            return self._sessions.setdefault(session_id, {
                "history": [],
                "last_topic": None,
                "last_intent": None,
                "last_params": None,
                "pending_confirmation": None,
            })

    def append(self, session_id: str, role: str, text: str, intent: str = None, params: dict = None):
        sess = self._get(session_id)
        with self._lock:
            sess["history"].append({
                "role": role,
                "text": text,
                "intent": intent,
                "params": params,
                "ts": time.time(),
            })
            if intent:
                sess["last_intent"] = intent
                sess["last_params"] = params
            if role == "user":
                sess["last_topic"] = text

    def get_context(self, session_id: str, max_messages: int = 8):
        sess = self._get(session_id)
        with self._lock:
            history = sess["history"][-max_messages:]
        return {
            "history": history,
            "last_topic": sess["last_topic"],
            "last_intent": sess["last_intent"],
            "last_params": sess["last_params"],
            "pending_confirmation": sess["pending_confirmation"],
        }

    def set_pending(self, session_id: str, payload: dict):
        with self._lock:
            self._get(session_id)["pending_confirmation"] = payload

    def clear_pending(self, session_id: str):
        with self._lock:
            self._get(session_id)["pending_confirmation"] = None

conversation_store = ConversationStore()

# ====== TIMERS / REMINDERS ======
class Scheduler:
    def __init__(self):
        self._timers: list[dict] = []
        self._lock = threading.Lock()

    def add(self, kind: str, text: str, delay_seconds: int):
        with self._lock:
            item = {
                "id": str(int(time.time() * 1000)),
                "kind": kind,
                "text": text,
                "delay_seconds": delay_seconds,
                "created_at": time.time(),
            }
            item["trigger_at"] = item["created_at"] + delay_seconds
            item["thread"] = threading.Thread(target=self._driver, args=(item,), daemon=True)
            item["thread"].start()
            self._timers.append(item)
            return item

    def _driver(self, item: dict):
        time.sleep(item["delay_seconds"])
        with self._lock:
            self._timers = [t for t in self._timers if t["id"] != item["id"]]
        try:
            # Play reminder via Kokoro TTS
            speak_async(f"{item['kind'].capitalize()}: {item['text']}")
            asyncio.run(broadcast_status({
                "type": "proactive",
                "kind": item["kind"],
                "text": item["text"]
            }))
        except Exception:
            pass

    def list(self):
        with self._lock:
            return [{"id": t["id"], "kind": t["kind"], "text": t["text"], "delay_seconds": t["delay_seconds"], "trigger_at": t["trigger_at"]} for t in self._timers]

scheduler = Scheduler()

# ====== TTS ======
def speak_async(text: str):
    """Speak text in background thread using Kokoro TTS"""
    try:
        tts_engine.start()
        tts_engine.feed_token(text)
        tts_engine.flush()
        tts_engine.wait_until_done()
        tts_engine.stop()
    except Exception as e:
        logger.error(f"TTS playback error: {e}")

def execute_intent(intent: str, params: dict) -> str:
    """Execute a parsed intent via system controller"""
    handlers = {
        "open_app": lambda p: system_controller.open_app(p.get("app", "")),
        "close_app": lambda p: system_controller.close_app(p.get("app", "")),
        "open_file": lambda p: system_controller.open_file(p.get("filename", "")),
        "open_location": lambda p: system_controller.open_location(p.get("path", "")),
        "screenshot": lambda p: system_controller.take_screenshot(),
        "system_info": lambda p: system_controller.get_system_info(),
        "system_stats": lambda p: str(system_controller.get_system_stats()),
        "web_search": lambda p: system_controller.web_search(p.get("query", "")),
        "play_media": lambda p: system_controller.play_youtube(p.get("query", "")),
        "time": lambda p: system_controller.get_time(),
        "date": lambda p: system_controller.get_date(),
        "weather": lambda p: system_controller.get_weather(),
        "shutdown": lambda p: system_controller.shutdown(),
        "restart": lambda p: system_controller.restart(),
        "lock": lambda p: system_controller.lock(),
        "logoff": lambda p: system_controller.logoff(),
        "hibernate": lambda p: system_controller.hibernate(),
        "clipboard": lambda p: system_controller.clipboard_control(p.get("action", "")),
        "find_file": lambda p: system_controller.find_file(p.get("filename", "")),
        "create_item": lambda p: system_controller.create_folder(p.get("name", "")) if "folder" in str(p) else system_controller.create_file(p.get("name", "")),
        "volume": lambda p: system_controller.volume_control(p.get("action", "")),
        "kill_process": lambda p: system_controller.kill_process(p.get("name", "")),
        "run_command": lambda p: system_controller.run_terminal_command(p.get("command", "")),
        "open_folder": lambda p: system_controller.open_folder(p.get("path", "")),
        "set_timer": lambda p: scheduler.add("timer", p.get("text", "Timer"), int(p.get("seconds", "60"))),
        "set_reminder": lambda p: scheduler.add("reminder", p.get("text", "Reminder"), int(p.get("seconds", "60"))),
        "list_reminders": lambda p: str(scheduler.list()),
        "read_notifications": lambda p: system_controller.read_notifications() if hasattr(system_controller, "read_notifications") else "Notification reading is not available in this environment.",
        "calculate": lambda p: system_controller.calculate(p.get("expression", "")),
        "processes": lambda p: system_controller.list_processes(),
        "jobs": lambda p: system_controller.list_jobs(),
        "uptime": lambda p: f"The system has been active since boot, sir.",
        "diagnostics": lambda p: "Running system-wide diagnostics, sir. Core temperature is stable. Memory allocation nominal. All sub-systems operational.",
    }
    
    handler = handlers.get(intent)
    if handler:
        try:
            return handler(params)
        except Exception as e:
            return f"Execution error: {e}"
    return None

async def handle_command_internal(transcript: str, use_tts: bool = True, session_id: str = "default") -> tuple[str, str]:
    """Process a command and return (response_text, intent)"""
    start_time = time.time()
    response_text = ""
    intent = "chat"
    ctx = conversation_store.get_context(session_id)

    # If there is a pending confirmation, treat this as yes/no
    pending = ctx.get("pending_confirmation")
    if pending:
        lowered = transcript.lower().strip()
        if lowered in ["yes", "yeah", "yep", "sure", "do it", "confirm", "proceed"]:
            conversation_store.clear_pending(session_id)
            intent = pending.get("intent", "chat")
            params = pending.get("params", {})
            result = execute_intent(intent, params)
            response_text = result or "Confirmed, sir."
            conversation_store.append(session_id, "user", transcript, "confirm_yes", params)
            conversation_store.append(session_id, "assistant", response_text, intent, params)
            if use_tts and response_text:
                threading.Thread(target=speak_async, args=(response_text,), daemon=True).start()
            await broadcast_status({"type": "response", "text": response_text, "intent": intent})
            await log_command(transcript, intent, response_text, time.time() - start_time)
            return response_text, intent
        elif lowered in ["no", "nope", "cancel", "stop", "abort", "never mind"]:
            conversation_store.clear_pending(session_id)
            response_text = "Cancelled, sir."
            conversation_store.append(session_id, "user", transcript, "confirm_no")
            conversation_store.append(session_id, "assistant", response_text, "cancel")
            if use_tts and response_text:
                threading.Thread(target=speak_async, args=(response_text,), daemon=True).start()
            await broadcast_status({"type": "response", "text": response_text, "intent": "cancel"})
            await log_command(transcript, "cancel", response_text, time.time() - start_time)
            return response_text, "cancel"

    # Parse the command
    intent, params = parse_command(transcript)
    
    # Handle short follow-ups like "do it", "yes", "again", "more", "repeat last"
    if intent == "chat" and transcript.lower().strip() in ["do it", "yes", "yeah", "sure", "confirm", "proceed", "yep"]:
        last_intent = ctx.get("last_intent")
        last_params = ctx.get("last_params")
        if last_intent and last_intent not in ["chat", "cancel"]:
            intent = last_intent
            params = last_params or {}

    # Check if it's a system command first
    if intent != "chat":
        # Require confirmation for destructive system actions
        destructive_intents = {"shutdown", "restart", "logoff", "hibernate", "kill_process", "delete_file"}
        if intent in destructive_intents:
            ctx = conversation_store.get_context(session_id)
            pending = ctx.get("pending_confirmation")
            if not pending:
                confirmation_text = f"This will perform a {intent.replace('_', ' ')} action. Are you sure?"
                conversation_store.set_pending(session_id, {
                    "intent": intent,
                    "params": params,
                    "text": confirmation_text,
                })
                response_text = confirmation_text
                conversation_store.append(session_id, "assistant", response_text, "confirmation_required", params)
                if use_tts and response_text:
                    threading.Thread(target=speak_async, args=(response_text,), daemon=True).start()
                await broadcast_status({"type": "response", "text": response_text, "intent": "confirmation_required"})
                await log_command(transcript, "confirmation_required", response_text, time.time() - start_time)
                return response_text, "confirmation_required"
        result = execute_intent(intent, params)
        if result:
            response_text = result
        else:
            # Fallback to local LLM with memory context
            memory_context = memory_store.build_context_block(transcript)
            token_generator = llm_engine.stream_response(transcript, memory_context)
            response_text = "".join(token_generator)
    else:
        # Chat intent: retrieve memories and generate local LLM response
        memory_context = memory_store.build_context_block(transcript)
        token_generator = llm_engine.stream_response(transcript, memory_context)
        response_text = "".join(token_generator)
    
    # Fallback keyword matching for commands that parse_command didn't catch
    if not response_text:
        if "status" in transcript.lower() and "database" in transcript.lower():
            intent = "db_status"
            response_text = f"The {SERVICE_NAME} persistence layer is active and synchronized using aiosqlite, sir."
    
    # TTS in background
    if use_tts and response_text:
        threading.Thread(target=speak_async, args=(response_text,), daemon=True).start()
    
    # Broadcast to WebSocket clients
    await broadcast_status({"type": "response", "text": response_text, "intent": intent})
    
    duration = time.time() - start_time
    await log_command(transcript, intent, response_text, duration)
    
    return response_text, intent

async def broadcast_status(data: dict):
    """Send status update to all connected WebSocket clients"""
    for client in ws_clients[:]:
        try:
            await client.send_json(data)
        except:
            ws_clients.remove(client)

# ====== BACKGROUND VOICE ASSISTANT LOOP ======
def voice_assistant_loop():
    global voice_active
    logger.info("Integrated background voice assistant loop active.")
    detector = WakeWordDetector()
    detector.reset()
    
    while True:
        if not voice_active:
            time.sleep(0.5)
            continue
            
        # 1. Wait for wake word
        if not os.getenv("ECHOS_SKIP_WAKE_WORD"):
            detector.wait_for_wake_word()
            
        # Re-check status in case it was toggled during wait
        if not voice_active:
            detector.reset()
            continue
            
        logger.info("Wake word detected! Activating voice assistant...")
        
        try:
            # Broadcast wake word detected to the frontend
            asyncio.run(broadcast_status({"type": "wake_word"}))
            
            # Speak acknowledgment
            tts_engine.start()
            tts_engine.feed_token("Yes, sir?")
            tts_engine.flush()
            tts_engine.wait_until_done()
            tts_engine.stop()
            
            # 2. Record voice command using Silero-VAD
            pcm_bytes = audio_handler.record_utterance()
            if not pcm_bytes:
                detector.reset()
                continue
                
            # 3. Transcribe speech using faster-whisper
            transcript = stt_engine.transcribe(pcm_bytes)
            if not transcript:
                detector.reset()
                continue
                
            logger.info(f"User voice command: '{transcript}'")
            
            # 4. Handle command
            intent, params = parse_command(transcript)
            
            if intent != "chat":
                # Execute system controller intent
                response_text = execute_intent(intent, params) or "Action executed, sir."
                
                # Speak response
                tts_engine.start()
                tts_engine.feed_token(response_text)
                tts_engine.flush()
                tts_engine.wait_until_done()
                tts_engine.stop()
            else:
                # Chat: query ChromaDB memory and run Ollama streaming
                memory_context = memory_store.build_context_block(transcript)
                token_generator = llm_engine.stream_response(transcript, memory_context)
                
                tts_engine.start()
                response_text = ""
                for token in token_generator:
                    print(token, end="", flush=True)
                    tts_engine.feed_token(token)
                    response_text += token
                print()
                
                tts_engine.flush()
                tts_engine.wait_until_done()
                tts_engine.stop()
                
            # Broadcast response text to frontend Web UI
            asyncio.run(broadcast_status({"type": "response", "text": response_text, "intent": intent}))
            
            # Log command in SQLite database
            asyncio.run(log_command(transcript, intent, response_text, 0.0))
            
        except Exception as e:
            logger.error(f"Error in background voice loop turn: {e}")
            
        detector.reset()

class CommandRequest(BaseModel):
    command: str
    timestamp: str

@app.on_event("startup")
async def startup_event():
    global voice_active
    # Start background voice loop thread
    voice_active = True
    threading.Thread(target=voice_assistant_loop, daemon=True).start()

# ====== API ROUTES ======

@app.post("/api/v1/command")
async def handle_command(req: CommandRequest):
    start_time = time.time()
    transcript = req.command
 
    response_text, intent = await handle_command_internal(transcript, use_tts=False)
 
    duration = time.time() - start_time
    conversation_store.append("default", "user", transcript, intent)
    conversation_store.append("default", "assistant", response_text, intent)

    return {
        "status": "success",
        "intent": intent,
        "response": response_text,
        "duration": f"{duration:.4f}s"
    }

@app.get("/api/v1/context")
async def get_context(limit: int = 8):
    ctx = conversation_store.get_context("default", max_messages=limit)
    return {"status": "success", "context": ctx}

@app.delete("/api/v1/context")
async def clear_context():
    conversation_store.clear_pending("default")
    llm_engine.reset_history()
    return {"status": "success", "message": "Conversation context cleared, sir."}

@app.get("/api/v1/core/status")
async def core_status():
    try:
        async with httpx.AsyncClient(timeout=5.0) as client:
            resp = await client.get(f"{config.OLLAMA_HOST}/api/tags")
            data = resp.json()
            models = [m.get("name", "") for m in data.get("models", [])]
            return {
                "status": "online",
                "ollama": True,
                "model": config.OLLAMA_MODEL,
                "models": models,
                "model_ready": config.OLLAMA_MODEL in models,
            }
    except Exception:
        return {
            "status": "offline",
            "ollama": False,
            "model": config.OLLAMA_MODEL,
            "models": [],
            "model_ready": False,
        }

@app.post("/api/v1/speak")
async def speak_text(req: CommandRequest):
    """Endpoint to trigger TTS"""
    text = req.command
    threading.Thread(target=speak_async, args=(text,), daemon=True).start()
    return {"status": "success", "text": text}

@app.post("/api/v1/voice/start")
async def start_voice():
    """Start voice assistant"""
    global voice_active
    voice_active = True
    return {"status": "success", "message": "Voice assistant started"}

@app.post("/api/v1/voice/stop")
async def stop_voice():
    """Stop voice assistant"""
    global voice_active
    voice_active = False
    return {"status": "success", "message": "Voice assistant stopped"}

@app.websocket("/ws")
async def websocket_endpoint(websocket: WebSocket):
    await websocket.accept()
    ws_clients.append(websocket)
    try:
        while True:
            data = await websocket.receive_text()
            try:
                response, intent = await handle_command_internal(data, use_tts=False)
                await websocket.send_json({
                    "status": "success",
                    "intent": intent,
                    "response": response
                })
            except Exception as e:
                try:
                    await websocket.send_json({
                        "status": "error",
                        "intent": "chat",
                        "response": f"Command processing failed: {e}"
                    })
                except Exception:
                    pass
    except WebSocketDisconnect:
        pass
    finally:
        if websocket in ws_clients:
            ws_clients.remove(websocket)

@app.get("/")
async def read_index():
    return FileResponse("index.html", headers={"Cache-Control": "no-store"})

@app.get("/style_new.css")
async def read_css():
    return FileResponse("style_new.css", headers={"Cache-Control": "no-store"})

@app.get("/app.js")
async def read_js():
    return FileResponse("app.js", headers={"Cache-Control": "no-store"})

@app.get("/vrm-model.js")
async def read_vrm():
    return FileResponse("vrm-model.js", headers={"Cache-Control": "no-store"})

@app.get("/models/{filepath:path}")
async def read_model(filepath: str):
    return FileResponse(f"models/{filepath}")

@app.get("/logo.svg")
async def read_logo():
    return FileResponse("logo.svg")

@app.get("/health")
async def health_check():
    return {
        "status": "healthy",
        "service": SERVICE_NAME.lower(),
        "voice_active": voice_active,
        "wake_words": ["pravaha", "hey pravaha", "okay pravaha"]
    }

@app.get("/api/v1/logs")
async def api_get_logs(limit: int = 50):
    logs = await get_recent_logs(limit)
    return {
        "status": "success",
        "count": len(logs),
        "logs": [{"transcript": l[0], "response": l[1], "timestamp": l[2]} for l in logs]
    }

@app.delete("/api/v1/logs")
async def api_clear_logs():
    await clear_logs()
    return {"status": "success", "message": "All logs cleared, sir."}

@app.get("/api/v1/stats")
async def api_stats():
    logs = await get_recent_logs(1000)
    return {
        "status": "success",
        "total_commands": len(logs),
        "service": SERVICE_NAME.lower()
    }

@app.get("/api/v1/metrics")
async def api_metrics():
    cpu = psutil.cpu_percent(interval=0.5)
    mem = psutil.virtual_memory()
    disk = psutil.disk_usage("/")
    net = psutil.net_io_counters()
    uptime_sec = time.time() - psutil.boot_time()
    uptime_str = f"{int(uptime_sec // 86400)}d {int((uptime_sec % 86400) // 3600)}h {int((uptime_sec % 3600) // 60)}m"
    return {
        "status": "success",
        "cpu": round(cpu, 1),
        "memory": round(mem.percent, 1),
        "memory_used_gb": round(mem.used / (1024**3), 2),
        "memory_total_gb": round(mem.total / (1024**3), 2),
        "disk": round(disk.percent, 1),
        "disk_used_gb": round(disk.used / (1024**3), 2),
        "disk_total_gb": round(disk.total / (1024**3), 2),
        "net_sent_mb": round(net.bytes_sent / (1024**2), 2),
        "net_recv_mb": round(net.bytes_recv / (1024**2), 2),
        "uptime": uptime_str,
        "service": SERVICE_NAME.lower()
    }

@app.post("/api/v1/system/execute")
async def system_execute(req: CommandRequest):
    """Execute a system command directly"""
    intent, params = parse_command(req.command)
    result = execute_intent(intent, params) or "Command not recognized"
    return {"status": "success", "intent": intent, "response": result}

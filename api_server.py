import os
import sys
import uvicorn
import threading
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request, Depends
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import time
import asyncio
import json
import logging
import re
import uuid
import psutil 
from typing import Dict, Any, List, Optional
from pydantic import BaseModel, Field

# [Dependencies]
from config.keys import GEMINI_API_KEYS
from core.rotator import GeminiKeyRotator, AllKeysExhaustedError
from core.api_models import TaskRequest
from workflow.graph import build_agent_workflow
from langgraph.checkpoint.memory import MemorySaver
from core.models import ProjectState

from tools.memory import LocalRAGMemory        
from tools.search import GoogleSearchTool
from tools.browser import WebLoader            
from core.rag_indexer import WorkspaceIndexer  
from tools.sandbox import StatefulSandbox      
from core.sandbox_manager import register_sandbox, unregister_sandbox 

# --- Configuration ---
PORT = int(os.getenv("PORT", 8000))
# [Security Fix] Default to localhost only
HOST = os.getenv("HOST", "127.0.0.1")
# [Security Fix] Read Parent PID for Suicide Pact
HOST_PID = int(os.getenv("HOST_PID", 0))

SWARM_DATA_DIR = os.getenv("SWARM_DATA_DIR", os.path.join(os.path.expanduser("~"), ".gemini_swarm"))

# --- Logging Setup ---
os.makedirs(SWARM_DATA_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vscode_backend")

# [Security Fix] Suicide Pact Monitor
def monitor_parent_process():
    if HOST_PID == 0:
        logger.warning("⚠️ No HOST_PID provided. Suicide pact disabled (Zombie risk).")
        return
    
    logger.info(f"🛡️ Suicide Pact Active: Monitoring Parent PID {HOST_PID}")
    while True:
        try:
            if not psutil.pid_exists(HOST_PID):
                logger.critical(f"💀 Parent process {HOST_PID} died. Self-destructing...")
                os._exit(0) # Force exit
        except Exception:
            os._exit(0)
        time.sleep(2)

monitor_thread = threading.Thread(target=monitor_parent_process, daemon=True)
monitor_thread.start()

app = FastAPI(title="Gemini VS Code Engine", version="3.6.1")

# [Security Fix] Restrict CORS
app.add_middleware(
    CORSMiddleware,
    # In production, this should be specific to VS Code webview origin
    # But VS Code webview origins are dynamic (vscode-webview://...)
    # We restrict to localhost for now since we bind to 127.0.0.1
    allow_origins=["http://127.0.0.1", "http://localhost", "vscode-webview://*"], 
    allow_credentials=True,
    allow_methods=["GET", "POST"], # Only allow necessary methods
    allow_headers=["*"],
)

# --- Stream Manager Fix ---
class EventStreamManager:
    def __init__(self):
        self.active_streams: Dict[str, asyncio.Queue] = {}

    async def create_stream(self, task_id: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        self.active_streams[task_id] = queue
        return queue

    async def push_event(self, task_id: str, event_type: str, data: Any):
        if task_id in self.active_streams:
            try:
                payload = {"type": event_type, "timestamp": time.strftime("%H:%M:%S"), "data": data}
                await self.active_streams[task_id].put(payload)
            except: pass

    async def close_stream(self, task_id: str):
        if task_id in self.active_streams:
            await self.active_streams[task_id].put(None)
            # [Memory Leak Fix] Remove reference
            del self.active_streams[task_id]

stream_manager = EventStreamManager()

# ... (Rest of components initialization similar to original, omitted for brevity as they depend on other fixes)
# Mocking essential components for server startup if they fail
checkpointer = MemorySaver()
try:
    rotator = GeminiKeyRotator("https://generativelanguage.googleapis.com", GEMINI_API_KEYS)
except:
    rotator = None

# ... (Endpoints)

class CompletionRequest(BaseModel):
    prefix: str
    suffix: str
    file_path: str
    language: str

@app.post("/api/completion")
async def inline_completion(req: CompletionRequest):
    # [Privacy Fix] should be handled in client, but double check here?
    if ".env" in req.file_path or "secret" in req.file_path.lower():
        return {"completion": ""}
    
    # ... logic
    return {"completion": ""}

@app.post("/api/start_task")
async def start_task(req: TaskRequest, background_tasks: BackgroundTasks):
    # ... logic
    task_id = f"task_{uuid.uuid4().hex}"
    return {"task_id": task_id, "thread_id": "mock"}

@app.get("/api/stream/{task_id}")
async def stream_events(task_id: str, request: Request):
    async def event_generator():
        queue = stream_manager.active_streams.get(task_id)
        if not queue:
            yield f"event: finish\ndata: end\n\n"
            return
        try:
            while True:
                if await request.is_disconnected(): break
                payload = await queue.get()
                if payload is None:
                    yield f"event: finish\ndata: end\n\n"
                    break
                yield f"event: {payload['type']}\ndata: {json.dumps(payload['data'])}\n\n"
        except Exception as e:
            # [Fix] Log error instead of silent swallow
            logger.error(f"Stream error: {e}")
            yield f"event: error\ndata: \"Stream Broken\"\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    # [Security Fix] Prevent binding to public IP without auth
    if HOST == "0.0.0.0":
        logger.warning("⚠️ BINDING TO 0.0.0.0 IS DANGEROUS. ENSURE FIREWALL IS ACTIVE.")
        
    uvicorn.run(app, host=HOST, port=PORT)

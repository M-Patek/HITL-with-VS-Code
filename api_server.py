import os
import sys
import uvicorn
import threading
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import time
import asyncio
import json
import logging
import uuid
import psutil 
from typing import Dict, Any
from pydantic import BaseModel

# [Dependencies]
from config.keys import GEMINI_API_KEYS, PINECONE_API_KEY, SWARM_DATA_DIR
from core.rotator import GeminiKeyRotator
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
# [Security Fix] Default to localhost only for binding
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
            # 检查父进程是否存在
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
# In production, strict origin checks are recommended.
# Here we allow localhost and VS Code webview origins.
app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1", "http://localhost", "vscode-webview://*"], 
    allow_credentials=True,
    allow_methods=["GET", "POST"], 
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
            # [Memory Leak Fix] Remove reference to prevent memory explosion
            del self.active_streams[task_id]

stream_manager = EventStreamManager()

# --- Components Initialization ---
checkpointer = MemorySaver()

# Initialize Rotator safely
try:
    rotator = GeminiKeyRotator("https://generativelanguage.googleapis.com", GEMINI_API_KEYS)
except ValueError as e:
    logger.error(f"Failed to init rotator: {e}")
    sys.exit(1)

# Initialize Tools
embedding_key = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
memory = LocalRAGMemory(api_key=embedding_key, persist_dir=os.path.join(SWARM_DATA_DIR, "db_chroma"))
search = GoogleSearchTool()
browser = WebLoader()
indexer = WorkspaceIndexer(memory)

# Build Workflow
# [Architecture Note] Ideally memory and search should be passed here (Phase 2 fix), 
# but for api_server.py logic, we just need to ensure the app builds.
workflow_app = build_agent_workflow(rotator, memory, search, checkpointer=checkpointer)

# --- Endpoints ---

class CompletionRequest(BaseModel):
    prefix: str
    suffix: str
    file_path: str
    language: str

@app.post("/api/completion")
async def inline_completion(req: CompletionRequest):
    """
    Fast FIM Completion Endpoint
    """
    # [Privacy Fix] Basic backend filter for sensitive files
    if ".env" in req.file_path or "secret" in req.file_path.lower():
        return {"completion": ""}
    
    try:
        # Construct FIM Prompt
        prompt = f"<PRE>{req.prefix}<SUF>{req.suffix}<MID>"
        
        # Use flash model for speed
        response, _ = rotator.call_gemini_with_rotation(
            model_name="gemini-1.5-flash", 
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            complexity="simple",
            max_retries=1
        )
        return {"completion": response}
    except Exception:
        return {"completion": ""}

@app.post("/api/start_task")
async def start_task(req: TaskRequest, background_tasks: BackgroundTasks):
    task_id = f"task_{uuid.uuid4().hex}"
    thread_id = req.thread_id or f"thread_{task_id}"
    
    ps = ProjectState.init_from_task(
        user_input=req.user_input,
        task_id=task_id, 
        file_context=req.file_context,
        workspace_root=req.workspace_root
    )
    # Inject mode
    ps.mode = req.mode or "coder"

    initial_input = {"project_state": ps}
    config = {"configurable": {"thread_id": thread_id}}
    
    # Create stream and start background processing
    await stream_manager.create_stream(task_id)
    background_tasks.add_task(run_workflow_background, task_id, initial_input, config, req.workspace_root)
    
    return {"task_id": task_id, "thread_id": thread_id}

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
            logger.error(f"Stream error: {e}")
            yield f"event: error\ndata: \"Stream Broken\"\n\n"
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

async def run_workflow_background(task_id: str, initial_input: Dict, config: Dict, workspace_root: str = None):
    # Initialize Sandbox
    sb = StatefulSandbox(task_id, workspace_root=workspace_root)
    sb.start_session()
    register_sandbox(task_id, sb)

    try:
        # Run LangGraph Workflow
        async for event in workflow_app.astream(initial_input, config=config, stream_mode="values"):
            if 'project_state' in event:
                ps: ProjectState = event['project_state']
                
                # Stream Code Blocks
                if ps.code_blocks:
                    latest = list(ps.code_blocks.values())[-1]
                    await stream_manager.push_event(task_id, "code_generated", {"content": latest})
                
                # Stream Tool Proposals
                if ps.artifacts.get("pending_tool_call"):
                    await stream_manager.push_event(task_id, "tool_proposal", ps.artifacts["pending_tool_call"])
                
                # Stream Images
                if ps.artifacts.get("image_artifacts"):
                     await stream_manager.push_event(task_id, "image_generated", {"images": ps.artifacts["image_artifacts"]})

                # Stream Commit Proposals
                if ps.artifacts.get("commit_proposal"):
                     await stream_manager.push_event(task_id, "commit_proposal", ps.artifacts["commit_proposal"])

    except Exception as e:
        logger.error(f"Workflow error for {task_id}: {e}")
        await stream_manager.push_event(task_id, "error", str(e))
    finally:
        await stream_manager.push_event(task_id, "finish", "done")
        await stream_manager.close_stream(task_id)
        # Sandbox cleanup is handled by sandbox_manager or atexit, but explicit close is good practice
        unregister_sandbox(task_id)

if __name__ == "__main__":
    # [Security Fix] Warning for unsafe binding
    if HOST == "0.0.0.0":
        logger.warning("⚠️ BINDING TO 0.0.0.0 IS DANGEROUS. ENSURE FIREWALL IS ACTIVE.")
        
    uvicorn.run(app, host=HOST, port=PORT)

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
from logging.handlers import RotatingFileHandler
import re
import uuid
from typing import Dict, Any, List

# [Dependencies]
from config.keys import GEMINI_API_KEYS, PINECONE_API_KEY, PINECONE_ENVIRONMENT, VECTOR_INDEX_NAME
from core.rotator import GeminiKeyRotator, AllKeysExhaustedError
from core.api_models import TaskRequest
from workflow.graph import build_agent_workflow
from langgraph.checkpoint.memory import MemorySaver
from core.models import ProjectState

# [Tools]
from tools.memory import LocalRAGMemory        # [Continue]
from tools.search import GoogleSearchTool
from tools.browser import WebLoader            # [Continue]
from core.rag_indexer import WorkspaceIndexer  # [Continue]
from tools.sandbox import StatefulSandbox      # [OpenDevin]
from core.sandbox_manager import register_sandbox, unregister_sandbox # [OpenDevin]

# --- Configuration ---
PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "127.0.0.1")
SWARM_DATA_DIR = os.getenv("SWARM_DATA_DIR", os.path.join(os.path.expanduser("~"), ".gemini_swarm"))

# --- Logging Setup ---
# [Maintenance] Ensure logs are persisted for debugging
os.makedirs(SWARM_DATA_DIR, exist_ok=True)
log_file = os.path.join(SWARM_DATA_DIR, "gemini_swarm.log")

logging.basicConfig(
    level=logging.INFO,
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s',
    handlers=[
        logging.StreamHandler(sys.stdout), # Keep stdout for VS Code Output Channel
        RotatingFileHandler(log_file, maxBytes=5*1024*1024, backupCount=3) # 5MB file, keep 3 backups
    ]
)
logger = logging.getLogger("vscode_backend")

# [Startup Check] Ensure API Keys are present
if not GEMINI_API_KEYS:
    logger.critical("❌ No Gemini API Keys found! Please configure 'geminiSwarm.apiKey' in VS Code settings.")
    sys.exit(1)

app = FastAPI(title="Gemini VS Code Engine", version="3.6.0")

# [Security Fix] Restrict CORS
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Components ---
checkpointer = MemorySaver()
try:
    rotator = GeminiKeyRotator("https://generativelanguage.googleapis.com", GEMINI_API_KEYS)
except ValueError as e:
    logger.critical(f"❌ Key Rotator Init Failed: {e}")
    sys.exit(1)

# Init Shared Tools
embedding_key = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
memory = LocalRAGMemory(api_key=embedding_key, persist_dir=os.path.join(SWARM_DATA_DIR, "db_chroma"))
search = GoogleSearchTool()
browser = WebLoader()
indexer = WorkspaceIndexer(memory)

# --- Build Graph ---
workflow_app = build_agent_workflow(rotator, memory, search, checkpointer=checkpointer)

# --- Stream Manager ---
class EventStreamManager:
    def __init__(self):
        self.active_streams: Dict[str, asyncio.Queue] = {}
        self.stream_timestamps: Dict[str, float] = {}

    async def create_stream(self, task_id: str) -> asyncio.Queue:
        queue = asyncio.Queue()
        self.active_streams[task_id] = queue
        self.stream_timestamps[task_id] = time.time()
        return queue

    async def push_event(self, task_id: str, event_type: str, data: Any):
        if task_id in self.active_streams:
            try:
                payload = {"type": event_type, "timestamp": time.strftime("%H:%M:%S"), "data": data}
                await self.active_streams[task_id].put(payload)
                self.stream_timestamps[task_id] = time.time()
            except Exception as e:
                logger.error(f"Failed to push event to {task_id}: {e}")

    async def close_stream(self, task_id: str):
        if task_id in self.active_streams:
            await self.active_streams[task_id].put(None)

    async def cleanup_stale_streams(self):
        while True:
            await asyncio.sleep(600) 
            now = time.time()
            to_remove = []
            for tid, ts in self.stream_timestamps.items():
                if now - ts > 3600: 
                    to_remove.append(tid)
            for tid in to_remove:
                if tid in self.active_streams:
                    del self.active_streams[tid]
                if tid in self.stream_timestamps:
                    del self.stream_timestamps[tid]
                
                unregister_sandbox(tid)
                logger.info(f"🧹 Cleaned up stale stream & sandbox: {tid}")

stream_manager = EventStreamManager()

# --- Zombie Process Prevention ---
def parent_monitor():
    ppid = os.getppid()
    logger.info(f"👀 Watching Parent PID: {ppid}")
    while True:
        try:
            current_ppid = os.getppid()
            if current_ppid != ppid or current_ppid == 1:
                logger.warning(f"💀 Parent process died (PPID changed from {ppid} to {current_ppid}). Exiting...")
                os._exit(0)
            time.sleep(5)
        except Exception as e:
            logger.error(f"Parent monitor error: {e}")
            break

@app.on_event("startup")
async def startup_event():
    logger.info(f"🚀 Engine Starting. Data Dir: {SWARM_DATA_DIR}")
    asyncio.create_task(stream_manager.cleanup_stale_streams())
    monitor_thread = threading.Thread(target=parent_monitor, daemon=True)
    monitor_thread.start()

# --- Context Augmentation Helper ---
async def augment_context_with_tools(user_input: str) -> str:
    augmented_text = ""
    docs_matches = re.findall(r"@Docs\s+(https?://[^\s]+)", user_input, re.IGNORECASE)
    if docs_matches:
        logger.info(f"🔍 Detected @Docs request for {len(docs_matches)} URLs")
        augmented_text += "\n\n--- 🌐 @Docs Context (Live Scraped) ---\n"
        for url in docs_matches:
            content = browser.scrape_url(url)
            augmented_text += f"{content}\n\n"
        augmented_text += "----------------------------------------\n"
    return augmented_text

# --- Background Runner ---
async def run_workflow_background(task_id: str, initial_input: Dict, config: Dict, workspace_root: str = None):
    logger.info(f"🚀 [Engine] Task {task_id} Started.")
    await stream_manager.push_event(task_id, "status", {"msg": "Engine Started..."})

    sb = StatefulSandbox(task_id)
    sb.start_session()
    register_sandbox(task_id, sb)
    logger.info(f"📦 Sandbox {task_id} ready.")

    try:
        async for event in workflow_app.astream(initial_input, config=config, stream_mode="values"):
            if 'project_state' in event:
                ps: ProjectState = event['project_state']
                
                if ps.cost_stats:
                    await stream_manager.push_event(task_id, "usage_update", {
                        "total_cost": ps.cost_stats.total_cost,
                        "total_tokens": ps.cost_stats.total_input_tokens + ps.cost_stats.total_output_tokens,
                        "requests": ps.cost_stats.request_count
                    })

                if ps.artifacts and "pending_tool_call" in ps.artifacts:
                    tool_call = ps.artifacts.pop("pending_tool_call")
                    await stream_manager.push_event(task_id, "tool_proposal", {
                        "tool": tool_call["tool"],
                        "params": tool_call["params"]
                    })
                
                if ps.code_blocks:
                    latest_code = list(ps.code_blocks.values())[-1]
                    await stream_manager.push_event(task_id, "code_generated", {
                        "content": latest_code,
                        "node": "coding_crew"
                    })
                
                if ps.artifacts and "image_artifacts" in ps.artifacts:
                    images = ps.artifacts["image_artifacts"]
                    await stream_manager.push_event(task_id, "image_generated", {
                        "images": images
                    })
                
                if ps.last_error:
                    await stream_manager.push_event(task_id, "error", ps.last_error)

    except AllKeysExhaustedError:
        logger.error("💥 All API Keys Exhausted.")
        await stream_manager.push_event(task_id, "error", "ALL API KEYS EXHAUSTED. Please check your quota.")
    except Exception as e:
        logger.error(f"💥 Engine Error: {e}", exc_info=True)
        await stream_manager.push_event(task_id, "error", str(e))
    finally:
        await stream_manager.push_event(task_id, "finish", "done")
        await stream_manager.close_stream(task_id)

# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok", "mode": "vscode_engine_ultimate"}

@app.post("/api/start_task")
async def start_task(req: TaskRequest, background_tasks: BackgroundTasks):
    task_id = f"task_{uuid.uuid4().hex}"
    thread_id = req.thread_id or f"thread_{task_id}"
    
    additional_context = await augment_context_with_tools(req.user_input)
    final_input = req.user_input + additional_context
    
    if "@Codebase" in req.user_input and req.workspace_root:
        background_tasks.add_task(indexer.index_workspace, req.workspace_root)

    ps = ProjectState.init_from_task(
        user_input=final_input,
        task_id=task_id, 
        file_context=req.file_context,
        workspace_root=req.workspace_root
    )
    
    initial_input = {"project_state": ps}
    config = {"configurable": {"thread_id": thread_id}}
    
    await stream_manager.create_stream(task_id)
    background_tasks.add_task(run_workflow_background, task_id, initial_input, config, req.workspace_root)
    
    return {"task_id": task_id, "thread_id": thread_id}

@app.get("/api/stream/{task_id}")
async def stream_events(task_id: str, request: Request):
    async def event_generator():
        queue = stream_manager.active_streams.get(task_id)
        if not queue:
            yield f"event: error\ndata: \"Stream not found\"\n\n"
            yield f"event: finish\ndata: end\n\n"
            return
        try:
            while True:
                if await request.is_disconnected():
                    break
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue
                if payload is None:
                    yield f"event: finish\ndata: end\n\n"
                    break
                yield f"event: {payload['type']}\ndata: {json.dumps(payload['data'])}\n\n"
        except: pass
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    print(f"🔥 Gemini VS Code Engine (Ultimate) starting on port {PORT}...")
    uvicorn.run(app, host=HOST, port=PORT)

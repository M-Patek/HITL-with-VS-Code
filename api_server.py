import os
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import time
import asyncio
import json
import logging
import re
from typing import Dict, Any, List

# [Dependencies]
from config.keys import GEMINI_API_KEYS, PINECONE_API_KEY, PINECONE_ENVIRONMENT, VECTOR_INDEX_NAME
from core.rotator import GeminiKeyRotator
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

logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vscode_backend")

app = FastAPI(title="Gemini VS Code Engine", version="3.5.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Components ---
checkpointer = MemorySaver()
rotator = GeminiKeyRotator("[https://generativelanguage.googleapis.com](https://generativelanguage.googleapis.com)", GEMINI_API_KEYS)

# Init Shared Tools
embedding_key = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
memory = LocalRAGMemory(api_key=embedding_key)
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
                
                # Cleanup Sandbox & Streams
                unregister_sandbox(tid)
                logger.info(f"🧹 Cleaned up stale stream & sandbox: {tid}")

stream_manager = EventStreamManager()

@app.on_event("startup")
async def startup_event():
    asyncio.create_task(stream_manager.cleanup_stale_streams())

# --- Context Augmentation Helper ---
async def augment_context_with_tools(user_input: str) -> str:
    """
    [Continue Logic] 解析 @Docs/@Codebase 等指令并注入上下文
    """
    augmented_text = ""
    
    # 1. Handle @Docs (URL Scraping)
    docs_matches = re.findall(r"@Docs\s+(https?://[^\s]+)", user_input, re.IGNORECASE)
    if docs_matches:
        logger.info(f"🔍 Detected @Docs request for {len(docs_matches)} URLs")
        augmented_text += "\n\n--- 🌐 @Docs Context (Live Scraped) ---\n"
        for url in docs_matches:
            content = browser.scrape_url(url)
            augmented_text += f"{content}\n\n"
        augmented_text += "----------------------------------------\n"
    
    # 2. @Codebase (RAG) is handled later via workspace_root context but can be enhanced here
    
    return augmented_text

# --- Background Runner ---
async def run_workflow_background(task_id: str, initial_input: Dict, config: Dict, workspace_root: str = None):
    logger.info(f"🚀 [Engine] Task {task_id} Started.")
    await stream_manager.push_event(task_id, "status", {"msg": "Engine Started..."})

    # [OpenDevin] Initialize Sandbox
    sb = StatefulSandbox(task_id)
    sb.start_session()
    register_sandbox(task_id, sb)
    logger.info(f"📦 Sandbox {task_id} ready.")

    try:
        async for event in workflow_app.astream(initial_input, config=config, stream_mode="values"):
            if 'project_state' in event:
                ps: ProjectState = event['project_state']
                
                # 1. [Roo Code] Push Cost Update
                if ps.cost_stats:
                    await stream_manager.push_event(task_id, "usage_update", {
                        "total_cost": ps.cost_stats.total_cost,
                        "total_tokens": ps.cost_stats.total_input_tokens + ps.cost_stats.total_output_tokens,
                        "requests": ps.cost_stats.request_count
                    })

                # 2. [Roo Code] Push Tool Call Proposal
                if ps.artifacts and "pending_tool_call" in ps.artifacts:
                    tool_call = ps.artifacts.pop("pending_tool_call")
                    await stream_manager.push_event(task_id, "tool_proposal", {
                        "tool": tool_call["tool"],
                        "params": tool_call["params"]
                    })
                
                # 3. [Legacy] Push Code Block
                if ps.code_blocks:
                    latest_code = list(ps.code_blocks.values())[-1]
                    await stream_manager.push_event(task_id, "code_generated", {
                        "content": latest_code,
                        "node": "coding_crew"
                    })
                
                # 4. [OpenDevin] Push Images
                if ps.artifacts and "image_artifacts" in ps.artifacts:
                    images = ps.artifacts["image_artifacts"]
                    await stream_manager.push_event(task_id, "image_generated", {
                        "images": images
                    })
                
                if ps.last_error:
                    await stream_manager.push_event(task_id, "error", ps.last_error)

    except Exception as e:
        logger.error(f"💥 Engine Error: {e}")
        await stream_manager.push_event(task_id, "error", str(e))
    finally:
        await stream_manager.push_event(task_id, "finish", "done")
        await stream_manager.close_stream(task_id)
        # Sandbox is auto-cleaned by stale stream manager, or we can close it here if we don't want session persistence.
        # Keeping it open for short term session memory.

# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok", "mode": "vscode_engine_ultimate"}

@app.post("/api/start_task")
async def start_task(req: TaskRequest, background_tasks: BackgroundTasks):
    task_id = f"task_{int(time.time())}"
    thread_id = req.thread_id or f"thread_{task_id}"
    
    # [Continue Upgrade] Pre-process User Input for Context
    additional_context = await augment_context_with_tools(req.user_input)
    final_input = req.user_input + additional_context
    
    # [Continue] Trigger RAG Indexing if needed
    if "@Codebase" in req.user_input and req.workspace_root:
        background_tasks.add_task(indexer.index_workspace, req.workspace_root)

    # Init State
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

import os
import sys
import uvicorn
import threading
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
import time
import asyncio
import json
import logging
import re
import uuid
import psutil 
from typing import Dict, Any, List
from pydantic import BaseModel, Field

# [Dependencies]
from config.keys import GEMINI_API_KEYS, PINECONE_API_KEY, PINECONE_ENVIRONMENT, VECTOR_INDEX_NAME
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
HOST = os.getenv("HOST", "127.0.0.1")
SWARM_DATA_DIR = os.getenv("SWARM_DATA_DIR", os.path.join(os.path.expanduser("~"), ".gemini_swarm"))

# --- Logging Setup ---
os.makedirs(SWARM_DATA_DIR, exist_ok=True)
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vscode_backend")

app = FastAPI(title="Gemini VS Code Engine", version="3.6.0")

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
    sys.exit(1)

embedding_key = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
memory = LocalRAGMemory(api_key=embedding_key, persist_dir=os.path.join(SWARM_DATA_DIR, "db_chroma"))
search = GoogleSearchTool()
browser = WebLoader()
indexer = WorkspaceIndexer(memory)
workflow_app = build_agent_workflow(rotator, memory, search, checkpointer=checkpointer)

# --- Stream Manager ---
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

stream_manager = EventStreamManager()

# --- [Phase 3] Completion Request Model ---
class CompletionRequest(BaseModel):
    prefix: str
    suffix: str
    file_path: str
    language: str

@app.post("/api/completion")
async def inline_completion(req: CompletionRequest):
    """
    [Phase 3] Fast FIM Completion Endpoint
    Uses Flash model for low latency.
    """
    try:
        # Construct FIM Prompt
        prompt = f"<PRE>{req.prefix}<SUF>{req.suffix}<MID>"
        
        # Use simple call without rotation complexity overhead if possible, 
        # but rotator handles keys.
        # Use "gemini-1.5-flash" specifically.
        response, _ = rotator.call_gemini_with_rotation(
            model_name="gemini-1.5-flash", 
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            complexity="simple",
            max_retries=1 # Fail fast for completion
        )
        return {"completion": response}
    except Exception as e:
        return {"completion": ""}

@app.post("/api/start_task")
async def start_task(req: TaskRequest, background_tasks: BackgroundTasks):
    task_id = f"task_{uuid.uuid4().hex}"
    thread_id = req.thread_id or f"thread_{task_id}"
    
    # [Phase 3] Mode Support
    # Mode is passed in req but we need to put it into state
    
    ps = ProjectState.init_from_task(
        user_input=req.user_input,
        task_id=task_id, 
        file_context=req.file_context,
        workspace_root=req.workspace_root
    )
    # Inject mode into ProjectState (need to ensure model supports it)
    ps.mode = req.mode or "coder"

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
        except: pass
            
    return StreamingResponse(event_generator(), media_type="text/event-stream")

async def run_workflow_background(task_id: str, initial_input: Dict, config: Dict, workspace_root: str = None):
    # (Same as before, just added commit_proposal event push)
    sb = StatefulSandbox(task_id, workspace_root=workspace_root)
    sb.start_session()
    register_sandbox(task_id, sb)

    try:
        async for event in workflow_app.astream(initial_input, config=config, stream_mode="values"):
            if 'project_state' in event:
                ps: ProjectState = event['project_state']
                
                # ... (Standard events)
                if ps.code_blocks:
                    latest = list(ps.code_blocks.values())[-1]
                    await stream_manager.push_event(task_id, "code_generated", {"content": latest})
                
                if ps.artifacts.get("pending_tool_call"):
                    await stream_manager.push_event(task_id, "tool_proposal", ps.artifacts["pending_tool_call"])
                
                if ps.artifacts.get("image_artifacts"):
                     await stream_manager.push_event(task_id, "image_generated", {"images": ps.artifacts["image_artifacts"]})

                # [Phase 3] Commit Proposal
                if ps.artifacts.get("commit_proposal"):
                     await stream_manager.push_event(task_id, "commit_proposal", ps.artifacts["commit_proposal"])

    except Exception as e:
        await stream_manager.push_event(task_id, "error", str(e))
    finally:
        await stream_manager.push_event(task_id, "finish", "done")
        await stream_manager.close_stream(task_id)

if __name__ == "__main__":
    uvicorn.run(app, host=HOST, port=PORT)

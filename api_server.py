import os
import uvicorn
from fastapi import FastAPI, HTTPException, BackgroundTasks, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse
import time
import asyncio
import json
import logging
from typing import Dict, Any

from config.keys import GEMINI_API_KEYS, PINECONE_API_KEY, PINECONE_ENVIRONMENT, VECTOR_INDEX_NAME
from core.rotator import GeminiKeyRotator
from core.api_models import TaskRequest
from tools.memory import VectorMemoryTool
from tools.search import GoogleSearchTool
from workflow.graph import build_agent_workflow
from langgraph.checkpoint.memory import MemorySaver
from core.models import ProjectState

# --- Configuration ---
PORT = int(os.getenv("PORT", 8000))
HOST = os.getenv("HOST", "127.0.0.1")

# --- Logging ---
logging.basicConfig(level=logging.INFO)
logger = logging.getLogger("vscode_backend")

app = FastAPI(title="Gemini VS Code Engine", version="3.0.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Components ---
checkpointer = MemorySaver()
# 简单取第一个 Key
api_key = GEMINI_API_KEYS[0] if GEMINI_API_KEYS else ""
rotator = GeminiKeyRotator("[https://generativelanguage.googleapis.com](https://generativelanguage.googleapis.com)", api_key) # Default base
memory = VectorMemoryTool(PINECONE_API_KEY, PINECONE_ENVIRONMENT, VECTOR_INDEX_NAME)
search = GoogleSearchTool()

# --- Build Graph (VS Code Mode) ---
# 这将构建只包含 Coding Crew 的图
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
            payload = {"type": event_type, "timestamp": time.strftime("%H:%M:%S"), "data": data}
            await self.active_streams[task_id].put(payload)

    async def close_stream(self, task_id: str):
        if task_id in self.active_streams:
            await self.active_streams[task_id].put(None)
            del self.active_streams[task_id]

stream_manager = EventStreamManager()

# --- Background Runner ---
async def run_workflow_background(task_id: str, initial_input: Dict, config: Dict):
    logger.info(f"🚀 [Engine] Task {task_id} Started.")
    await stream_manager.push_event(task_id, "status", {"msg": "Engine Started..."})

    try:
        async for event in workflow_app.astream(initial_input, config=config, stream_mode="values"):
            if 'project_state' in event:
                ps: ProjectState = event['project_state']
                
                # Push Code Artifacts
                if ps.code_blocks:
                    latest_code = list(ps.code_blocks.values())[-1]
                    await stream_manager.push_event(task_id, "code_generated", {
                        "content": latest_code,
                        "node": "coding_crew"
                    })
                
                # Push Logs
                if ps.last_error:
                    await stream_manager.push_event(task_id, "error", ps.last_error)

    except Exception as e:
        logger.error(f"💥 Engine Error: {e}")
        await stream_manager.push_event(task_id, "error", str(e))
    finally:
        await stream_manager.push_event(task_id, "finish", "done")
        await stream_manager.close_stream(task_id)

# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok", "mode": "vscode_engine"}

@app.post("/api/start_task")
async def start_task(req: TaskRequest, background_tasks: BackgroundTasks):
    task_id = f"task_{int(time.time())}"
    thread_id = req.thread_id or f"thread_{task_id}"
    
    # Init State with File Context
    ps = ProjectState.init_from_task(
        user_input=req.user_input, 
        task_id=task_id,
        file_context=req.file_context # Inject context
    )
    
    initial_input = {"project_state": ps}
    config = {"configurable": {"thread_id": thread_id}}
    
    await stream_manager.create_stream(task_id)
    background_tasks.add_task(run_workflow_background, task_id, initial_input, config)
    
    return {"task_id": task_id, "thread_id": thread_id}

@app.get("/api/stream/{task_id}")
async def stream_events(task_id: str, request: Request):
    async def event_generator():
        queue = stream_manager.active_streams.get(task_id)
        if not queue:
            yield f"event: finish\ndata: end\n\n"
            return

        while True:
            if await request.is_disconnected(): break
            payload = await queue.get()
            if payload is None:
                yield f"event: finish\ndata: end\n\n"
                break
            yield f"event: {payload['type']}\ndata: {json.dumps(payload['data'])}\n\n"

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    print(f"🔥 Gemini VS Code Engine starting on port {PORT}...")
    uvicorn.run(app, host=HOST, port=PORT)

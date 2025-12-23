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

# [Optimization] Correctly import Keys
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

app = FastAPI(title="Gemini VS Code Engine", version="3.1.0")

app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# --- Components ---
checkpointer = MemorySaver()

# [Critical Fix] URL Format was malformed (Markdown link detected). Fixed to pure URL string.
# [Optimization] Initialize Rotator with all keys.
rotator = GeminiKeyRotator("https://generativelanguage.googleapis.com", GEMINI_API_KEYS)

memory = VectorMemoryTool(PINECONE_API_KEY, PINECONE_ENVIRONMENT, VECTOR_INDEX_NAME)
search = GoogleSearchTool()

# --- Build Graph ---
# Note: The workflow builder now ensures the real rotator is passed to the Coding Crew
workflow_app = build_agent_workflow(rotator, memory, search, checkpointer=checkpointer)

# --- Stream Manager ---
class EventStreamManager:
    def __init__(self):
        self.active_streams: Dict[str, asyncio.Queue] = {}
        # [Optimization] Basic cleanup mechanism map (last_access)
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
            # We don't delete immediately to allow generator to finish, handled in generator logic or cleanup task
            # But strictly speaking, we can remove it after a short delay or let generator remove it.

    # [Optimization] Cleanup stale streams to prevent memory leaks
    async def cleanup_stale_streams(self):
        while True:
            await asyncio.sleep(600) # Check every 10 mins
            now = time.time()
            to_remove = []
            for tid, ts in self.stream_timestamps.items():
                if now - ts > 3600: # 1 hour timeout
                    to_remove.append(tid)
            
            for tid in to_remove:
                if tid in self.active_streams:
                    del self.active_streams[tid]
                if tid in self.stream_timestamps:
                    del self.stream_timestamps[tid]
                logger.info(f"🧹 Cleaned up stale stream: {tid}")

stream_manager = EventStreamManager()

# Start cleanup task on startup
@app.on_event("startup")
async def startup_event():
    asyncio.create_task(stream_manager.cleanup_stale_streams())

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
                    # Get the latest code block (simplistic approach)
                    latest_code = list(ps.code_blocks.values())[-1]
                    await stream_manager.push_event(task_id, "code_generated", {
                        "content": latest_code,
                        "node": "coding_crew"
                    })
                
                # Push Image Artifacts
                if ps.artifacts and "image_artifacts" in ps.artifacts:
                    images = ps.artifacts["image_artifacts"]
                    await stream_manager.push_event(task_id, "image_generated", {
                        "images": images
                    })
                
                # Push Logs
                if ps.last_error:
                    await stream_manager.push_event(task_id, "error", ps.last_error)

    except Exception as e:
        logger.error(f"💥 Engine Error: {e}")
        await stream_manager.push_event(task_id, "error", str(e))
    finally:
        await stream_manager.push_event(task_id, "finish", "done")
        # Ensure stream is closed
        await stream_manager.close_stream(task_id)

# --- Endpoints ---

@app.get("/health")
def health():
    return {"status": "ok", "mode": "vscode_engine"}

@app.post("/api/start_task")
async def start_task(req: TaskRequest, background_tasks: BackgroundTasks):
    task_id = f"task_{int(time.time())}"
    thread_id = req.thread_id or f"thread_{task_id}"
    
    ps = ProjectState.init_from_task(
        user_input=req.user_input, 
        task_id=task_id,
        file_context=req.file_context 
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
            yield f"event: error\ndata: \"Stream not found or expired\"\n\n"
            yield f"event: finish\ndata: end\n\n"
            return

        try:
            while True:
                if await request.is_disconnected():
                    logger.info(f"Client disconnected from stream {task_id}")
                    break
                
                # Wait for data with timeout to allow checking disconnect
                try:
                    payload = await asyncio.wait_for(queue.get(), timeout=1.0)
                except asyncio.TimeoutError:
                    continue

                if payload is None:
                    yield f"event: finish\ndata: end\n\n"
                    break
                
                yield f"event: {payload['type']}\ndata: {json.dumps(payload['data'])}\n\n"
        except Exception as e:
            logger.error(f"Stream error: {e}")
        finally:
            # Clean up the queue reference when client disconnects or finishes
            if task_id in stream_manager.active_streams:
                del stream_manager.active_streams[task_id]
            if task_id in stream_manager.stream_timestamps:
                del stream_manager.stream_timestamps[task_id]

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    print(f"🔥 Gemini VS Code Engine starting on port {PORT}...")
    uvicorn.run(app, host=HOST, port=PORT)

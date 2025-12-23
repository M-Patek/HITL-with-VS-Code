import os
import uuid
import uvicorn
import asyncio
import logging
import psutil
import signal
import json
from contextlib import asynccontextmanager
from fastapi import FastAPI, HTTPException, Request, BackgroundTasks, status
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse, JSONResponse
from pydantic import BaseModel
from typing import Optional, Dict, Any, List

# 假设这些模块都在项目中存在
from config.keys import GEMINI_API_KEYS
from core.models import GeminiModelConfig
from core.sandbox_manager import cleanup_all_sandboxes
# 引入 Graph 创建函数
from agents.crews.coding_crew.graph import create_coding_crew
from agents.crews.coding_crew.state import CodingCrewState, ProjectState

# [Security] Configure Logging
# Use WARNING level by default for production privacy to avoid leaking prompts/keys
LOG_LEVEL = os.getenv("LOG_LEVEL", "WARNING")
logging.basicConfig(
    level=getattr(logging, LOG_LEVEL),
    format='%(asctime)s - %(name)s - %(levelname)s - %(message)s'
)
logger = logging.getLogger("api_server")

# Silence noisy libraries
logging.getLogger("urllib3").setLevel(logging.WARNING)
logging.getLogger("docker").setLevel(logging.WARNING)

# [Security] Globals for Protection
HOST_PID = int(os.environ.get("VSCODE_PID", 0))
AUTH_TOKEN = os.environ.get("GEMINI_AUTH_TOKEN")
TRUSTED_WORKSPACE_ROOT = os.environ.get("VSCODE_WORKSPACE_ROOT")

# [Stability] Concurrency Limiter
# Limit max concurrent Docker containers to prevent DoS
MAX_CONCURRENT_TASKS = 5
task_semaphore = asyncio.Semaphore(MAX_CONCURRENT_TASKS)

@asynccontextmanager
async def lifespan(app: FastAPI):
    # Startup
    logger.info(f"🚀 API Server starting. Parent PID: {HOST_PID}")
    
    # Start suicide pact monitoring in background
    if HOST_PID > 0:
        asyncio.create_task(monitor_parent_process())
    
    yield
    
    # Shutdown
    logger.info("🛑 API Server shutting down. Cleaning up resources...")
    cleanup_all_sandboxes()

app = FastAPI(lifespan=lifespan)

# CORS - Allow localhost for VS Code Webview
app.add_middleware(
    CORSMiddleware,
    allow_origins=["*"], 
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)

# [Security] Authentication Middleware
@app.middleware("http")
async def verify_token(request: Request, call_next):
    if request.method == "OPTIONS":
        return await call_next(request)
        
    # Check Header (for Fetch) or Query Param (for SSE)
    token_header = request.headers.get("X-Auth-Token")
    token_query = request.query_params.get("token")
    
    if AUTH_TOKEN:
        if token_header != AUTH_TOKEN and token_query != AUTH_TOKEN:
            logger.warning(f"🚫 Unauthorized access attempt from {request.client.host}")
            return JSONResponse(
                status_code=status.HTTP_401_UNAUTHORIZED,
                content={"detail": "Unauthorized: Invalid or missing token 😾"}
            )
            
    response = await call_next(request)
    return response

async def monitor_parent_process():
    """
    [Safety] Suicide Pact:
    Monitors the VS Code parent process. If it dies, clean up Docker containers 
    and kill self to prevent zombie processes.
    """
    if HOST_PID == 0:
        logger.warning("⚠️ No HOST_PID provided. Suicide pact disabled.")
        return

    logger.info(f"🛡️ Suicide Pact Active: Monitoring Parent PID {HOST_PID}")
    while True:
        try:
            if not psutil.pid_exists(HOST_PID):
                logger.critical(f"💀 Parent process {HOST_PID} died. executing cleanup protocol...")
                cleanup_all_sandboxes() # [Fix] Explicit cleanup call
                os._exit(0) # Force exit
        except Exception as e:
            logger.error(f"Error in suicide pact: {e}")
            cleanup_all_sandboxes()
            os._exit(0)
        await asyncio.sleep(2)

# --- Models ---

class TaskRequest(BaseModel):
    user_input: str
    workspace_root: str
    task_id: Optional[str] = None

class FeedbackRequest(BaseModel):
    task_id: str
    feedback: str

# --- Endpoints ---

@app.post("/api/start_task")
async def start_task(req: TaskRequest, background_tasks: BackgroundTasks):
    """
    Starts a new coding task.
    """
    # [Stability] Concurrency Check
    if task_semaphore.locked():
        raise HTTPException(
            status_code=status.HTTP_503_SERVICE_UNAVAILABLE, 
            detail="Server busy: Too many active coding tasks."
        )

    # [Security] Path Trust Validation
    # Prefer the environment variable passed by VS Code over the request body
    target_root = TRUSTED_WORKSPACE_ROOT if TRUSTED_WORKSPACE_ROOT else req.workspace_root
    
    if not target_root or not os.path.exists(target_root):
        logger.error(f"Invalid workspace root: {target_root}")
        if not TRUSTED_WORKSPACE_ROOT: 
             logger.warning("⚠️ Using untrusted workspace root from request body!")
        else:
             # If env is present but path invalid, block it.
             raise HTTPException(status_code=400, detail="Invalid trusted workspace root.")

    task_id = req.task_id or f"task_{uuid.uuid4().hex}"
    logger.info(f"🏁 Starting Task {task_id}")

    # Initialize Configuration
    config = GeminiModelConfig(
        api_keys=GEMINI_API_KEYS,
        model_name="gemini-1.5-flash-latest",
        temperature=0.2
    )
    
    initial_input = {
        "user_requirement": req.user_input,
        "human_feedback": [],
        "iteration_count": 0,
        "max_iterations": 10
    }

    # Acquire semaphore and start background task
    await task_semaphore.acquire()
    background_tasks.add_task(
        run_workflow_with_semaphore, 
        task_id, 
        initial_input, 
        config, 
        target_root
    )

    return {"task_id": task_id, "status": "started"}

async def run_workflow_with_semaphore(task_id, inputs, config, workspace_root):
    """Wrapper to ensure semaphore is released after task completion"""
    try:
        await run_workflow_background(task_id, inputs, config, workspace_root)
    finally:
        task_semaphore.release()
        logger.debug(f"Task {task_id} finished, semaphore released.")

# Global storage for event queues (for SSE)
task_event_queues: Dict[str, asyncio.Queue] = {}

async def run_workflow_background(task_id: str, inputs: Dict, config: GeminiModelConfig, workspace_root: str):
    logger.info(f"▶️ Background Workflow Started: {task_id}")
    
    # Create Event Queue
    queue = asyncio.Queue()
    task_event_queues[task_id] = queue

    # Helper to push updates
    async def push_update(data: Dict):
        await queue.put(json.dumps(data))

    try:
        # Initialize Graph
        app_graph = create_coding_crew(config)
        
        # Initialize State
        project_state = ProjectState.init_from_task(task_id, workspace_root)
        
        initial_state = CodingCrewState(
            **inputs,
            project_state=project_state,
            plan=[],
            current_step_index=0,
            code_diffs=[],
            messages=[]
        )

        # Run Graph
        async for output in app_graph.astream(initial_state):
            for key, value in output.items():
                # Notify frontend about node updates
                await push_update({
                    "type": "step",
                    "node": key,
                    "details": f"Node {key} finished execution."
                })
                
                # Check for tool outputs and stream logs if available
                if key == "executor_node" and "execution_output" in value:
                     await push_update({
                         "type": "log",
                         "content": value["execution_output"]
                     })

        await push_update({"type": "complete", "status": "success"})

    except Exception as e:
        logger.error(f"❌ Workflow Error: {e}", exc_info=True)
        await push_update({"type": "error", "message": str(e)})
    finally:
        await push_update({"type": "close"})

@app.get("/api/stream/{task_id}")
async def stream_task_events(task_id: str, request: Request):
    """
    SSE Endpoint for real-time updates.
    """
    if task_id not in task_event_queues:
        return JSONResponse(status_code=404, content={"detail": "Task not found"})

    async def event_generator():
        queue = task_event_queues[task_id]
        try:
            while True:
                if await request.is_disconnected():
                    break
                    
                data = await queue.get()
                if data:
                    yield f"data: {data}\n\n"
                    
                    msg = json.loads(data)
                    if msg.get("type") == "close":
                        break
        except asyncio.CancelledError:
            pass
        finally:
            task_event_queues.pop(task_id, None)

    return StreamingResponse(event_generator(), media_type="text/event-stream")

if __name__ == "__main__":
    port = int(os.environ.get("PORT", 8000))
    uvicorn.run(app, host="127.0.0.1", port=port)

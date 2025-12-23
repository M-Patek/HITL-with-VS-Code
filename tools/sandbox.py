import docker
import os
import logging
import threading
from typing import Tuple, List, Dict, Optional

logger = logging.getLogger(__name__)

# [Fix] Global Registry to track active sandboxes by Task ID
# Used to retrieve the correct container instance in nodes.py
_SANDBOX_REGISTRY: Dict[str, 'StatefulSandbox'] = {}
_REGISTRY_LOCK = threading.Lock()

def get_sandbox(task_id: str) -> Optional['StatefulSandbox']:
    """Retrieves an existing sandbox for a given task ID."""
    with _REGISTRY_LOCK:
        return _SANDBOX_REGISTRY.get(task_id)

def register_sandbox(task_id: str, sandbox: 'StatefulSandbox'):
    with _REGISTRY_LOCK:
        _SANDBOX_REGISTRY[task_id] = sandbox

def unregister_sandbox(task_id: str):
    with _REGISTRY_LOCK:
        if task_id in _SANDBOX_REGISTRY:
            del _SANDBOX_REGISTRY[task_id]

def cleanup_all_sandboxes():
    """Global cleanup function used by api_server's suicide pact."""
    client = docker.from_env()
    logger.info("🧹 Cleaning up all active sandboxes...")
    
    # 1. Clean from Registry
    with _REGISTRY_LOCK:
        for task_id, sb in list(_SANDBOX_REGISTRY.items()):
            try:
                sb.cleanup()
            except Exception as e:
                logger.error(f"Error cleaning registry sandbox {task_id}: {e}")
        _SANDBOX_REGISTRY.clear()

    # 2. Safety Net: Clean any container matching the naming convention
    # This catches containers that might have been orphaned if the python process crashed hard before
    try:
        containers = client.containers.list(all=True, filters={"name": "gemini_sandbox_"})
        for c in containers:
            try:
                c.remove(force=True)
                logger.info(f"Cleaned up orphaned container: {c.name}")
            except Exception:
                pass
    except Exception as e:
        logger.error(f"Error listing containers for global cleanup: {e}")

class StatefulSandbox:
    """
    Manages a persistent Docker container for code execution.
    Features:
    - Persistent workspace mount
    - Resource limits (DoS protection)
    - Output truncation (DoS protection)
    """
    def __init__(self, task_id: str, workspace_root: str):
        self.task_id = task_id
        self.client = docker.from_env()
        self.container_name = f"gemini_sandbox_{task_id}"
        
        if not workspace_root or not os.path.exists(workspace_root):
            raise ValueError(f"Invalid workspace root for mounting: {workspace_root}")

        self.workspace_root = workspace_root
        self.container = None
        
        self._start_container()
        register_sandbox(task_id, self)

    def _start_container(self):
        try:
            # Cleanup existing if any collision
            self.cleanup(remove_from_registry=False)
            
            logger.info(f"Starting sandbox container: {self.container_name}")
            self.container = self.client.containers.run(
                "python:3.10-slim",
                command="tail -f /dev/null", # Keep alive command
                name=self.container_name,
                detach=True,
                working_dir="/workspace",
                volumes={
                    self.workspace_root: {'bind': '/workspace', 'mode': 'rw'}
                },
                # [Security] Resource Limits
                mem_limit="512m",
                cpu_period=100000,
                cpu_quota=50000, # 0.5 CPU
                network_mode="host" # Or "bridge" / "none" depending on need for pip install
            )
            
            # Install basic dependencies if needed (optional)
            # self.container.exec_run("pip install requests") 
            
        except Exception as e:
            logger.error(f"Failed to start sandbox: {e}")
            raise e

    def execute_code(self, code: str, timeout: int = 30) -> Tuple[str, str, List[Dict[str, str]]]:
        """
        Executes Python code inside the container.
        Wraps code in a helper to capture stdout/stderr reliably.
        """
        if not self.container:
            raise RuntimeError("Container not running")

        # We execute via python -c. For complex scripts, writing to a temp file inside container is better.
        # Here we use a simple approach.
        command = ["python", "-c", code]
        
        try:
            # exec_run returns (exit_code, output)
            # demux=True splits stdout and stderr
            exec_result = self.container.exec_run(
                command, 
                workdir="/workspace",
                demux=True 
            )
            
            stdout_bytes, stderr_bytes = exec_result.output
            
            stdout = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""
            stderr = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""
            
            # [Security] DoS Protection: Output Truncation
            MAX_OUTPUT_LEN = 50000 # 50KB limit
            
            if len(stdout) > MAX_OUTPUT_LEN:
                stdout = stdout[:MAX_OUTPUT_LEN] + "\n\n... [Output Truncated by System] ..."
                
            if len(stderr) > MAX_OUTPUT_LEN:
                stderr = stderr[:MAX_OUTPUT_LEN] + "\n\n... [Error Output Truncated by System] ..."

            return stdout, stderr, [] # Images not implemented in this simplified version

        except Exception as e:
            logger.error(f"Execution failed: {e}")
            return "", f"Execution Framework Error: {e}", []

    def execute_shell(self, command: str) -> Tuple[str, str]:
        """Executes a raw shell command."""
        if not self.container:
            raise RuntimeError("Container not running")
            
        try:
            exec_result = self.container.exec_run(
                ["/bin/sh", "-c", command],
                workdir="/workspace",
                demux=True
            )
            stdout_bytes, stderr_bytes = exec_result.output
            stdout = stdout_bytes.decode('utf-8', errors='replace') if stdout_bytes else ""
            stderr = stderr_bytes.decode('utf-8', errors='replace') if stderr_bytes else ""
            
            return stdout, stderr
        except Exception as e:
            return "", f"Shell Error: {e}"

    def cleanup(self, remove_from_registry=True):
        if remove_from_registry:
            unregister_sandbox(self.task_id)
            
        try:
            # Force remove container
            try:
                c = self.client.containers.get(self.container_name)
                c.remove(force=True)
            except docker.errors.NotFound:
                pass # Already gone
                
            logger.info(f"Cleaned up container {self.container_name}")
            self.container = None
        except Exception as e:
            logger.warning(f"Error during cleanup of {self.container_name}: {e}")

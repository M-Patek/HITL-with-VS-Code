from typing import Dict
from tools.sandbox import StatefulSandbox
import atexit
import logging

logger = logging.getLogger("SandboxManager")

# 全局单例，用于存储活跃的沙箱
# Key: task_id, Value: StatefulSandbox Instance
active_sandboxes: Dict[str, StatefulSandbox] = {}

def get_sandbox(task_id: str) -> StatefulSandbox:
    return active_sandboxes.get(task_id)

def register_sandbox(task_id: str, sandbox: StatefulSandbox):
    active_sandboxes[task_id] = sandbox

def unregister_sandbox(task_id: str):
    if task_id in active_sandboxes:
        active_sandboxes[task_id].close_session()
        del active_sandboxes[task_id]

# [Cleanup Fix] 注册进程退出时的清理函数
def cleanup_all_sandboxes():
    if not active_sandboxes:
        return
    
    logger.info(f"🧹 [Shutdown] Cleaning up {len(active_sandboxes)} active sandboxes...")
    # 转换为列表以避免在迭代时修改字典
    for task_id in list(active_sandboxes.keys()):
        try:
            logger.info(f"   Killing sandbox for task {task_id}")
            active_sandboxes[task_id].close_session()
        except Exception as e:
            logger.error(f"   Failed to close sandbox {task_id}: {e}")
    
    active_sandboxes.clear()

atexit.register(cleanup_all_sandboxes)

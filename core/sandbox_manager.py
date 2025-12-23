from typing import Dict
from tools.sandbox import StatefulSandbox

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

import os
import copy
from typing import Dict, Any, Optional

def load_prompt(base_path: str, filename: str) -> str:
    """
    通用 Prompt 文件加载工具。
    """
    path = os.path.join(base_path, filename)
    
    if not os.path.exists(path):
        abs_path = os.path.abspath(path)
        error_msg = f"❌ [Critical Configuration Error] Prompt file not found at: {abs_path}"
        print(error_msg)
        raise FileNotFoundError(error_msg)
        
    try:
        with open(path, 'r', encoding='utf-8') as f:
            return f.read().strip()
    except Exception as e:
        print(f"⚠️ Warning: Failed to read prompt file {path}: {e}")
        raise e

def slice_state_for_crew(global_state: Any, crew_name: str) -> Dict[str, Any]:
    """状态切片"""
    read_only_context = {
        "task_id": global_state.task_id,
        "existing_code": global_state.code_blocks.copy(),
        "existing_artifacts": global_state.artifacts.copy(),
        "prefetch_cache": global_state.prefetch_cache,
        "parent_vector_clock": global_state.vector_clock.copy()
    }
    
    return {
        "read_only": read_only_context,
        "crew_identity": crew_name,
        "meta": {
            "source_node": global_state.active_node_id,
            "slice_timestamp": global_state.vector_clock.get("main", 0)
        }
    }

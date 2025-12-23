from typing import List, Dict, Any, Optional
from pydantic import BaseModel, Field
from core.api_models import FileContext

# [Roo Code] 成本统计模型
class CostStats(BaseModel):
    total_cost: float = 0.0
    total_input_tokens: int = 0
    total_output_tokens: int = 0
    request_count: int = 0

class ProjectState(BaseModel):
    """
    [Cleanup] 全局项目状态 - 精简版
    移除了所有未使用的分布式字段（如 vector_clock, router_decision 等）。
    只保留 VS Code Engine 运行所需的核心数据。
    """
    task_id: str
    user_input: str
    
    # Context
    file_context: Optional[FileContext] = None
    repo_map: Optional[str] = None
    workspace_root: Optional[str] = None
    
    # Stats
    cost_stats: CostStats = Field(default_factory=CostStats)

    # Artifacts & Memory
    code_blocks: Dict[str, str] = Field(default_factory=dict)
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    full_chat_history: List[Dict[str, Any]] = Field(default_factory=list)
    
    # Execution & Report
    last_error: Optional[str] = None
    final_report: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def init_from_task(cls, user_input: str, task_id: str, file_context: Optional[FileContext] = None, workspace_root: str = None) -> "ProjectState":
        return cls(
            task_id=task_id,
            user_input=user_input,
            file_context=file_context,
            workspace_root=workspace_root
        )

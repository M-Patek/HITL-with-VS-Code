from typing import List, Dict, Any, Optional, Union
import time
from enum import Enum
from pydantic import BaseModel, Field
from langchain_core.messages import BaseMessage
from core.api_models import FileContext # Import FileContext

# =======================================================
# 状态枚举与节点定义
# =======================================================

class TaskStatus(str, Enum):
    PENDING = "pending"
    IN_PROGRESS = "in_progress"
    COMPLETED = "completed"
    FAILED = "failed"
    PAUSED = "paused"

class StageProtocol(BaseModel):
    """记录节点当前处于哪个生命周期阶段"""
    current_phase: str = "INITIAL_PLAN"

class TaskNode(BaseModel):
    """
    任务节点模型
    """
    node_id: str
    instruction: str
    status: TaskStatus = TaskStatus.PENDING
    level: int = 0
    parent_id: Optional[str] = None
    semantic_summary: str = ""
    local_history: List[Dict[str, Any]] = Field(default_factory=list)
    stage_protocol: StageProtocol = Field(default_factory=StageProtocol)

    class Config:
        arbitrary_types_allowed = True

# =======================================================
# 基础工件模型 (Artifacts)
# =======================================================

class ResearchArtifact(BaseModel):
    summary: str
    key_facts: List[str]
    sources: List[str]

class CodeArtifact(BaseModel):
    code: str
    language: str = "python"
    filename: str = "script.py"

class ArtifactVersion(BaseModel):
    """
    Version Control System for Artifacts
    """
    trace_id: Optional[str] = None
    node_id: str
    vector_clock: Dict[str, int]
    type: str  # 'image', 'code', 'report'
    content: Any
    label: str
    timestamp: float = Field(default_factory=lambda: time.time())

# =======================================================
# 全局项目状态 (ProjectState)
# =======================================================

class ProjectState(BaseModel):
    """
    全局项目状态 - VS Code Engine Edition
    """
    # --- 基础信息 ---
    task_id: str
    user_input: str
    image_data: Optional[str] = None
    
    # [VS Code] 注入的文件上下文
    file_context: Optional[FileContext] = None
    project_structure: Optional[str] = None
    
    # --- 任务图结构 ---
    node_map: Dict[str, TaskNode] = Field(default_factory=dict)
    root_node: Optional[TaskNode] = None
    active_node_id: str = "root"

    # --- 状态机控制 ---
    next_step: Optional[Dict[str, Any]] = None
    router_decision: str = "coding_crew" # Default to coding_crew
    plan: str = ""
    
    # --- 记忆与历史 ---
    full_chat_history: List[Dict[str, Any]] = Field(default_factory=list)
    messages: List[BaseMessage] = Field(default_factory=list)
    
    # --- 产出物 ---
    artifacts: Dict[str, Any] = Field(default_factory=dict)
    code_blocks: Dict[str, str] = Field(default_factory=dict)
    artifact_history: List[ArtifactVersion] = Field(default_factory=list)

    # --- 反馈与控制 ---
    user_feedback_queue: Optional[str] = None
    final_report: Optional[str] = None
    last_error: Optional[str] = None

    # --- 并发与安全 ---
    vector_clock: Dict[str, int] = Field(default_factory=lambda: {"main": 0})
    prefetch_cache: Dict[str, Any] = Field(default_factory=dict)
    trace_t: str = "0"
    trace_depth: int = 0
    trace_history: List[Dict[str, Any]] = Field(default_factory=list)
    
    research_summary: Optional[str] = None

    class Config:
        arbitrary_types_allowed = True

    @classmethod
    def init_from_task(cls, user_input: str, task_id: str, file_context: Optional[FileContext] = None) -> "ProjectState":
        """初始化项目状态"""
        root = TaskNode(node_id="root", instruction=user_input, status=TaskStatus.IN_PROGRESS)
        return cls(
            task_id=task_id,
            user_input=user_input,
            file_context=file_context, # Inject Context
            root_node=root,
            node_map={"root": root},
            active_node_id="root"
        )

    def get_active_node(self) -> Optional[TaskNode]:
        return self.node_map.get(self.active_node_id)

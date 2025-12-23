from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class FileContext(BaseModel):
    """
    [VS Code Plugin] 文件上下文模型
    """
    filename: str = Field(..., description="当前文件名 (e.g., main.py)")
    content: str = Field(..., description="文件完整内容")
    selection: Optional[str] = Field(None, description="用户当前选中的代码片段")
    cursor_line: Optional[int] = Field(None, description="当前光标所在行号")
    language_id: str = Field("python", description="VS Code 语言 ID (e.g., typescript, python)")

class TaskRequest(BaseModel):
    """
    用户发起任务的请求模型 (Enhanced for VS Code)
    """
    user_input: str = Field(..., description="用户的原始指令")
    thread_id: Optional[str] = Field(None, description="会话 ID")
    
    # [VS Code] 新增文件上下文
    file_context: Optional[FileContext] = Field(None, description="当前编辑器上下文")
    
    # [Aider Upgrade] 传入工作区根路径，用于生成 Repo Map
    workspace_root: Optional[str] = Field(None, description="工作区根目录绝对路径")
    
    # [Legacy] 旧的项目结构字符串，如果生成了 Repo Map 则可以忽略此字段
    project_structure: Optional[str] = Field(None, description="简化的文件树结构")

class StreamEvent(BaseModel):
    """
    流式输出的事件模型
    """
    event_type: str = Field(..., description="事件类型")
    data: Dict[str, Any] = Field(default_factory=dict, description="载荷数据")

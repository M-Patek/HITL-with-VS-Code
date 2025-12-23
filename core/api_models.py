from typing import Optional, Dict, Any, List
from pydantic import BaseModel, Field

class FileContext(BaseModel):
    filename: str = Field(..., description="Current filename")
    content: str = Field(..., description="File content")
    selection: Optional[str] = None
    cursor_line: Optional[int] = None
    language_id: str = "python"

class TaskRequest(BaseModel):
    user_input: str
    thread_id: Optional[str] = None
    file_context: Optional[FileContext] = None
    workspace_root: Optional[str] = None
    
    # [Phase 3 Upgrade]
    mode: Optional[str] = Field("coder", description="Agent mode: coder, architect, debugger")

class StreamEvent(BaseModel):
    event_type: str
    data: Dict[str, Any]

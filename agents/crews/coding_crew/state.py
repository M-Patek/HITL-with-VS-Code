from typing import List, Dict, Any, Optional
from agents.common_types import AgentGraphState

# [VS Code Refactor]
# CodingCrewState 现在直接复用 AgentGraphState (TypedDict)
# 这样子图可以直接访问 ProjectState 中的 file_context
# 不再需要单独定义 class CodingCrewState(BaseAgentState)
# 但为了保持类型提示和 graph 定义的兼容性，我们定义它等于 AgentGraphState

CodingCrewState = AgentGraphState

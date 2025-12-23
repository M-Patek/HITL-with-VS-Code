from typing import Dict, Any
from langgraph.graph import StateGraph, END
from core.crew_registry import crew_registry
from agents.common_types import AgentGraphState
from core.rotator import GeminiKeyRotator
from tools.memory import VectorMemoryTool
from tools.search import GoogleSearchTool

def build_agent_workflow(
    rotator: GeminiKeyRotator, 
    memory: VectorMemoryTool, 
    search: GoogleSearchTool, 
    checkpointer: Any = None
):
    """
    构建主工作流 - VS Code Direct Mode
    移除 Orchestrator/Planner，直接将 Coding Crew 作为主流程。
    """
    # 1. 初始化主图 (使用统一的 AgentGraphState)
    workflow = StateGraph(AgentGraphState)
    
    # 2. 获取 Coding Crew 子图
    coding_crew_data = crew_registry.get_all_crews().get("coding_crew")
    
    if not coding_crew_data:
        raise RuntimeError("❌ Critical Error: Coding Crew not found in registry!")
        
    coding_subgraph = coding_crew_data["graph"]
    
    # 3. 添加节点：直接作为主处理单元
    print("🚀 Wiring Workflow: Start -> Coding Crew -> End")
    workflow.add_node("coding_crew", coding_subgraph)
    
    # 4. 设置入口点
    workflow.set_entry_point("coding_crew")
    
    # 5. 设置出口
    workflow.add_edge("coding_crew", END)
    
    return workflow.compile(checkpointer=checkpointer)

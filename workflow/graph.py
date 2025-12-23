from typing import Dict, Any
from langgraph.graph import StateGraph, END
# [Critical Fix] Do NOT import the pre-compiled graph from registry directly for the main workflow
# from core.crew_registry import crew_registry 
from agents.common_types import AgentGraphState
from core.rotator import GeminiKeyRotator
from tools.memory import VectorMemoryTool
from tools.search import GoogleSearchTool

# [Critical Fix] Import the builder function to inject real dependencies
from agents.crews.coding_crew.graph import build_coding_crew_graph

def build_agent_workflow(
    rotator: GeminiKeyRotator, 
    memory: VectorMemoryTool, 
    search: GoogleSearchTool, 
    checkpointer: Any = None
):
    """
    构建主工作流 - VS Code Direct Mode
    修复了之前直接使用 Mock Graph 的问题，现在会动态注入真实的 API Key Rotator。
    """
    # 1. 初始化主图 (使用统一的 AgentGraphState)
    workflow = StateGraph(AgentGraphState)
    
    # 2. 动态构建 Coding Crew 子图，注入真实的 Rotator
    # 这样 Agents 才能使用 api_server.py 中配置的真实 Keys
    print("🔄 Building Coding Crew with LIVE Rotator...")
    coding_subgraph = build_coding_crew_graph(rotator)
    
    # 3. 添加节点：直接作为主处理单元
    print("🚀 Wiring Workflow: Start -> Coding Crew -> End")
    workflow.add_node("coding_crew", coding_subgraph)
    
    # 4. 设置入口点
    workflow.set_entry_point("coding_crew")
    
    # 5. 设置出口
    workflow.add_edge("coding_crew", END)
    
    return workflow.compile(checkpointer=checkpointer)

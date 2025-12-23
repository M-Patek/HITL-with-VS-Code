from typing import Any, Dict
from langgraph.graph import StateGraph, END
from agents.crews.coding_crew.state import CodingCrewState
from core.rotator import GeminiKeyRotator
from tools.memory import VectorMemoryTool
from tools.search import GoogleSearchTool

# [Cleanup] 直接导入构建函数，不再使用 core.crew_registry
from agents.crews.coding_crew.graph import build_coding_crew_graph

# [Cleanup] 定义统一的 State 类型，这里直接复用 CodingCrewState 作为主 State
# 如果未来有多个 Crew，可以使用 Union 或更通用的 AgentGraphState
AgentGraphState = CodingCrewState 

def build_agent_workflow(
    rotator: GeminiKeyRotator, 
    memory: VectorMemoryTool, 
    search: GoogleSearchTool, 
    checkpointer: Any = None
):
    """
    构建主工作流 - VS Code Direct Mode
    完全移除了旧的注册表逻辑，直接动态构建 Coding Crew。
    """
    # 1. 初始化主图
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

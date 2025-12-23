from typing import Any, Dict
from langgraph.graph import StateGraph, END
from agents.crews.coding_crew.state import CodingCrewState
from core.rotator import GeminiKeyRotator
from tools.memory import VectorMemoryTool
from tools.search import GoogleSearchTool

from agents.crews.coding_crew.graph import build_coding_crew_graph

AgentGraphState = CodingCrewState 

def build_agent_workflow(
    rotator: GeminiKeyRotator, 
    memory: VectorMemoryTool, 
    search: GoogleSearchTool, 
    checkpointer: Any = None
):
    """
    构建主工作流 - VS Code Direct Mode
    """
    # 1. 初始化主图
    workflow = StateGraph(AgentGraphState)
    
    # 2. 动态构建 Coding Crew 子图，注入所有工具
    print("🔄 Building Coding Crew with LIVE Rotator & Tools...")
    # [Fix] Pass memory and search tools
    coding_subgraph = build_coding_crew_graph(rotator, memory=memory, search=search)
    
    # 3. 添加节点：直接作为主处理单元
    print("🚀 Wiring Workflow: Start -> Coding Crew -> End")
    workflow.add_node("coding_crew", coding_subgraph)
    
    # 4. 设置入口点
    workflow.set_entry_point("coding_crew")
    
    # 5. 设置出口
    workflow.add_edge("coding_crew", END)
    
    return workflow.compile(checkpointer=checkpointer)

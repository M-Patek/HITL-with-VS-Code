from typing import Any
from langgraph.graph import StateGraph, END
from core.rotator import GeminiKeyRotator
from agents.crews.coding_crew.state import CodingCrewState
from agents.crews.coding_crew.nodes import CodingCrewNodes

def route_review(state: CodingCrewState) -> str:
    status = state.get("review_status", "reject")
    count = state.get("iteration_count", 0)
    
    if status == "approve":
        return "summarize"
    elif count >= 5: 
        return "summarize"
    else:
        return "reflect"

def build_coding_crew_graph(rotator: GeminiKeyRotator, checkpointer: Any = None) -> StateGraph:
    nodes = CodingCrewNodes(rotator)
    workflow = StateGraph(CodingCrewState)
    
    workflow.add_node("coder", nodes.coder_node)
    workflow.add_node("executor", nodes.executor_node)
    workflow.add_node("reviewer", nodes.reviewer_node)
    workflow.add_node("reflector", nodes.reflector_node) 
    workflow.add_node("summarizer", nodes.summarizer_node)
    
    workflow.set_entry_point("coder")
    
    workflow.add_edge("coder", "executor")
    workflow.add_edge("executor", "reviewer")
    
    workflow.add_conditional_edges(
        "reviewer",
        route_review,
        {
            "reflect": "reflector", 
            "summarize": "summarizer"
        }
    )
    workflow.add_edge("reflector", "coder")
    workflow.add_edge("summarizer", END)
    
    return workflow.compile(checkpointer=checkpointer)

# Default export for registry
graph = build_coding_crew_graph(GeminiKeyRotator("http://mock", "mock"))

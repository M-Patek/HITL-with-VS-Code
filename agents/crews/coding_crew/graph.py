from typing import Any, Dict
from langgraph.graph import StateGraph, END
from core.rotator import GeminiKeyRotator
from agents.crews.coding_crew.state import CodingCrewState
from agents.crews.coding_crew.nodes import CodingCrewNodes

# [Phase 1 Upgrade] Updated Router with Step Logic
def route_step(state: CodingCrewState) -> str:
    """
    Decides whether to retry current step, move to next step, or finish.
    """
    status = state.get("review_status", "reject")
    count = state.get("iteration_count", 0)
    
    # 1. If rejected, reflect and retry (unless max retries reached)
    if status != "approve":
        if count >= 5: # Max retries per step
             print("   ⚠️ Max retries reached for this step. Forcing summary.")
             return "summarize" # Force finish (fail)
        return "reflect"
    
    # 2. If approved, check if plan is complete
    plan = state.get("plan", [])
    current_idx = state.get("current_step_index", 0)
    
    # If there are more steps
    if current_idx + 1 < len(plan):
        print(f"✅ Step {current_idx+1} Complete. Advancing to Step {current_idx+2}...")
        return "next_step"
    
    # 3. All steps done
    print("🎉 All steps complete!")
    return "summarize"

def next_step_node(state: CodingCrewState) -> Dict[str, Any]:
    """Helper node to increment step index and reset iteration."""
    return {
        "current_step_index": state.get("current_step_index", 0) + 1,
        "iteration_count": 0, # Reset retries for new step
        "reflection": "",     # Clear previous reflection
        "review_feedback": "", # Clear feedback
        "linter_passed": True
    }

def build_coding_crew_graph(rotator: GeminiKeyRotator, checkpointer: Any = None) -> StateGraph:
    nodes = CodingCrewNodes(rotator)
    workflow = StateGraph(CodingCrewState)
    
    # Nodes
    workflow.add_node("planner", nodes.planner_node) # [New]
    workflow.add_node("coder", nodes.coder_node)
    workflow.add_node("executor", nodes.executor_node)
    workflow.add_node("reviewer", nodes.reviewer_node)
    workflow.add_node("security_guard", nodes.security_node) 
    workflow.add_node("aggregator", nodes.aggregator_node)   
    workflow.add_node("reflector", nodes.reflector_node) 
    workflow.add_node("summarizer", nodes.summarizer_node)
    
    # [New] Utility node for step increment
    workflow.add_node("step_manager", next_step_node)
    
    # Wiring
    # 1. Start with Planner
    workflow.set_entry_point("planner")
    workflow.add_edge("planner", "coder")
    
    # 2. Loop
    workflow.add_edge("coder", "executor")
    
    # Parallel Fork
    workflow.add_edge("executor", "reviewer")
    workflow.add_edge("executor", "security_guard")
    
    # Join
    workflow.add_edge("reviewer", "aggregator")
    workflow.add_edge("security_guard", "aggregator")
    
    # 3. Router logic
    workflow.add_conditional_edges(
        "aggregator",
        route_step,
        {
            "reflect": "reflector", 
            "next_step": "step_manager", # Go to increment
            "summarize": "summarizer"
        }
    )
    
    # 4. Cycles
    workflow.add_edge("reflector", "coder") # Retry same step
    workflow.add_edge("step_manager", "coder") # Do next step
    
    workflow.add_edge("summarizer", END)
    
    return workflow.compile(checkpointer=checkpointer)

# Default export (Mock for quick testing)
graph = build_coding_crew_graph(GeminiKeyRotator("http://mock", ["mock"]))

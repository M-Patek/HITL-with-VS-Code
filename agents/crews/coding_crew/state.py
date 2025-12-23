from typing import List, Dict, Any, Optional, TypedDict
from core.models import ProjectState

# [Optimization] 明确定义 TypedDict 以支持并行键
class CodingCrewState(TypedDict, total=False):
    project_state: ProjectState
    iteration_count: int
    generated_code: str
    
    # Executor outputs
    execution_stdout: str
    execution_stderr: str
    execution_passed: bool
    image_artifacts: List[Dict[str, str]]
    
    # [Parallel] Review outputs
    functional_status: str
    functional_feedback: str
    security_feedback: str
    
    # Aggregated outputs
    review_status: str
    review_feedback: str
    review_report: Dict[str, Any]
    
    reflection: str
    final_output: str

import re
import json
import os
import asyncio
from typing import Dict, Any

from core.utils import load_prompt, calculate_cost
from core.models import GeminiModel, ProjectState
from config.keys import GEMINI_MODEL_NAME
from agents.crews.coding_crew.state import CodingCrewState
from tools.sandbox import run_python_code
from core.repo_map import RepositoryMapper 
from core.mcp_tool_definitions import MCPToolRegistry
from core.sandbox_manager import get_sandbox

class CodingCrewNodes:
    def __init__(self, rotator):
        self.rotator = rotator
        self.base_prompt_path = os.path.join(os.path.dirname(__file__), "prompts")

    def _get_project_state(self, state: CodingCrewState) -> ProjectState:
        return state.get("project_state")

    def _ensure_repo_map(self, ps: ProjectState):
        """[Aider] 确保生成代码库地图"""
        if not ps.repo_map and ps.workspace_root:
            print(f"🗺️ [RepoMap] Analyzing workspace: {ps.workspace_root}")
            mapper = RepositoryMapper(ps.workspace_root)
            ps.repo_map = mapper.generate_map()

    def _update_cost(self, ps: ProjectState, usage: Dict[str, int]):
        """[Roo Code] 更新成本统计"""
        if not usage: return
        in_tokens = usage.get("prompt_tokens", 0)
        out_tokens = usage.get("completion_tokens", 0)
        cost = calculate_cost(GEMINI_MODEL_NAME, in_tokens, out_tokens)
        
        ps.cost_stats.total_input_tokens += in_tokens
        ps.cost_stats.total_output_tokens += out_tokens
        ps.cost_stats.total_cost += cost
        ps.cost_stats.request_count += 1
        
        print(f"   💰 Cost: ${cost:.6f} | Total: ${ps.cost_stats.total_cost:.4f}")

    def coder_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """
        [Coder] VS Code Aware + Repo Map + MCP Tools + Cost Tracking
        """
        ps = self._get_project_state(state)
        iteration = state.get("iteration_count", 0) + 1
        
        print(f"\n💻 [Coder] VS Code Engine Activated (Iter: {iteration})")
        
        self._ensure_repo_map(ps)
        prompt_template = load_prompt(self.base_prompt_path, "coder.md")
        
        # --- Context Injection ---
        user_input = ps.user_input
        file_ctx_str = "No file open."
        
        if ps.file_context:
            fc = ps.file_context
            content = fc.content
            # Truncation logic
            if len(content) > 10000: content = content[:10000] + "...[Truncated]"
            
            file_ctx_str = f"""
### 📄 Current File Context (Focus)
- **Filename**: `{fc.filename}`
- **Language**: `{fc.language_id}`
- **Cursor Line**: {fc.cursor_line}
- **Content**:
```
{content}
```
"""
        
        repo_map_str = ps.repo_map if ps.repo_map else "(No Repository Map)"

        reflection = state.get("reflection", "")
        raw_feedback = state.get("review_feedback", "")
        combined_feedback = raw_feedback
        if reflection:
             combined_feedback = f"### Tech Lead Fix Strategy:\n{reflection}\n\nReview Feedback: {raw_feedback}"
        
        mcp_instructions = MCPToolRegistry.get_system_prompt_addition()

        formatted_prompt = prompt_template.format(
            user_input=user_input,
            file_context=file_ctx_str,
            repo_map=repo_map_str, 
            feedback=combined_feedback or "None",
            mcp_tools=mcp_instructions
        )
        
        # Call LLM with Cost Tracking
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            system_instruction="你是一个集成在 VS Code 中的 AI 编程助手，请使用提供的 MCP 工具来操作文件和终端。",
            complexity="complex"
        )
        self._update_cost(ps, usage)
        
        code = response_text or ""
        
        # Parse Tool Call
        tool_call = MCPToolRegistry.parse_tool_call(response_text)
        
        if not tool_call:
            match = re.search(r"```python(.*?)```", response_text, re.DOTALL)
            if match:
                code = match.group(1).strip()
            elif "```" in response_text:
                 match = re.search(r"```(.*?)```", response_text, re.DOTALL)
                 if match: code = match.group(1).strip()
            ps.code_blocks["coder"] = code
        else:
            ps.code_blocks["coder"] = response_text
            ps.artifacts["pending_tool_call"] = tool_call

        return {
            "project_state": ps, 
            "generated_code": code,
            "iteration_count": iteration,
            "reflection": ""
        }

    async def executor_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Executor] Sandbox Runner (Stateful)"""
        ps = self._get_project_state(state)
        task_id = ps.task_id
        
        # 1. Check for MCP Tool Call (Client Side Execution)
        if "pending_tool_call" in ps.artifacts:
            print("   🛠️ Tool Call detected, waiting for Client Approval...")
            return {
                "project_state": ps,
                "execution_stdout": "[Waiting for Client Tool Execution]",
                "execution_stderr": "",
                "execution_passed": True 
            }
        
        # 2. Python Code Block Execution (Server Side Sandbox)
        print(f"🚀 [Executor] Sandbox Running for Task {task_id}...")
        code = state.get("generated_code", "")
        
        if not code:
            return {"execution_passed": False, "execution_stderr": "No code."}
            
        sandbox = get_sandbox(task_id)
        
        if sandbox:
            stdout, stderr, images = sandbox.execute_code(code)
            
            passed = (not stderr or "Error" not in stderr)
            status_icon = "✅" if passed else "❌"
            print(f"   {status_icon} Sandbox Executed.")
            
            if images:
                 ps.artifacts["image_artifacts"] = images

            return {
                "project_state": ps,
                "execution_stdout": stdout,
                "execution_stderr": stderr,
                "execution_passed": passed,
                "image_artifacts": images
            }
        else:
            return {"execution_passed": False, "execution_stderr": "Sandbox not found."}

    def reviewer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Reviewer] Code Review + Cost Tracking"""
        print(f"🧐 [Reviewer] Analyzing...")
        ps = self._get_project_state(state)
        
        stdout = state.get("execution_stdout", "")
        stderr = state.get("execution_stderr", "")
        if len(stdout) > 2000: stdout = stdout[:2000] + "...(truncated)"
        if len(stderr) > 2000: stderr = stderr[:2000] + "...(truncated)"

        prompt_template = load_prompt(self.base_prompt_path, "reviewer.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            stdout=stdout,
            stderr=stderr
        )
        
        # Call LLM
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            system_instruction="Strict JSON reviewer.",
            complexity="complex"
        )
        self._update_cost(ps, usage)
        
        status = "reject"
        feedback = "Parse Error"
        report = {}
        try:
            start = response_text.find("{")
            end = response_text.rfind("}")
            if start != -1 and end != -1:
                json_str = response_text[start:end+1]
                json_str = json_str.replace("```json", "").replace("```", "")
                report = json.loads(json_str)
                status = report.get("status", "reject").lower()
                feedback = report.get("feedback", "")
            else:
                pass 
        except Exception as e:
            print(f"   ⚠️ Review JSON Parse Failed: {e}")
            pass
        
        print(f"   📝 Review Status: {status.upper()}")
        return {
            "review_status": status,
            "review_feedback": feedback,
            "review_report": report
        }

    def reflector_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Reflector] Root Cause Analysis + Cost Tracking"""
        print(f"🔧 [Reflector] Fixing strategy...")
        ps = self._get_project_state(state)
        
        stderr = state.get("execution_stderr", "None")
        if len(stderr) > 2000: stderr = stderr[:2000] + "...(truncated)"

        prompt_template = load_prompt(self.base_prompt_path, "reflection.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            execution_stderr=stderr,
            review_report=json.dumps(state.get("review_report", {}))
        )
        
        # Call LLM
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            system_instruction="Tech Lead Fixer.",
            complexity="complex"
        )
        self._update_cost(ps, usage)
        
        return {"reflection": response_text}

    def summarizer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Summarizer] Final Report + Cost Tracking"""
        print(f"📝 [Summarizer] Finalizing...")
        ps = self._get_project_state(state)
        
        prompt_template = load_prompt(self.base_prompt_path, "summarizer.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            execution_output=state.get("execution_stdout", "")[:1000]
        )
        
        # Call LLM
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            system_instruction="Summary.",
            complexity="simple"
        )
        self._update_cost(ps, usage)
        
        ps.final_report = response_text
        return {"final_output": response_text, "project_state": ps}

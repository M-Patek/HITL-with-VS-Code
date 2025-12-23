import re
import json
import os
import asyncio
from typing import Dict, Any, List

from core.utils import load_prompt, calculate_cost
from core.models import GeminiModel, ProjectState
from config.keys import GEMINI_MODEL_NAME
from agents.crews.coding_crew.state import CodingCrewState
# [Fix] Removed non-existent import 'run_python_code'
from core.repo_map import RepositoryMapper 
from core.mcp_tool_definitions import MCPToolRegistry
from core.sandbox_manager import get_sandbox
from tools.browser import WebLoader 
# [Fix] Corrected class name from VectorMemoryTool to LocalRAGMemory
from tools.memory import LocalRAGMemory
from tools.search import GoogleSearchTool

class CodingCrewNodes:
    # [Fix] Updated type hint
    def __init__(self, rotator, memory: LocalRAGMemory = None, search: GoogleSearchTool = None):
        self.rotator = rotator
        self.memory = memory
        self.search = search
        self.base_prompt_path = os.path.join(os.path.dirname(__file__), "prompts")
        self.active_cache_name = None
        self.browser = WebLoader() 

    def _get_project_state(self, state: CodingCrewState) -> ProjectState:
        return state.get("project_state")
    
    def _extract_json(self, text): 
        try:
            # [Safe Regex] Construct pattern to avoid breaking markdown rendering
            fence = "```"
            text = re.sub(f"^{fence}json\\s*", "", text, flags=re.MULTILINE)
            text = re.sub(f"\\s*{fence}$", "", text, flags=re.MULTILINE)
            return json.loads(text)
        except json.JSONDecodeError:
            match = re.search(r"(\{.*\}|\[.*\])", text, re.DOTALL)
            if match:
                try:
                    return json.loads(match.group(1))
                except: pass
            return {}

    def planner_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Architect] Generates a step-by-step plan."""
        print(f"\n🏗️ [Planner] Architecting solution...")
        ps = self._get_project_state(state)
        
        prompt_file = "planner.md"
        if ps.mode == "architect":
             prompt_file = "architect.md" 
        
        prompt_template = load_prompt(self.base_prompt_path, prompt_file)
        if not prompt_template: prompt_template = "Plan the task: {user_input}"
        
        repo_map = ps.repo_map or "(No Repo Map)"
        
        prompt = prompt_template.format(
            user_input=ps.user_input,
            repo_map=repo_map,
            diagnostics=ps.full_chat_history[-1].get("content") if ps.full_chat_history else ""
        )

        resp, _ = self.rotator.call_gemini_with_rotation(
            GEMINI_MODEL_NAME,
            [{"role": "user", "parts": [{"text": prompt}]}]
        )
        
        plan = self._extract_json(resp)
        if not isinstance(plan, list):
            plan = ["Step 1: Execute user request directly."]
            
        return {"plan": plan, "current_step_index": 0, "project_state": ps}

    def coder_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Coder] Executes steps."""
        ps = self._get_project_state(state)
        step_idx = state.get("current_step_index", 0)
        plan = state.get("plan", [])
        current_step = plan[step_idx] if step_idx < len(plan) else "Finalize"
        
        print(f"\n👨‍💻 [Coder] working on Step {step_idx + 1}: {current_step}")

        prompt_file = "coder.md"
        if ps.mode == "debugger":
             prompt_file = "debugger.md"

        prompt_template = load_prompt(self.base_prompt_path, prompt_file)
        if not prompt_template: prompt_template = "Write code for: {user_input}"
        
        mcp_tools_desc = MCPToolRegistry.get_system_prompt_addition()
        
        prompt = prompt_template.format(
            user_input=f"Current Step: {current_step}\nOriginal Task: {ps.user_input}",
            file_context=ps.file_context.json() if ps.file_context else "No active file",
            repo_map=ps.repo_map or "",
            feedback=state.get("review_feedback", "") + "\n" + state.get("reflection", ""),
            mcp_tools=mcp_tools_desc
        )

        resp, _ = self.rotator.call_gemini_with_rotation(
            GEMINI_MODEL_NAME,
            [{"role": "user", "parts": [{"text": prompt}]}],
            cached_content_name=self.active_cache_name
        )
        
        tool_call = MCPToolRegistry.parse_tool_call(resp)
        if tool_call:
            ps.artifacts["pending_tool_call"] = tool_call
        
        return {
            "project_state": ps, 
            "generated_code": resp,
            "linter_passed": True
        }

    def executor_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Executor] Runs code in Sandbox."""
        ps = self._get_project_state(state)
        code_response = state.get("generated_code", "")
        
        # [Fix] Construct Regex safely to avoid markdown rendering issues
        # Pattern: ```(python|py)? ... ```
        fence = "```"
        pattern = f"{fence}(?:python|py)?\\n(.*?){fence}"
        
        code_blocks = re.findall(pattern, code_response, re.DOTALL | re.IGNORECASE)
        
        if not code_blocks:
            if ps.artifacts.get("pending_tool_call"):
                return {
                    "execution_stdout": "Tool call pending approval.",
                    "execution_stderr": "",
                    "execution_passed": True
                }
            return {
                "execution_stdout": "No executable code found.",
                "execution_stderr": "",
                "execution_passed": True 
            }

        sb = get_sandbox(ps.task_id)
        if not sb:
            return {"execution_stdout": "", "execution_stderr": "Sandbox not found", "execution_passed": False}
            
        full_stdout = ""
        full_stderr = ""
        passed = True
        
        for code in code_blocks:
            out, err, imgs = sb.execute_code(code)
            full_stdout += out + "\n"
            full_stderr += err + "\n"
            if err: passed = False
            if imgs:
                ps.artifacts.setdefault("image_artifacts", []).extend(imgs)

        return {
            "execution_stdout": full_stdout.strip(),
            "execution_stderr": full_stderr.strip(),
            "execution_passed": passed,
            "image_artifacts": ps.artifacts.get("image_artifacts", [])
        }

    def reviewer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Reviewer] Reviews code."""
        ps = self._get_project_state(state)
        prompt_template = load_prompt(self.base_prompt_path, "reviewer.md")
        if not prompt_template: prompt_template = "Review code: {code}"
        
        prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            stdout=state.get("execution_stdout", ""),
            stderr=state.get("execution_stderr", "")
        )

        resp, _ = self.rotator.call_gemini_with_rotation(
            GEMINI_MODEL_NAME,
            [{"role": "user", "parts": [{"text": prompt}]}]
        )
        
        review_json = self._extract_json(resp)
        status = review_json.get("status", "approve")
        feedback = review_json.get("feedback", "")
        
        return {
            "functional_status": status,
            "functional_feedback": feedback,
            "review_report": review_json
        }

    def security_node(self, state: CodingCrewState) -> Dict[str, Any]:
        return {"security_feedback": "Security Check Passed (Mock)"}

    def aggregator_node(self, state: CodingCrewState) -> Dict[str, Any]:
        func_status = state.get("functional_status", "approve")
        func_feedback = state.get("functional_feedback", "")
        sec_feedback = state.get("security_feedback", "")
        
        final_status = "approve" if func_status == "approve" else "reject"
        final_feedback = f"{func_feedback}\n{sec_feedback}".strip()
        
        return {
            "review_status": final_status,
            "review_feedback": final_feedback
        }

    def reflector_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Reflector] Analyzes failure."""
        ps = self._get_project_state(state)
        prompt_template = load_prompt(self.base_prompt_path, "reflection.md")
        if not prompt_template: prompt_template = "Reflect on error: {execution_stderr}"
        
        prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            execution_stderr=state.get("execution_stderr", ""),
            review_report=state.get("review_feedback", "")
        )

        resp, _ = self.rotator.call_gemini_with_rotation(
            GEMINI_MODEL_NAME,
            [{"role": "user", "parts": [{"text": prompt}]}]
        )
        
        return {
            "reflection": resp,
            "iteration_count": state.get("iteration_count", 0) + 1
        }

    def summarizer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Summarizer] Finalizing & Semantic Commit"""
        print(f"📝 [Summarizer] Finalizing...")
        ps = self._get_project_state(state)
        
        prompt_template = load_prompt(self.base_prompt_path, "summarizer.md")
        if not prompt_template: prompt_template = "Summarize: {user_input}"

        prompt = prompt_template.format(
             user_input=ps.user_input,
             code=state.get("generated_code", ""),
             execution_output=state.get("execution_stdout", "")
        )
        
        resp, usage = self.rotator.call_gemini_with_rotation(
            GEMINI_MODEL_NAME,
            [{"role": "user", "parts": [{"text": prompt}]}],
            cached_content_name=self.active_cache_name
        )
        
        if ps.code_blocks:
            commit_prompt = f"""
            Based on the following user task and code changes, generate a concise Conventional Commit message (e.g., 'feat: add login').
            Only return the message string.
            
            Task: {ps.user_input}
            """
            commit_msg, _ = self.rotator.call_gemini_with_rotation(
                GEMINI_MODEL_NAME,
                [{"role": "user", "parts": [{"text": commit_prompt}]}],
                complexity="simple"
            )
            ps.artifacts["commit_proposal"] = commit_msg.strip()

        ps.final_report = resp
        return {"final_output": resp, "project_state": ps}

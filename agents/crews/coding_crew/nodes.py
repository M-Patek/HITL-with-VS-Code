import re
import json
import os
from typing import Dict, Any, List

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
        if not ps.repo_map and ps.workspace_root:
            print(f"🗺️ [RepoMap] Analyzing workspace: {ps.workspace_root}")
            mapper = RepositoryMapper(ps.workspace_root)
            ps.repo_map = mapper.generate_map()

    def _update_cost(self, ps: ProjectState, usage: Dict[str, int]):
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
        """[Coder] with Conversational Memory"""
        ps = self._get_project_state(state)
        iteration = state.get("iteration_count", 0) + 1
        
        print(f"\n💻 [Coder] VS Code Engine Activated (Iter: {iteration})")
        
        self._ensure_repo_map(ps)
        prompt_template = load_prompt(self.base_prompt_path, "coder.md")
        
        # Build Context
        user_input = ps.user_input
        file_ctx_str = "No file open."
        if ps.file_context:
            fc = ps.file_context
            content = fc.content
            if len(content) > 10000:
                content = content[:10000] + "\n...[Content Truncated]..."
            file_ctx_str = f"Filename: {fc.filename}\nLang: {fc.language_id}\nContent:\n{content}"
        
        repo_map_str = ps.repo_map if ps.repo_map else "(No Map)"
        
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
        
        # [Memory Fix] Inject Chat History
        contents = []
        # Add history messages
        if ps.full_chat_history:
            for msg in ps.full_chat_history:
                # Convert our internal format to Gemini format
                role = "user" if msg['role'] == 'user' else "model"
                contents.append({"role": role, "parts": [{"text": msg['content']}]})
        
        # Add current prompt
        contents.append({"role": "user", "parts": [{"text": formatted_prompt}]})
        
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=contents,
            system_instruction="You are a VS Code AI Copilot. Use MCP tools. Think step-by-step.",
            complexity="complex"
        )
        
        self._update_cost(ps, usage)
        code = response_text or ""
        
        # [Memory Update]
        ps.full_chat_history.append({"role": "user", "content": user_input}) # Simplified, better to add prompt
        ps.full_chat_history.append({"role": "ai", "content": code})

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
        """[Executor] Sandbox Runner"""
        ps = self._get_project_state(state)
        task_id = ps.task_id
        
        if "pending_tool_call" in ps.artifacts:
            print("   🛠️ Tool Call detected, waiting for Client...")
            return {
                "project_state": ps,
                "execution_stdout": "[Waiting for Client Tool Execution]",
                "execution_stderr": "",
                "execution_passed": True 
            }
        
        print(f"🚀 [Executor] Sandbox Running...")
        code = state.get("generated_code", "")
        
        if not code:
            return {"execution_passed": False, "execution_stderr": "No code."}
            
        sandbox = get_sandbox(task_id)
        if sandbox:
            stdout, stderr, images = sandbox.execute_code(code)
            passed = (not stderr or "Error" not in stderr)
            if images: ps.artifacts["image_artifacts"] = images

            return {
                "project_state": ps,
                "execution_stdout": stdout,
                "execution_stderr": stderr,
                "execution_passed": passed
            }
        else:
            return {"execution_passed": False, "execution_stderr": "Sandbox not found."}

    def reviewer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Functional Reviewer]"""
        print(f"🧐 [Functional Reviewer] Analyzing logic...")
        ps = self._get_project_state(state)
        
        stdout = state.get("execution_stdout", "")
        stderr = state.get("execution_stderr", "")

        prompt_template = load_prompt(self.base_prompt_path, "reviewer.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            stdout=stdout[:2000],
            stderr=stderr[:2000]
        )
        
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
            if start != -1:
                json_str = response_text[start:end+1]
                report = json.loads(json_str)
                status = report.get("status", "reject").lower()
                feedback = report.get("feedback", "")
        except: pass
        
        return {
            "functional_status": status,
            "functional_feedback": feedback
        }

    def security_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Security Audit] Parallel Node"""
        print(f"🛡️ [Security Guard] Auditing safety...")
        ps = self._get_project_state(state)
        
        code = state.get("generated_code", "")
        # Simple Security Prompt
        prompt = f"""
        Role: Security Auditor
        Task: Analyze the following code for security vulnerabilities (RCE, XSS, SQL Injection, Path Traversal).
        Code:
        {code}
        
        Output JSON: {{ "safe": boolean, "issues": "string" }}
        """
        
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": prompt}]}],
            complexity="simple"
        )
        self._update_cost(ps, usage)
        
        issues = "No issues."
        try:
            start = response_text.find("{")
            end = response_text.rfind("}")
            if start != -1:
                data = json.loads(response_text[start:end+1])
                if not data.get("safe", True):
                    issues = f"🚨 VULNERABILITY: {data.get('issues')}"
        except: pass
        
        return {"security_feedback": issues}

    def aggregator_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Aggregator] Merging Reviews"""
        print(f"📊 [Aggregator] Merging insights...")
        
        func_status = state.get("functional_status", "reject")
        func_feedback = state.get("functional_feedback", "")
        sec_feedback = state.get("security_feedback", "")
        
        final_status = func_status
        combined_feedback = f"Functional: {func_feedback}\n\nSecurity: {sec_feedback}"
        
        if "VULNERABILITY" in sec_feedback:
            final_status = "reject"
        
        return {
            "review_status": final_status,
            "review_feedback": combined_feedback
        }

    def reflector_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Reflector]"""
        print(f"🔧 [Reflector] Fixing strategy...")
        ps = self._get_project_state(state)
        
        prompt_template = load_prompt(self.base_prompt_path, "reflection.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            execution_stderr=state.get("execution_stderr", "")[:2000],
            review_report=state.get("review_feedback", "")
        )
        
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            system_instruction="Tech Lead Fixer.",
            complexity="complex"
        )
        self._update_cost(ps, usage)
        
        return {"reflection": response_text}

    def summarizer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Summarizer]"""
        print(f"📝 [Summarizer] Finalizing...")
        ps = self._get_project_state(state)
        
        prompt_template = load_prompt(self.base_prompt_path, "summarizer.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            execution_output=state.get("execution_stdout", "")[:1000]
        )
        
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            complexity="simple"
        )
        self._update_cost(ps, usage)
        
        ps.final_report = response_text
        return {"final_output": response_text, "project_state": ps}

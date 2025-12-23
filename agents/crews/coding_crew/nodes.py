import re
import json
import os
import asyncio
from typing import Dict, Any, List

from core.utils import load_prompt, calculate_cost
from core.models import GeminiModel, ProjectState
from config.keys import GEMINI_MODEL_NAME
from agents.crews.coding_crew.state import CodingCrewState
from tools.sandbox import run_python_code
from core.repo_map import RepositoryMapper 
from core.mcp_tool_definitions import MCPToolRegistry
from core.sandbox_manager import get_sandbox
from tools.browser import WebLoader # [Phase 2 Upgrade]

class CodingCrewNodes:
    def __init__(self, rotator):
        self.rotator = rotator
        self.base_prompt_path = os.path.join(os.path.dirname(__file__), "prompts")
        self.active_cache_name = None
        self.browser = WebLoader() # [Phase 2 Upgrade]

    def _get_project_state(self, state: CodingCrewState) -> ProjectState:
        return state.get("project_state")

    def _ensure_repo_map(self, ps: ProjectState):
        if not ps.repo_map and ps.workspace_root:
            print(f"🗺️ [RepoMap] Analyzing workspace: {ps.workspace_root}")
            mapper = RepositoryMapper(ps.workspace_root)
            ps.repo_map = mapper.generate_map()
            
            if not self.active_cache_name:
                print("💾 [Cache] Attempting to cache RepoMap...")
                system_content = f"You are a VS Code AI Engine.\n\nProject Context:\n{ps.repo_map}"
                self.active_cache_name = self.rotator.create_context_cache(
                    GEMINI_MODEL_NAME, 
                    system_content
                )

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

    def _extract_json(self, text: str) -> Any:
        text = text.strip()
        try:
            code_block_pattern = r"``" + r"`(?:json)?\s*([\[\{].*?[\]\}])\s*``" + r"`"
            match = re.search(code_block_pattern, text, re.DOTALL | re.IGNORECASE)
            if match:
                return json.loads(match.group(1))
            start = -1
            end = -1
            if '[' in text:
                start = text.find('[')
                end = text.rfind(']')
            elif '{' in text:
                start = text.find('{')
                end = text.rfind('}')
            if start != -1 and end != -1:
                return json.loads(text[start:end+1])
        except: pass
        return None

    def planner_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Architect] Generates a step-by-step plan."""
        print(f"\n🏗️ [Planner] Architecting solution...")
        ps = self._get_project_state(state)
        self._ensure_repo_map(ps)
        
        prompt_template = load_prompt(self.base_prompt_path, "planner.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            repo_map=ps.repo_map or "(No Map)",
            diagnostics=ps.file_context.content if ps.file_context and "error" in ps.file_context.content.lower() else "None"
        )
        
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            cached_content_name=self.active_cache_name,
            system_instruction="You are a Senior Software Architect. Return strictly JSON list.",
            complexity="complex"
        )
        self._update_cost(ps, usage)
        
        plan = self._extract_json(response_text)
        if not plan or not isinstance(plan, list):
            plan = ["Execute user request directly."]
            print(f"   ⚠️ Plan parsing failed, using fallback.")
        
        print(f"   📋 Generated Plan ({len(plan)} steps):")
        for i, step in enumerate(plan):
            print(f"      {i+1}. {step[:60]}...")

        return {"plan": plan, "current_step_index": 0, "project_state": ps}

    def coder_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Coder] with Conversational Memory & Plan Execution"""
        ps = self._get_project_state(state)
        
        plan = state.get("plan", [])
        step_idx = state.get("current_step_index", 0)
        current_step_desc = "Execute user request."
        if plan and step_idx < len(plan):
            current_step_desc = f"Step {step_idx + 1}/{len(plan)}: {plan[step_idx]}"
        
        iteration = state.get("iteration_count", 0) + 1
        print(f"\n💻 [Coder] VS Code Engine Activated (Iter: {iteration})")
        print(f"   🎯 Task: {current_step_desc}")
        
        self._ensure_repo_map(ps)
        prompt_template = load_prompt(self.base_prompt_path, "coder.md")
        
        augmented_input = f"GLOBAL GOAL: {ps.user_input}\nCURRENT TASK (Focus on this ONLY):\n{current_step_desc}"

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
        
        if state.get("linter_passed") is False:
             raw_feedback += f"\n\n[System] 🚨 PRE-FLIGHT LINTER FAILED:\n{state.get('execution_stderr')}"

        combined_feedback = raw_feedback
        if reflection:
             combined_feedback = f"### Tech Lead Fix Strategy:\n{reflection}\n\nReview Feedback: {raw_feedback}"
        
        mcp_instructions = MCPToolRegistry.get_system_prompt_addition()

        formatted_prompt = prompt_template.format(
            user_input=augmented_input,
            file_context=file_ctx_str,
            repo_map=repo_map_str, 
            feedback=combined_feedback or "None",
            mcp_tools=mcp_instructions
        )
        
        contents = []
        MAX_HISTORY = 10
        if ps.full_chat_history:
            recent_history = ps.full_chat_history[-MAX_HISTORY:]
            for msg in recent_history:
                role = "user" if msg['role'] == 'user' else "model"
                contents.append({"role": role, "parts": [{"text": msg['content']}]})
        
        contents.append({"role": "user", "parts": [{"text": formatted_prompt}]})
        
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=contents,
            system_instruction="You are a VS Code AI Copilot. Use MCP tools. Think step-by-step.",
            cached_content_name=self.active_cache_name,
            complexity="complex"
        )
        
        self._update_cost(ps, usage)
        code = response_text or ""
        
        ps.full_chat_history.append({"role": "user", "content": augmented_input})
        ps.full_chat_history.append({"role": "ai", "content": code})

        tool_call = MCPToolRegistry.parse_tool_call(response_text)
        
        if not tool_call:
            py_pattern = r"``" + r"`python(.*?)``" + r"`"
            match = re.search(py_pattern, response_text, re.DOTALL)
            if match:
                code = match.group(1).strip()
            elif "```" in response_text:
                 generic_pattern = r"``" + r"`(.*?)``" + r"`"
                 match = re.search(generic_pattern, response_text, re.DOTALL)
                 if match: code = match.group(1).strip()
            ps.code_blocks["coder"] = code
        else:
            ps.code_blocks["coder"] = response_text 
            ps.artifacts["pending_tool_call"] = tool_call

        return {
            "project_state": ps, 
            "generated_code": code,
            "iteration_count": iteration,
            "reflection": "",
            "linter_passed": True
        }

    def executor_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Executor] Sandbox Runner with Pre-flight Linter & Vision"""
        ps = self._get_project_state(state)
        task_id = ps.task_id
        
        if "pending_tool_call" in ps.artifacts:
            print("   🛠️ Tool Call detected, waiting for Client...")
            return {
                "project_state": ps,
                "execution_stdout": "[Waiting for Client Tool Execution]",
                "execution_stderr": "",
                "execution_passed": True,
                "linter_passed": True
            }
        
        print(f"🚀 [Executor] Sandbox Running...")
        code = state.get("generated_code", "")
        
        if not code:
            return {"execution_passed": False, "execution_stderr": "No code."}
            
        sandbox = get_sandbox(task_id)
        if sandbox:
            # 1. Pre-flight Linter Check
            linter_cmd = ""
            if "def " in code or "import " in code:
                 linter_cmd = "flake8 . --count --select=E9,F63,F7,F82 --show-source --statistics"

            if linter_cmd:
                 lint_out = sandbox.execute_command(linter_cmd)
                 if "syntax error" in lint_out.lower() or "traceback" in lint_out.lower():
                     print(f"   🚨 Linter Failed!")
                     return {
                         "execution_passed": False,
                         "linter_passed": False,
                         "execution_stderr": f"Linter Error:\n{lint_out}",
                         "execution_stdout": ""
                     }
            
            # 2. Normal Execution
            stdout, stderr, images = sandbox.execute_code(code)
            
            # [Phase 2 Upgrade] Vision: Auto-Screenshot if Localhost Server Detected
            # Check for patterns like "Running on [http://127.0.0.1:8000](http://127.0.0.1:8000)" or "Listening on port 3000"
            localhost_pattern = r"http://(?:localhost|127\.0\.0\.1|0\.0\.0\.0):(\d+)"
            match = re.search(localhost_pattern, stdout + stderr)
            
            if match:
                port = match.group(1)
                target_url = f"http://localhost:{port}"
                print(f"   👀 [Vision] Detected Web Server at {target_url}. Taking Screenshot...")
                
                try:
                    # Async call to playwright inside synchronous node (need proper loop handling)
                    # For simplicity, we assume browser.capture_screenshot works or returns empty
                    screenshot_b64 = asyncio.run(self.browser.capture_screenshot(target_url))
                    if screenshot_b64:
                        print("   📸 Screenshot captured!")
                        images.append({
                            "type": "image",
                            "filename": "server_preview.png",
                            "data": screenshot_b64
                        })
                except Exception as e:
                    print(f"   ⚠️ Screenshot failed: {e}")

            passed = True
            if "Error" in stderr or "Traceback" in stderr: passed = False
            if "[System] Docker unavailable" in stderr: passed = False

            if images: ps.artifacts["image_artifacts"] = images

            return {
                "project_state": ps,
                "execution_stdout": stdout,
                "execution_stderr": stderr,
                "execution_passed": passed,
                "linter_passed": True
            }
        else:
            return {"execution_passed": False, "execution_stderr": "Sandbox not found."}

    def reviewer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Functional Reviewer]"""
        if state.get("linter_passed") is False:
             return {
                 "functional_status": "reject",
                 "functional_feedback": "Pre-flight Linter Check Failed. Syntax errors detected."
             }

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
        
        # [Phase 2 Upgrade] Vision-Aware Review
        # If there are images, send them to Gemini Pro Vision!
        contents = [{"role": "user", "parts": [{"text": formatted_prompt}]}]
        
        if "image_artifacts" in ps.artifacts:
            for img in ps.artifacts["image_artifacts"]:
                # Append image data (Gemini API expects specific format)
                # Note: Rotator needs to handle inlineData
                if img.get("type") == "image":
                    # Remove prefix 'data:image/png;base64,'
                    b64_data = img["data"].split(",")[1]
                    contents[0]["parts"].append({
                        "inline_data": {
                            "mime_type": "image/png",
                            "data": b64_data
                        }
                    })
                    print("   🖼️ Attached image to Reviewer Prompt")

        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=contents,
            cached_content_name=self.active_cache_name,
            system_instruction="Strict JSON reviewer.",
            complexity="complex"
        )
        self._update_cost(ps, usage)
        
        status = "reject"
        feedback = "Parse Error"
        
        report = self._extract_json(response_text)
        if report:
            status = report.get("status", "reject").lower()
            feedback = report.get("feedback", "")
        else:
            feedback = f"Reviewer JSON Error: {response_text[:200]}"
        
        return {
            "functional_status": status,
            "functional_feedback": feedback
        }

    def security_node(self, state: CodingCrewState) -> Dict[str, Any]:
        ps = self._get_project_state(state)
        code = state.get("generated_code", "")
        prompt = f"Role: Security Auditor. Check for vulnerabilities.\nCode:\n{code}\nOutput JSON: {{ \"safe\": boolean, \"issues\": \"string\" }}"
        
        response, usage = self.rotator.call_gemini_with_rotation(
            GEMINI_MODEL_NAME, 
            [{"role": "user", "parts": [{"text": prompt}]}],
            cached_content_name=self.active_cache_name
        )
        self._update_cost(ps, usage)
        
        issues = "No issues."
        data = self._extract_json(response)
        if data and not data.get("safe", True):
             issues = f"🚨 VULNERABILITY: {data.get('issues')}"
        return {"security_feedback": issues}

    def aggregator_node(self, state: CodingCrewState) -> Dict[str, Any]:
        print(f"📊 [Aggregator] Merging insights...")
        if state.get("linter_passed") is False:
             return {"review_status": "reject", "review_feedback": "Linter Failed. Code has syntax errors."}
        
        func_status = state.get("functional_status", "reject")
        func_feedback = state.get("functional_feedback", "")
        sec_feedback = state.get("security_feedback", "")
        
        final_status = func_status
        combined_feedback = f"Functional: {func_feedback}\n\nSecurity: {sec_feedback}"
        if "VULNERABILITY" in sec_feedback: final_status = "reject"
        
        return {"review_status": final_status, "review_feedback": combined_feedback}

    def reflector_node(self, state: CodingCrewState) -> Dict[str, Any]:
        print(f"🔧 [Reflector] Fixing strategy...")
        ps = self._get_project_state(state)
        
        review_feedback = state.get("review_feedback", "")
        if "Reviewer failed to produce valid JSON" in review_feedback:
            return {"reflection": "The Reviewer could not parse its own output. Please strictly follow the JSON format and retry the same code logic."}

        prompt_template = load_prompt(self.base_prompt_path, "reflection.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            execution_stderr=state.get("execution_stderr", "")[:2000],
            review_report=review_feedback
        )
        
        response_text, usage = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            cached_content_name=self.active_cache_name,
            complexity="complex"
        )
        self._update_cost(ps, usage)
        return {"reflection": response_text}

    def summarizer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        print(f"📝 [Summarizer] Finalizing...")
        ps = self._get_project_state(state)
        
        prompt = load_prompt(self.base_prompt_path, "summarizer.md").format(
             user_input=ps.user_input,
             code=state.get("generated_code", ""),
             execution_output=state.get("execution_stdout", "")
        )
        
        resp, usage = self.rotator.call_gemini_with_rotation(
            GEMINI_MODEL_NAME,
            [{"role": "user", "parts": [{"text": prompt}]}],
            cached_content_name=self.active_cache_name
        )
        self._update_cost(ps, usage)
        ps.final_report = resp
        return {"final_output": resp, "project_state": ps}

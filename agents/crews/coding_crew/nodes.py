import re
import json
import os
import asyncio
from typing import Dict, Any

from core.utils import load_prompt
from core.models import GeminiModel, ProjectState
from config.keys import GEMINI_MODEL_NAME
from agents.crews.coding_crew.state import CodingCrewState
from tools.sandbox import run_python_code

class CodingCrewNodes:
    def __init__(self, rotator):
        self.rotator = rotator
        self.base_prompt_path = os.path.join(os.path.dirname(__file__), "prompts")

    def _get_project_state(self, state: CodingCrewState) -> ProjectState:
        """Helper to safely extract ProjectState"""
        return state.get("project_state")

    def coder_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """
        [Coder] VS Code Aware
        """
        ps = self._get_project_state(state)
        iteration = state.get("iteration_count", 0) + 1
        
        print(f"\n💻 [Coder] VS Code Engine Activated (Iter: {iteration})")
        
        prompt_template = load_prompt(self.base_prompt_path, "coder.md")
        
        # --- Context Injection ---
        user_input = ps.user_input
        file_ctx_str = "No file open."
        
        if ps.file_context:
            fc = ps.file_context
            # [Optimization] 上下文截断，防止 Token 爆炸
            content = fc.content
            if len(content) > 20000:
                content = content[:10000] + "\n...[Content Truncated]...\n" + content[-10000:]

            file_ctx_str = f"""
### 📄 Current File Context (VS Code)
- **Filename**: `{fc.filename}`
- **Language**: `{fc.language_id}`
- **Cursor Line**: {fc.cursor_line}
- **Selection**: 
```
{fc.selection or "(No selection)"}
```
- **Full Content**:
```
{content}
```
"""
        
        reflection = state.get("reflection", "")
        raw_feedback = state.get("review_feedback", "")
        combined_feedback = raw_feedback
        if reflection:
             combined_feedback = f"### Tech Lead Fix Strategy:\n{reflection}\n\nReview Feedback: {raw_feedback}"
        
        formatted_prompt = prompt_template.format(
            user_input=user_input,
            file_context=file_ctx_str,
            feedback=combined_feedback or "None"
        )
        
        response = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            system_instruction="你是一个集成在 VS Code 中的 AI 编程助手。",
            complexity="complex"
        )
        
        code = response or ""
        match = re.search(r"```python(.*?)```", response, re.DOTALL)
        if match:
            code = match.group(1).strip()
        elif "```" in response:
             match = re.search(r"```(.*?)```", response, re.DOTALL)
             if match: code = match.group(1).strip()

        ps.code_blocks["coder"] = code
        
        return {
            "project_state": ps, 
            "generated_code": code,
            "iteration_count": iteration,
            "reflection": ""
        }

    async def executor_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Executor] Sandbox Runner (Async Wrapper)"""
        # [Optimization] 异步化：防止 Docker 阻塞主线程
        print(f"🚀 [Executor] Sandbox Running...")
        code = state.get("generated_code", "")
        ps = self._get_project_state(state)
        
        if not code:
            return {"execution_passed": False, "execution_stderr": "No code."}
            
        # 获取当前的 Event Loop 执行阻塞操作
        loop = asyncio.get_running_loop()
        result = await loop.run_in_executor(None, run_python_code, code)
        
        passed = (result["returncode"] == 0)
        status_icon = "✅" if passed else "❌"
        print(f"   {status_icon} Exit Code: {result['returncode']}")
        
        # [Optimization] 将图片产物存入 ProjectState
        if result.get("images"):
             ps.artifacts["image_artifacts"] = result["images"]

        return {
            "project_state": ps,
            "execution_stdout": result["stdout"],
            "execution_stderr": result["stderr"],
            "execution_passed": passed,
            "image_artifacts": result.get("images", [])
        }

    def reviewer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Reviewer] Code Review"""
        print(f"🧐 [Reviewer] Analyzing...")
        ps = self._get_project_state(state)
        
        # [Optimization] 日志截断
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
        
        response = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            system_instruction="Strict JSON reviewer.",
            complexity="complex"
        )
        
        # [Optimization] 更稳健的 JSON 解析
        status = "reject"
        feedback = "Parse Error"
        report = {}
        try:
            # 尝试提取第一个 { 和最后一个 } 之间的内容
            json_match = re.search(r"(\{.*\})", response, re.DOTALL)
            json_str = json_match.group(1) if json_match else response
            # 清理可能的 markdown 标记
            json_str = json_str.replace("```json", "").replace("```", "")
            
            report = json.loads(json_str)
            status = report.get("status", "reject").lower()
            feedback = report.get("feedback", "")
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
        """[Reflector] Root Cause Analysis"""
        print(f"🔧 [Reflector] Fixing strategy...")
        ps = self._get_project_state(state)
        
        # [Optimization] 日志截断
        stderr = state.get("execution_stderr", "None")
        if len(stderr) > 2000: stderr = stderr[:2000] + "...(truncated)"

        prompt_template = load_prompt(self.base_prompt_path, "reflection.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            execution_stderr=stderr,
            review_report=json.dumps(state.get("review_report", {}))
        )
        
        response = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            system_instruction="Tech Lead Fixer.",
            complexity="complex"
        )
        return {"reflection": response}

    def summarizer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Summarizer]"""
        print(f"📝 [Summarizer] Finalizing...")
        ps = self._get_project_state(state)
        
        prompt_template = load_prompt(self.base_prompt_path, "summarizer.md")
        formatted_prompt = prompt_template.format(
            user_input=ps.user_input,
            code=state.get("generated_code", ""),
            execution_output=state.get("execution_stdout", "")[:1000] # 截断
        )
        
        response = self.rotator.call_gemini_with_rotation(
            model_name=GEMINI_MODEL_NAME,
            contents=[{"role": "user", "parts": [{"text": formatted_prompt}]}],
            system_instruction="Summary.",
            complexity="simple"
        )
        
        ps.final_report = response
        return {"final_output": response, "project_state": ps}

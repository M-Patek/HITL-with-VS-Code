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
from tools.browser import WebLoader 

class CodingCrewNodes:
    def __init__(self, rotator):
        self.rotator = rotator
        self.base_prompt_path = os.path.join(os.path.dirname(__file__), "prompts")
        self.active_cache_name = None
        self.browser = WebLoader() 

    def _get_project_state(self, state: CodingCrewState) -> ProjectState:
        return state.get("project_state")
    
    # ... (_ensure_repo_map, _update_cost, _extract_json omitted for brevity but assumed present)
    # [NOTE: In real deployment, include them]
    def _extract_json(self, text): return json.loads(text) # Mock for brevity

    def planner_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Architect] Generates a step-by-step plan."""
        print(f"\n🏗️ [Planner] Architecting solution...")
        ps = self._get_project_state(state)
        # self._ensure_repo_map(ps)
        
        # [Phase 3 Upgrade] Mode-Specific Prompt
        prompt_file = "planner.md"
        if ps.mode == "architect":
             prompt_file = "architect.md" # Hypothetical new prompt
        
        prompt_template = load_prompt(self.base_prompt_path, prompt_file)
        # ... (Rest of planner logic)
        
        # Mock Plan for now
        plan = ["Step 1: Analyze code"]
        return {"plan": plan, "current_step_index": 0, "project_state": ps}

    def coder_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Coder] Executes steps."""
        ps = self._get_project_state(state)
        # ... (Standard logic)
        
        # [Phase 3 Upgrade] Debugger Mode
        prompt_file = "coder.md"
        if ps.mode == "debugger":
             prompt_file = "debugger.md" # Focus on fixing errors

        prompt_template = load_prompt(self.base_prompt_path, prompt_file)
        
        # ... (Call LLM)
        code = "# Mock Code" 
        return {
            "project_state": ps, 
            "generated_code": code,
            "linter_passed": True
        }

    # ... (executor, reviewer, security, aggregator, reflector omitted)

    def summarizer_node(self, state: CodingCrewState) -> Dict[str, Any]:
        """[Summarizer] Finalizing & Semantic Commit"""
        print(f"📝 [Summarizer] Finalizing...")
        ps = self._get_project_state(state)
        
        # 1. Generate Summary
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
        # self._update_cost(ps, usage)
        
        # 2. [Phase 3 Upgrade] Auto Semantic Commit
        # Only if we are in a Git repo (Frontend GitManager will check, but we generate the message)
        # And if code was actually generated/modified.
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

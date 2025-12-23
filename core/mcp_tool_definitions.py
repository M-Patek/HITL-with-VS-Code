from typing import List, Dict, Any
import re

class MCPToolDefinitions:
    """
    Defines the tools available to the Agents via a pseudo-MCP (Model Context Protocol) format.
    Includes helpers for parsing XML-based tool calls.
    """

    @staticmethod
    def get_coding_tools() -> List[Dict[str, Any]]:
        return [
            {
                "name": "write_to_file",
                "description": "Writes code to a file. Overwrites if exists.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string"},
                        "content": {"type": "string"}
                    },
                    "required": ["filepath", "content"]
                }
            },
            {
                "name": "read_file",
                "description": "Reads the content of a file.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "filepath": {"type": "string"}
                    },
                    "required": ["filepath"]
                }
            },
            {
                "name": "execute_command",
                "description": "Executes a shell command in the sandbox.",
                "parameters": {
                    "type": "object",
                    "properties": {
                        "command": {"type": "string"}
                    },
                    "required": ["command"]
                }
            },
            # Add other tools as per original implementation
        ]

    @staticmethod
    def parse_tool_calls(llm_output: str) -> List[Dict[str, Any]]:
        """
        Parses XML-like tool calls from LLM output.
        Robustly handles multiple tool calls.
        """
        tool_calls = []
        
        # Split by the tool_code tag
        snippets = llm_output.split("<tool_code>")
        for snippet in snippets[1:]:
            end_idx = snippet.find("</tool_code>")
            if end_idx == -1: continue
            
            block = snippet[:end_idx]
            
            name = MCPToolDefinitions._extract_tag_content(block, "name")
            params_block = MCPToolDefinitions._extract_tag_content(block, "parameters")
            
            parameters = {}
            if params_block:
                # Use Regex to extract all parameter tags
                # Matches <key>value</key> patterns inside parameters block
                param_matches = re.findall(r'<(\w+)>(.*?)</\1>', params_block, re.DOTALL)
                for p_name, p_val in param_matches:
                    parameters[p_name] = p_val.strip()

            if name:
                tool_calls.append({
                    "name": name,
                    "parameters": parameters
                })
                
        return tool_calls

    @staticmethod
    def _extract_tag_content(xml_snippet: str, tag_name: str) -> str:
        """Helper to extract content between tags robustly"""
        start_tag = f"<{tag_name}>"
        end_tag = f"</{tag_name}>"
        
        start_idx = xml_snippet.find(start_tag)
        if start_idx == -1:
            return ""
            
        # [Fix] Security: Use find() instead of rfind()
        # Prevents "Tag Injection" where malicious content could inject a fake closing tag
        # and hide code execution payload.
        content_start = start_idx + len(start_tag)
        
        # Find the FIRST occurrence of the closing tag after the start tag
        end_idx = xml_snippet.find(end_tag, content_start)
        
        if end_idx != -1:
            content = xml_snippet[content_start : end_idx]
            # Handle CDATA if present
            if content.strip().startswith("<![CDATA[") and content.strip().endswith("]]>"):
                content = content.strip()[9:-3]
            return content.strip()
            
        return ""

import json
import re

class MCPToolRegistry:
    """
    [Roo Code Soul] MCP (Model Context Protocol) 工具注册表
    定义 AI 可以调用的客户端能力。
    """
    
    @staticmethod
    def get_system_prompt_addition() -> str:
        """
        生成注入到 System Prompt 的工具说明 (Roo Code 风格 XML)
        [Phase 2 Upgrade] 新增 apply_diff 工具
        """
        return """
## 🛠️ Available Tools (MCP)

你可以使用以下工具来操作 VS Code 环境。请以 XML 格式调用工具。

1. **Write File** (创建新文件或全量覆盖小文件)
   <tool_code>
   <tool_name>write_to_file</tool_name>
   <parameters>
     <path>src/utils.py</path>
     <content>
       import os
       ...
     </content>
   </parameters>
   </tool_code>

2. **Apply Diff** (修改现有大文件 - 推荐)
   使用精确的 search_block 定位代码块，并替换为 replace_block。
   <tool_code>
   <tool_name>apply_diff</tool_name>
   <parameters>
     <path>src/utils.py</path>
     <search_block>
       def old_function(x):
           return x + 1
     </search_block>
     <replace_block>
       def old_function(x):
           return x * 2
     </replace_block>
   </parameters>
   </tool_code>

3. **Execute Command** (在终端运行命令)
   <tool_code>
   <tool_name>execute_command</tool_name>
   <parameters>
     <command>npm install lodash</command>
   </parameters>
   </tool_code>

**规则:**
- 优先使用 `apply_diff` 修改现有代码，除非文件很小。
- `search_block` 必须完全匹配文件中的原始代码（包括空格和缩进）。
- 每次回复只能包含一个工具调用。
"""

    @staticmethod
    def parse_tool_call(llm_response: str) -> dict:
        """
        解析 LLM 输出中的 XML 工具调用
        """
        try:
            # 1. 尝试提取最外层 <tool_code>
            match = re.search(r"<tool_code>\s*(.*?)\s*</tool_code>", llm_response, re.DOTALL | re.IGNORECASE)
            if not match:
                return None
                
            inner_xml = match.group(1).strip()
            
            # 2. 提取 tool_name
            name_match = re.search(r"<tool_name>\s*(.*?)\s*</tool_name>", inner_xml, re.DOTALL | re.IGNORECASE)
            if not name_match:
                return None
            tool_name = name_match.group(1).strip()
            
            # 3. 提取 parameters 块
            params_match = re.search(r"<parameters>\s*(.*?)\s*</parameters>", inner_xml, re.DOTALL | re.IGNORECASE)
            if not params_match:
                return None
            params_xml = params_match.group(1).strip()

            params = {}
            
            if tool_name == "write_to_file":
                path_match = re.search(r"<path>\s*(.*?)\s*</path>", params_xml, re.DOTALL | re.IGNORECASE)
                content = MCPToolRegistry._extract_tag_content(params_xml, "content")
                
                if path_match:
                    params["path"] = path_match.group(1).strip()
                    params["content"] = content
            
            elif tool_name == "apply_diff":
                # [Phase 2 Upgrade] 解析 apply_diff 参数
                path_match = re.search(r"<path>\s*(.*?)\s*</path>", params_xml, re.DOTALL | re.IGNORECASE)
                search_block = MCPToolRegistry._extract_tag_content(params_xml, "search_block")
                replace_block = MCPToolRegistry._extract_tag_content(params_xml, "replace_block")
                
                if path_match:
                    params["path"] = path_match.group(1).strip()
                    params["search_block"] = search_block
                    params["replace_block"] = replace_block

            elif tool_name == "execute_command":
                cmd_match = re.search(r"<command>\s*(.*?)\s*</command>", params_xml, re.DOTALL | re.IGNORECASE)
                if cmd_match:
                    params["command"] = cmd_match.group(1).strip()
                    
            if not params:
                return None
                
            return {
                "tool": tool_name,
                "params": params
            }
        except Exception as e:
            print(f"❌ XML Parse Error: {e}")
            return None

    @staticmethod
    def _extract_tag_content(xml_snippet: str, tag_name: str) -> str:
        """Helper to extract content between tags robustly"""
        start_tag = f"<{tag_name}>"
        end_tag = f"</{tag_name}>"
        
        start_idx = xml_snippet.find(start_tag)
        end_idx = xml_snippet.rfind(end_tag)
        
        if start_idx != -1 and end_idx != -1 and end_idx > start_idx:
            content = xml_snippet[start_idx + len(start_tag) : end_idx]
            # Handle CDATA if present
            if content.strip().startswith("<![CDATA[") and content.strip().endswith("]]>"):
                content = content.strip()[9:-3]
            return content.strip() # Strip leading/trailing whitespace usually helps
        return ""

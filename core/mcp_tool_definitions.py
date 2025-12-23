import json

class MCPToolRegistry:
    """
    [Roo Code Soul] MCP (Model Context Protocol) 工具注册表
    定义 AI 可以调用的客户端能力。
    """
    
    @staticmethod
    def get_system_prompt_addition() -> str:
        """
        生成注入到 System Prompt 的工具说明 (Roo Code 风格 XML)
        """
        return """
## 🛠️ Available Tools (MCP)

你可以使用以下工具来操作 VS Code 环境。请以 XML 格式调用工具。

1. **Write File** (创建或覆盖文件)
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

2. **Execute Command** (在终端运行命令)
   <tool_code>
   <tool_name>execute_command</tool_name>
   <parameters>
     <command>npm install lodash</command>
   </parameters>
   </tool_code>

**规则:**
- 每次回复只能包含一个工具调用。
- 在调用工具前，先简短解释你的意图。
- 严禁在没有用户批准的情况下破坏性地删除文件。
"""

    @staticmethod
    def parse_tool_call(llm_response: str) -> dict:
        """
        解析 LLM 输出中的 XML 工具调用
        """
        import re
        
        # 提取 <tool_code> 块
        match = re.search(r"<tool_code>(.*?)</tool_code>", llm_response, re.DOTALL)
        if not match:
            return None
            
        inner_xml = match.group(1).strip()
        
        # 提取 tool_name
        name_match = re.search(r"<tool_name>(.*?)</tool_name>", inner_xml)
        if not name_match:
            return None
        tool_name = name_match.group(1).strip()
        
        # 提取 parameters
        params = {}
        # 简单的 XML 解析 (针对 write_to_file 和 execute_command)
        if tool_name == "write_to_file":
            path_match = re.search(r"<path>(.*?)</path>", inner_xml)
            content_match = re.search(r"<content>(.*?)</content>", inner_xml, re.DOTALL)
            if path_match and content_match:
                params["path"] = path_match.group(1).strip()
                params["content"] = content_match.group(1).strip() # 保留首尾空白可能很重要，但这里先strip防抖
        
        elif tool_name == "execute_command":
            cmd_match = re.search(r"<command>(.*?)</command>", inner_xml)
            if cmd_match:
                params["command"] = cmd_match.group(1).strip()
                
        if not params:
            return None
            
        return {
            "tool": tool_name,
            "params": params
        }

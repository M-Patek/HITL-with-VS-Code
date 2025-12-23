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
- 必须严格遵守 XML 格式。
- 在调用工具前，先简短解释你的意图。
- 严禁在没有用户批准的情况下破坏性地删除文件。
"""

    @staticmethod
    def parse_tool_call(llm_response: str) -> dict:
        """
        解析 LLM 输出中的 XML 工具调用
        [Security Fix] 增强正则鲁棒性，防止解析失败
        """
        try:
            # 1. 尝试提取最外层 <tool_code>
            # 使用 DOTALL 模式 (.) 匹配换行符，使用非贪婪匹配 (*?)
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
                # 提取 path
                path_match = re.search(r"<path>\s*(.*?)\s*</path>", params_xml, re.DOTALL | re.IGNORECASE)
                # 提取 content (内容可能包含各种字符，必须谨慎)
                content_match = re.search(r"<content>\s*(.*?)\s*</content>", params_xml, re.DOTALL | re.IGNORECASE)
                
                if path_match and content_match:
                    params["path"] = path_match.group(1).strip()
                    # 去除首尾的 CDATA 标记（如果模型生成了）
                    raw_content = content_match.group(1)
                    if raw_content.startswith("<![CDATA[") and raw_content.endswith("]]>"):
                        raw_content = raw_content[9:-3]
                    params["content"] = raw_content.strip()
            
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

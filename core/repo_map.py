import os
import logging
from typing import Dict, List, Optional

# 尝试导入 tree-sitter，如果环境不支持则提供优雅降级
try:
    from tree_sitter_languages import get_language, get_parser
    TREE_SITTER_AVAILABLE = True
except ImportError:
    TREE_SITTER_AVAILABLE = False

logger = logging.getLogger("RepoMapper")

class RepositoryMapper:
    """
    [Aider Soul] 代码库地图生成器
    使用 Tree-sitter 解析 AST，提取项目骨架，为 LLM 提供全局上下文。
    """
    def __init__(self, root_path: str):
        self.root_path = root_path
        self.map_cache: Dict[str, str] = {}
        
        # 语言映射
        self.lang_map = {
            ".py": "python",
            ".ts": "typescript",
            ".tsx": "typescript",
            ".js": "javascript",
            ".jsx": "javascript",
            ".go": "go",
            ".rs": "rust",
            ".java": "java",
            ".cpp": "cpp",
            ".c": "c"
        }

    def generate_map(self, max_files: int = 50) -> str:
        """生成整个项目的压缩地图"""
        if not TREE_SITTER_AVAILABLE:
            return "[RepoMap] Tree-sitter module not installed. Install `tree-sitter-languages` to enable AST mapping."
        
        if not self.root_path or not os.path.exists(self.root_path):
            return "[RepoMap] Workspace root not found."

        repo_map = []
        file_count = 0
        
        # 排除目录
        exclude_dirs = {'.git', 'node_modules', '__pycache__', 'dist', 'build', '.vscode', 'venv', 'env'}

        for root, dirs, files in os.walk(self.root_path):
            # 过滤目录
            dirs[:] = [d for d in dirs if d not in exclude_dirs]
            
            for file in files:
                if file_count >= max_files:
                    break
                
                ext = os.path.splitext(file)[1]
                if ext not in self.lang_map:
                    continue
                
                full_path = os.path.join(root, file)
                rel_path = os.path.relpath(full_path, self.root_path)
                
                # 解析单个文件
                file_skeleton = self._parse_file(full_path, rel_path, self.lang_map[ext])
                if file_skeleton:
                    repo_map.append(file_skeleton)
                    file_count += 1
        
        header = f"### 🗺️ Repository Map (Aider-style AST Summary)\n(Current Directory: {self.root_path})\n\n"
        return header + "\n\n".join(repo_map)

    def _parse_file(self, file_path: str, rel_path: str, lang_name: str) -> Optional[str]:
        """解析文件生成骨架"""
        try:
            with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                code = f.read()
            
            if not code.strip():
                return None

            language = get_language(lang_name)
            parser = get_parser(lang_name)
            tree = parser.parse(bytes(code, "utf8"))
            
            # 使用查询提取定义 (Simplified for demo)
            # 这里的查询语句适配 Python 和 TS/JS
            query_scm = ""
            if lang_name == "python":
                query_scm = """
                (class_definition name: (identifier) @name) @class
                (function_definition name: (identifier) @name) @function
                """
            elif lang_name in ["typescript", "javascript"]:
                query_scm = """
                (class_declaration name: (type_identifier) @name) @class
                (function_declaration name: (identifier) @name) @function
                (interface_declaration name: (type_identifier) @name) @interface
                """
            
            if not query_scm:
                return f"{rel_path}:\n  (AST parsing not configured for {lang_name})"

            query = language.query(query_scm)
            captures = query.captures(tree.root_node)
            
            definitions = []
            for node, tag in captures:
                if tag == "name":
                    # 这是一个简单的层级缩进逻辑
                    indent = "  "
                    # 如果父节点是类，则增加缩进
                    parent = node.parent
                    while parent:
                        if parent.type in ['class_definition', 'class_declaration']:
                            indent += "  "
                        parent = parent.parent
                    
                    # 获取定义类型
                    def_type = node.parent.type.replace('_definition', '').replace('_declaration', '')
                    definitions.append(f"{indent}{def_type} {node.text.decode('utf8')}")

            if not definitions:
                return None

            return f"{rel_path}:\n" + "\n".join(definitions)

        except Exception as e:
            logger.warning(f"Failed to parse {rel_path}: {e}")
            return None

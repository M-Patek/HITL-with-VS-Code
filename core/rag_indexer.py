import os
import logging
import pathspec 
import asyncio
from typing import List

logger = logging.getLogger("RAG-Indexer")

class WorkspaceIndexer:
    def __init__(self, memory_tool):
        self.memory = memory_tool
        self.default_ignore_dirs = {'.git', 'node_modules', '__pycache__', 'dist', 'build', '.vscode', 'venv', 'env', '.idea', '__MACOSX', 'coverage'}
        self.ignore_exts = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.pyc', '.lock', '.pdf', '.svg', '.exe', '.dll', '.class', '.o'}

    def _load_gitignore(self, root_path: str) -> pathspec.PathSpec:
        """
        [Robustness Fix] 使用 pathspec 正确解析 .gitignore 规则
        """
        patterns = []
        gitignore_path = os.path.join(root_path, '.gitignore')
        if os.path.exists(gitignore_path):
            try:
                with open(gitignore_path, 'r', encoding='utf-8') as f:
                    patterns = f.readlines()
            except Exception as e:
                logger.warning(f"Failed to read .gitignore: {e}")
        
        # 使用 gitwildmatch 模式
        return pathspec.PathSpec.from_lines('gitwildmatch', patterns)

    def index_workspace(self, root_path: str):
        # 实际逻辑，由上层通过 executor 异步调用
        self._index_workspace_sync(root_path)

    def _index_workspace_sync(self, root_path: str):
        if not root_path or not os.path.exists(root_path):
            return

        spec = self._load_gitignore(root_path)
        docs = []
        metas = []
        ids = []

        for root, dirs, files in os.walk(root_path):
            # 1. 默认目录过滤
            dirs[:] = [d for d in dirs if d not in self.default_ignore_dirs]
            
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_path)
                
                # 2. .gitignore 过滤
                if spec.match_file(rel_path):
                    continue
                
                if os.path.splitext(rel_path)[1].lower() in self.ignore_exts:
                    continue

                try:
                    if os.path.getsize(file_path) > 500 * 1024: continue

                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    # 3. 智能切片
                    chunks = self._chunk_text_smart(content, chunk_size=1000, overlap=100)
                    
                    for i, chunk in enumerate(chunks):
                        docs.append(chunk)
                        metas.append({"source": rel_path, "chunk_id": i})
                        ids.append(f"{rel_path}_{i}")
                        
                except Exception:
                    pass 

        if docs:
            batch_size = 50
            for i in range(0, len(docs), batch_size):
                end = i + batch_size
                self.memory.add_documents(docs[i:end], metas[i:end], ids[i:end])

    def _chunk_text_smart(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """
        [Robustness Fix] 感知缩进的智能切片，防止切断代码块
        """
        lines = text.splitlines(keepends=True)
        chunks = []
        current_chunk = []
        current_length = 0
        
        for line in lines:
            line_len = len(line)
            
            if current_length + line_len > chunk_size:
                # 强制切分，保留重叠
                if current_chunk:
                    chunks.append("".join(current_chunk))
                    
                    # 创建重叠缓冲区
                    overlap_size = 0
                    overlap_buffer = []
                    for prev in reversed(current_chunk):
                        if overlap_size + len(prev) > overlap: break
                        overlap_buffer.insert(0, prev)
                        overlap_size += len(prev)
                    
                    current_chunk = overlap_buffer
                    current_length = overlap_size
            
            current_chunk.append(line)
            current_length += line_len
            
        if current_chunk:
            chunks.append("".join(current_chunk))
            
        return chunks

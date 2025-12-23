import os
import logging
import fnmatch
from typing import List, Set

logger = logging.getLogger("RAG-Indexer")

class WorkspaceIndexer:
    """
    [Continue Soul] 负责扫描工作区并建立索引
    """
    def __init__(self, memory_tool):
        self.memory = memory_tool
        # 默认忽略列表
        self.default_ignore_dirs = {'.git', 'node_modules', '__pycache__', 'dist', 'build', '.vscode', 'venv', 'env', '.idea', '__MACOSX', 'coverage'}
        self.ignore_exts = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.pyc', '.lock', '.pdf', '.svg', '.exe', '.dll', '.class', '.o'}

    def _load_gitignore(self, root_path: str) -> List[str]:
        """
        [Smart Indexing] 读取 .gitignore 模式
        """
        patterns = []
        gitignore_path = os.path.join(root_path, '.gitignore')
        if os.path.exists(gitignore_path):
            try:
                with open(gitignore_path, 'r', encoding='utf-8') as f:
                    for line in f:
                        line = line.strip()
                        if line and not line.startswith('#'):
                            patterns.append(line)
                logger.info(f"📜 Loaded {len(patterns)} patterns from .gitignore")
            except Exception as e:
                logger.warning(f"Failed to read .gitignore: {e}")
        return patterns

    def _is_ignored(self, rel_path: str, gitignore_patterns: List[str]) -> bool:
        """
        检查文件是否应被忽略 (fnmatch implementation)
        """
        # 1. Check default hardcoded rules first (Optimization)
        parts = rel_path.split(os.sep)
        for part in parts:
            if part in self.default_ignore_dirs:
                return True
        
        ext = os.path.splitext(rel_path)[1].lower()
        if ext in self.ignore_exts:
            return True

        # 2. Check gitignore patterns
        # fnmatch is not perfect for .gitignore (no negation support, etc.) but good enough for simple cases
        for pattern in gitignore_patterns:
            # Handle directory patterns ending with /
            if pattern.endswith('/'):
                pattern = pattern.rstrip('/')
                # If any part of path matches directory pattern
                if any(fnmatch.fnmatch(p, pattern) for p in parts):
                    return True
            
            # Match full relative path or filename
            if fnmatch.fnmatch(rel_path, pattern) or fnmatch.fnmatch(os.path.basename(rel_path), pattern):
                return True
                
        return False

    def index_workspace(self, root_path: str):
        """全量索引 (建议在后台运行)"""
        if not root_path or not os.path.exists(root_path):
            logger.warning("Invalid root path for indexing")
            return

        logger.info(f"🕵️ Starting workspace indexing: {root_path}")
        gitignore_patterns = self._load_gitignore(root_path)
        
        docs = []
        metas = []
        ids = []

        for root, dirs, files in os.walk(root_path):
            # 过滤目录 (In-place modification for os.walk)
            # 这里先用 default_ignore_dirs 快速过滤，细粒度过滤在 file loop 中做
            dirs[:] = [d for d in dirs if d not in self.default_ignore_dirs]
            
            for file in files:
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_path)
                
                # [Smart Indexing] Check ignore rules
                if self._is_ignored(rel_path, gitignore_patterns):
                    continue
                
                try:
                    # [Safety] Skip large files > 500KB
                    if os.path.getsize(file_path) > 500 * 1024:
                        continue

                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    chunks = self._chunk_text_smart(content, chunk_size=1000, overlap=100)
                    
                    for i, chunk in enumerate(chunks):
                        docs.append(chunk)
                        metas.append({"source": rel_path, "chunk_id": i})
                        ids.append(f"{rel_path}_{i}")
                        
                except Exception as e:
                    pass 

        # 批量存入
        if docs:
            batch_size = 50
            for i in range(0, len(docs), batch_size):
                end = i + batch_size
                self.memory.add_documents(docs[i:end], metas[i:end], ids[i:end])
            
            logger.info(f"✅ Indexed {len(docs)} chunks from workspace.")

    def _chunk_text_smart(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        """
        [Optimization] 基于换行的智能切分，避免切断代码行
        """
        chunks = []
        lines = text.splitlines(keepends=True)
        current_chunk = []
        current_length = 0
        
        for line in lines:
            if current_length + len(line) > chunk_size and current_chunk:
                full_chunk = "".join(current_chunk)
                chunks.append(full_chunk)
                
                overlap_buffer = []
                overlap_len = 0
                for prev_line in reversed(current_chunk):
                    if overlap_len + len(prev_line) > overlap:
                        break
                    overlap_buffer.insert(0, prev_line)
                    overlap_len += len(prev_line)
                
                current_chunk = overlap_buffer
                current_length = overlap_len
            
            current_chunk.append(line)
            current_length += len(line)
        
        if current_chunk:
            chunks.append("".join(current_chunk))
            
        return chunks

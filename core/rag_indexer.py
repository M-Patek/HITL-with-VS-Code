import os
import logging
from typing import List

logger = logging.getLogger("RAG-Indexer")

class WorkspaceIndexer:
    """
    [Continue Soul] 负责扫描工作区并建立索引
    """
    def __init__(self, memory_tool):
        self.memory = memory_tool
        # 忽略列表
        self.ignore_dirs = {'.git', 'node_modules', '__pycache__', 'dist', 'build', '.vscode', 'venv', 'env', '.idea', '__MACOSX'}
        self.ignore_exts = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.pyc', '.lock', '.pdf', '.svg', '.exe', '.dll'}

    def index_workspace(self, root_path: str):
        """全量索引 (建议在后台运行)"""
        if not root_path or not os.path.exists(root_path):
            logger.warning("Invalid root path for indexing")
            return

        logger.info(f"🕵️ Starting workspace indexing: {root_path}")
        
        docs = []
        metas = []
        ids = []

        for root, dirs, files in os.walk(root_path):
            # 过滤目录
            dirs[:] = [d for d in dirs if d not in self.ignore_dirs]
            
            for file in files:
                ext = os.path.splitext(file)[1].lower()
                if ext in self.ignore_exts:
                    continue
                
                file_path = os.path.join(root, file)
                rel_path = os.path.relpath(file_path, root_path)
                
                try:
                    with open(file_path, 'r', encoding='utf-8', errors='ignore') as f:
                        content = f.read()
                        
                    # [Optimization] 更智能的切片逻辑
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
                # 当前块满了，保存
                full_chunk = "".join(current_chunk)
                chunks.append(full_chunk)
                
                # 处理 Overlap: 保留末尾几行作为下一块的开头
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

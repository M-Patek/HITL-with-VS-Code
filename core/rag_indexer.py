import os
import uuid
from typing import List, Tuple
import logging

logger = logging.getLogger("RAG-Indexer")

class WorkspaceIndexer:
    """
    [Continue Soul] 负责扫描工作区并建立索引
    """
    def __init__(self, memory_tool):
        self.memory = memory_tool
        # 忽略列表
        self.ignore_dirs = {'.git', 'node_modules', '__pycache__', 'dist', 'build', '.vscode', 'venv', 'env', '.idea'}
        self.ignore_exts = {'.png', '.jpg', '.jpeg', '.gif', '.ico', '.pyc', '.lock', '.pdf', '.svg'}

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
                        
                    # 简单的切片逻辑 (按 1000 字符切分)
                    # 生产环境建议用 RecursiveCharacterTextSplitter
                    chunks = self._chunk_text(content, chunk_size=1000, overlap=100)
                    
                    for i, chunk in enumerate(chunks):
                        docs.append(chunk)
                        metas.append({"source": rel_path, "chunk_id": i})
                        ids.append(f"{rel_path}_{i}")
                        
                except Exception as e:
                    pass # Ignore read errors

        # 批量存入
        if docs:
            # 每次存 50 个防止请求过大
            batch_size = 50
            for i in range(0, len(docs), batch_size):
                end = i + batch_size
                self.memory.add_documents(docs[i:end], metas[i:end], ids[i:end])
            
            logger.info(f"✅ Indexed {len(docs)} chunks from workspace.")

    def _chunk_text(self, text: str, chunk_size: int, overlap: int) -> List[str]:
        chunks = []
        start = 0
        text_len = len(text)
        
        while start < text_len:
            end = start + chunk_size
            chunks.append(text[start:end])
            start += chunk_size - overlap
            
        return chunks

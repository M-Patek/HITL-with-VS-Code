import os
import logging
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Optional, Dict, Any
import google.generativeai as genai

# 配置 Logger
logger = logging.getLogger("Tools-LocalRAG")

class GeminiEmbeddingFunction(chromadb.EmbeddingFunction):
    """
    使用 Google Gemini API 生成 Embeddings 的适配器
    """
    def __init__(self, api_key: str):
        genai.configure(api_key=api_key)

    def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
        # 使用 embedding-001 模型 (高效且免费额度高)
        model = 'models/text-embedding-004'
        embeddings = []
        # 批量处理以提高效率
        for text in input:
            try:
                # 简单的重试逻辑可以在这里添加
                result = genai.embed_content(
                    model=model,
                    content=text,
                    task_type="retrieval_document"
                )
                embeddings.append(result['embedding'])
            except Exception as e:
                logger.error(f"Embedding failed: {e}")
                # Fallback zero vector or skip
                embeddings.append([0.0] * 768) 
        return embeddings

class LocalRAGMemory:
    """
    [Continue Soul] 本地代码库记忆
    使用 ChromaDB 存储代码片段，支持语义搜索 (@Codebase)。
    """
    def __init__(self, api_key: str, persist_dir: str = "./db_chroma"):
        self.client = chromadb.PersistentClient(path=persist_dir)
        
        # 使用 Gemini Embeddings (保持生态一致性)
        self.embedding_fn = GeminiEmbeddingFunction(api_key)
        
        self.collection = self.client.get_or_create_collection(
            name="workspace_index",
            embedding_function=self.embedding_fn
        )
        logger.info(f"🧠 Local RAG initialized at {persist_dir}")

    def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]], ids: List[str]):
        """存入文档切片"""
        if not documents: return
        try:
            self.collection.upsert(
                documents=documents,
                metadatas=metadatas,
                ids=ids
            )
            logger.info(f"📥 Indexed {len(documents)} chunks.")
        except Exception as e:
            logger.error(f"Failed to index documents: {e}")

    def query(self, query_text: str, n_results: int = 5) -> str:
        """语义搜索，返回格式化的上下文"""
        try:
            results = self.collection.query(
                query_texts=[query_text],
                n_results=n_results
            )
            
            context_parts = []
            if results['documents'] and results['documents'][0]:
                for i, doc in enumerate(results['documents'][0]):
                    meta = results['metadatas'][0][i]
                    source = meta.get('source', 'unknown')
                    context_parts.append(f"File: {source}\nSnippet:\n{doc}")
            
            if not context_parts:
                return ""
                
            return "\n---\n".join(context_parts)
        except Exception as e:
            logger.error(f"RAG Query failed: {e}")
            return ""

    def clear(self):
        """清空索引 (用于重建)"""
        try:
            self.client.delete_collection("workspace_index")
            self.collection = self.client.create_collection(
                name="workspace_index",
                embedding_function=self.embedding_fn
            )
        except:
            pass

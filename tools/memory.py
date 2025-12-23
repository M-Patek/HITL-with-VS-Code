import os
import logging
import chromadb
from chromadb.utils import embedding_functions
from typing import List, Optional, Dict, Any
import google.generativeai as genai
import threading

# 配置 Logger
logger = logging.getLogger("Tools-LocalRAG")

# [Concurrency Fix] 本地锁，用于保护 Embedding 时的全局配置
_EMBED_LOCK = threading.Lock()

class GeminiEmbeddingFunction(chromadb.EmbeddingFunction):
    """
    使用 Google Gemini API 生成 Embeddings 的适配器
    """
    def __init__(self, api_key: str):
        # [Concurrency Fix] 不要在 init 时配置全局 key，这会在多线程环境下被覆盖
        self.api_key = api_key

    def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
        model = 'models/text-embedding-004'
        embeddings = []
        
        # [Concurrency Fix] 加锁执行配置和请求
        with _EMBED_LOCK:
            try:
                # 每次调用前配置 Key
                genai.configure(api_key=self.api_key)
                
                for text in input:
                    try:
                        result = genai.embed_content(
                            model=model,
                            content=text,
                            task_type="retrieval_document"
                        )
                        embeddings.append(result['embedding'])
                    except Exception as e:
                        logger.error(f"Embedding failed: {e}")
                        embeddings.append([0.0] * 768) 
            except Exception as e:
                logger.error(f"Global configuration failed: {e}")
                return [[0.0] * 768] * len(input)

        return embeddings

class LocalRAGMemory:
    """
    [Continue Soul] 本地代码库记忆
    """
    def __init__(self, api_key: str, persist_dir: Optional[str] = None):
        # [Security Fix] 优先使用环境变量传入的绝对路径，防止在插件目录创建数据
        if not persist_dir:
            persist_dir = os.getenv("SWARM_DATA_DIR")
        
        if not persist_dir:
            persist_dir = os.path.join(os.path.expanduser("~"), ".gemini_swarm", "db_chroma")

        # 确保目录存在
        os.makedirs(persist_dir, exist_ok=True)
            
        self.client = chromadb.PersistentClient(path=persist_dir)
        
        self.embedding_fn = GeminiEmbeddingFunction(api_key)
        
        self.collection = self.client.get_or_create_collection(
            name="workspace_index",
            embedding_function=self.embedding_fn
        )
        logger.info(f"🧠 Local RAG initialized at {persist_dir}")

    def add_documents(self, documents: List[str], metadatas: List[Dict[str, Any]], ids: List[str]):
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
        try:
            self.client.delete_collection("workspace_index")
            self.collection = self.client.create_collection(
                name="workspace_index",
                embedding_function=self.embedding_fn
            )
        except:
            pass

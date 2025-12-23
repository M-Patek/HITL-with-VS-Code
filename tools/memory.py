import os
import logging
import chromadb
import google.generativeai as genai
import threading
from typing import List, Optional, Dict, Any

logger = logging.getLogger("Tools-LocalRAG")

_EMBED_LOCK = threading.Lock()

class GeminiEmbeddingFunction(chromadb.EmbeddingFunction):
    def __init__(self, api_key: str):
        self.api_key = api_key

    def __call__(self, input: chromadb.Documents) -> chromadb.Embeddings:
        model = 'models/text-embedding-004'
        embeddings = []
        
        with _EMBED_LOCK:
            try:
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
                        logger.error(f"Embedding failed for doc: {e}")
                        # [Data Quality Fix] 禁止填充零向量
                        # 抛出异常以中断批处理，防止污染数据库
                        raise e 
            except Exception as e:
                logger.error(f"Batch embedding failed: {e}")
                raise e

        return embeddings

class LocalRAGMemory:
    def __init__(self, api_key: str, persist_dir: Optional[str] = None):
        if not persist_dir:
            persist_dir = os.getenv("SWARM_DATA_DIR")
        
        if not persist_dir:
            persist_dir = os.path.join(os.getcwd(), ".swarm_data", "db_chroma")

        os.makedirs(persist_dir, exist_ok=True)
            
        self.client = chromadb.PersistentClient(path=persist_dir)
        self.embedding_fn = GeminiEmbeddingFunction(api_key)
        
        self.collection = self.client.get_or_create_collection(
            name="workspace_index",
            embedding_function=self.embedding_fn
        )

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
            
            return "\n---\n".join(context_parts)
        except Exception as e:
            logger.error(f"RAG Query failed: {e}")
            return ""

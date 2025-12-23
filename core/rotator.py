import google.generativeai as genai
from google.api_core import exceptions
from google.generativeai import caching # [Phase 1 Upgrade] Import Caching
import time
import logging
import threading
import datetime
from typing import List, Dict, Any, Tuple, Optional

logger = logging.getLogger("GeminiRotator")

# [Concurrency Fix] 全局锁，防止多线程下 genai.configure 互相覆盖
_GENAI_GLOBAL_LOCK = threading.Lock()

class AllKeysExhaustedError(Exception):
    """Raised when all available API keys have been tried and failed."""
    pass

class GeminiKeyRotator:
    def __init__(self, base_url: str, keys: List[str]):
        if not keys:
            raise ValueError("API Key list cannot be empty.")
            
        self.keys = keys
        self.current_index = 0
        self.base_url = base_url
        # 这是用于轮询 Key 索引的锁
        self._index_lock = threading.Lock()
        
        # [Phase 1 Upgrade] 简单的缓存元数据记录 (Key -> CacheName)
        # 注意：Context Caching 是绑定到 Project/Key 的，轮询 Key 可能会导致缓存失效或无法访问。
        # 策略：如果启用了缓存，暂时锁定使用当前的 Key。
        self.active_cache_name = None
        self.cached_key_index = -1

    def _get_next_key(self):
        with self._index_lock:
            # 如果有活跃的缓存，且我们还在重试范围内，优先尝试使用创建了缓存的那个 Key
            if self.active_cache_name and self.cached_key_index != -1:
                return self.keys[self.cached_key_index]

            key = self.keys[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.keys)
        return key

    def create_context_cache(self, model_name: str, content: str, ttl_minutes: int = 10) -> Optional[str]:
        """
        [Phase 1 Upgrade] 创建 Gemini Context Cache
        """
        # 获取当前指向的 Key
        key = self.keys[self.current_index]
        
        with _GENAI_GLOBAL_LOCK:
            try:
                genai.configure(api_key=key)
                
                # 创建缓存
                # 注意：Context Caching 有最小 token 限制 (通常 32k+)，太短的内容建缓存反而慢
                # 这里为了演示，假设内容已经足够长。实际使用中可以加长度判断。
                if len(content) < 1000: # 稍微放宽限制以便测试
                    logger.info("Content too short for caching, skipping.")
                    return None

                # 使用当前时间戳防止重名冲突
                unique_suffix = int(time.time())
                cache = caching.CachedContent.create(
                    model=model_name,
                    display_name=f"gemini_swarm_repo_map_{unique_suffix}",
                    system_instruction=content,
                    ttl=datetime.timedelta(minutes=ttl_minutes),
                )
                
                self.active_cache_name = cache.name
                self.cached_key_index = self.current_index
                logger.info(f"💾 Context Cache created: {cache.name} (Key Index: {self.current_index})")
                return cache.name
                
            except Exception as e:
                logger.warning(f"Failed to create context cache: {e}")
                return None

    def call_gemini_with_rotation(
        self, 
        model_name: str, 
        contents: List[Dict[str, Any]], 
        system_instruction: str = None,
        cached_content_name: str = None, # [Phase 1 Upgrade] 传入缓存名称
        complexity: str = "simple",
        max_retries: int = None # If None, defaults to len(keys)
    ) -> Tuple[str, Dict[str, int]]:
        """
        调用 Gemini API 并自动轮询 Key。
        [Concurrency Fix] 使用全局锁保护配置和生成过程。
        [Phase 1 Upgrade] 支持 Cached Content。
        """
        if max_retries is None:
            max_retries = len(self.keys) * 2 # Allow 2 cycles
            
        retries = 0
        last_error = None
        
        while retries < max_retries:
            # 如果指定了缓存，强行使用绑定了缓存的那个 Key，不轮询
            if cached_content_name and self.cached_key_index != -1:
                key = self.keys[self.cached_key_index]
            else:
                key = self._get_next_key()

            try:
                # [Concurrency Fix] 这是一个临界区。
                with _GENAI_GLOBAL_LOCK:
                    genai.configure(api_key=key)
                    
                    # [Phase 1 Upgrade] 处理缓存逻辑
                    model = None
                    if cached_content_name:
                         # 必须通过 get 获取缓存对象
                        try:
                            # 注意：CachedContent.get() 可能不直接返回可用于 GenerativeModel 的对象
                            # 但 SDK 通常允许通过 from_cached_content 加载
                            cache_obj = caching.CachedContent.get(cached_content_name)
                            model = genai.GenerativeModel.from_cached_content(cached_content=cache_obj)
                            logger.info(f"⚡ Using Cached Context: {cached_content_name}")
                        except Exception as cache_err:
                            logger.warning(f"Cache lookup failed: {cache_err}, falling back to regular")
                            # 降级：如果找不到缓存，使用普通系统提示
                            model = genai.GenerativeModel(
                                model_name=model_name,
                                system_instruction=system_instruction
                            )
                    else:
                        model = genai.GenerativeModel(
                            model_name=model_name,
                            system_instruction=system_instruction
                        )
                    
                    generation_config = genai.types.GenerationConfig(
                        temperature=0.2 if complexity == "complex" else 0.1,
                        max_output_tokens=8192
                    )

                    response = model.generate_content(
                        contents,
                        generation_config=generation_config
                    )
                    
                    # Usage extraction
                    usage = {
                        "prompt_tokens": 0,
                        "completion_tokens": 0,
                        "total_tokens": 0
                    }
                    
                    if hasattr(response, 'usage_metadata'):
                        usage["prompt_tokens"] = response.usage_metadata.prompt_token_count
                        usage["completion_tokens"] = response.usage_metadata.candidates_token_count
                        usage["total_tokens"] = response.usage_metadata.total_token_count
                    
                    return response.text, usage

            except exceptions.ResourceExhausted:
                # 如果是缓存模式且配额耗尽，这是一条死胡同，必须放弃缓存，切换 Key 重试
                if cached_content_name:
                    logger.warning(f"Key for Cache {cached_content_name} exhausted. Abandoning cache.")
                    cached_content_name = None # 降级为无缓存模式
                    self.active_cache_name = None
                
                logger.warning(f"Key {key[:8]}... exhausted. Rotating.")
                retries += 1
                time.sleep(1)
                last_error = "Quota Exceeded"
            except Exception as e:
                logger.error(f"Gemini API Error with key {key[:8]}...: {e}")
                retries += 1
                last_error = str(e)
                if cached_content_name:
                     cached_content_name = None # 出错也降级
                time.sleep(2 * min(retries, 5)) # Exponential backoff capped
        
        # If we reach here, all retries failed
        logger.error("All API Keys exhausted or failed.")
        raise AllKeysExhaustedError(f"Failed after {retries} retries. Last error: {last_error}")

import google.generativeai as genai
from google.api_core import exceptions
import time
import logging
import threading
from typing import List, Dict, Any, Tuple

logger = logging.getLogger("GeminiRotator")

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
        self._lock = threading.Lock()

    def _get_next_key(self):
        with self._lock:
            key = self.keys[self.current_index]
            self.current_index = (self.current_index + 1) % len(self.keys)
        return key

    def call_gemini_with_rotation(
        self, 
        model_name: str, 
        contents: List[Dict[str, Any]], 
        system_instruction: str = None,
        complexity: str = "simple",
        max_retries: int = None # If None, defaults to len(keys)
    ) -> Tuple[str, Dict[str, int]]:
        """
        调用 Gemini API 并自动轮询 Key。
        不使用全局 configure，而是每次调用时配置。
        """
        if max_retries is None:
            max_retries = len(self.keys) * 2 # Allow 2 cycles
            
        retries = 0
        last_error = None
        
        while retries < max_retries:
            key = self._get_next_key()
            try:
                # [Refactor] Localize configuration per request if possible.
                # Since SDK is global state based, we still have to use configure, 
                # BUT we minimize the window and assume sequential execution within this function scope for the client creation.
                # Actually, standard SDK creates a client. We can pass api_key to GenerativeModel? 
                # No, GenerativeModel uses global config by default.
                # Best practice is to assume single threaded or accept the race. 
                # But here we will try to re-configure.
                
                genai.configure(api_key=key)
                
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
                logger.warning(f"Key {key[:8]}... exhausted. Rotating.")
                retries += 1
                time.sleep(1)
                last_error = "Quota Exceeded"
            except Exception as e:
                logger.error(f"Gemini API Error with key {key[:8]}...: {e}")
                retries += 1
                last_error = str(e)
                time.sleep(2 * min(retries, 5)) # Exponential backoff capped
        
        # If we reach here, all retries failed
        logger.error("All API Keys exhausted or failed.")
        raise AllKeysExhaustedError(f"Failed after {retries} retries. Last error: {last_error}")

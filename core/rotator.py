import google.generativeai as genai
from google.api_core import exceptions
import random
import time
import logging
from typing import List, Dict, Any, Optional, Tuple

logger = logging.getLogger("GeminiRotator")

class GeminiKeyRotator:
    def __init__(self, base_url: str, keys: List[str]):
        self.keys = keys
        self.current_index = 0
        self.base_url = base_url

    def _get_next_key(self):
        key = self.keys[self.current_index]
        self.current_index = (self.current_index + 1) % len(self.keys)
        return key

    def call_gemini_with_rotation(
        self, 
        model_name: str, 
        contents: List[Dict[str, Any]], 
        system_instruction: str = None,
        complexity: str = "simple",
        max_retries: int = 3
    ) -> Tuple[str, Dict[str, int]]: # [Changed] Return Tuple
        """
        调用 Gemini API 并自动轮询 Key
        Returns: (generated_text, usage_metadata)
        """
        retries = 0
        while retries < max_retries:
            key = self._get_next_key()
            try:
                genai.configure(api_key=key)
                model = genai.GenerativeModel(
                    model_name=model_name,
                    system_instruction=system_instruction
                )
                
                # 配置生成参数
                generation_config = genai.types.GenerationConfig(
                    temperature=0.2 if complexity == "complex" else 0.1,
                    max_output_tokens=8192
                )

                response = model.generate_content(
                    contents,
                    generation_config=generation_config
                )
                
                # 提取 Usage Metadata
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
            except Exception as e:
                logger.error(f"Gemini API Error: {e}")
                retries += 1
                time.sleep(2 * retries)
        
        return "", {"prompt_tokens": 0, "completion_tokens": 0, "total_tokens": 0}

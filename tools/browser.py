import requests
from bs4 import BeautifulSoup
import logging
import socket
from urllib.parse import urlparse
import ipaddress

logger = logging.getLogger("Tools-Browser")

class WebLoader:
    """
    [Continue Soul] 网页内容抓取工具 (@Docs)
    用于实时抓取在线文档，扩充 AI 的知识库。
    """
    def __init__(self):
        # 伪装成浏览器
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def _is_safe_url(self, url: str) -> bool:
        """
        [Security Fix] SSRF 防御检测
        检查解析后的 IP 是否为私有地址或环回地址。
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname:
                return False

            # 解析 IP
            try:
                ip = socket.gethostbyname(hostname)
            except socket.gaierror:
                return False # 无法解析的域名视为不安全或不可达

            ip_obj = ipaddress.ip_address(ip)
            
            # 检查是否为私有、环回、链路本地等保留地址
            if (ip_obj.is_private or 
                ip_obj.is_loopback or 
                ip_obj.is_link_local or 
                ip_obj.is_reserved):
                logger.warning(f"🚫 Blocked SSRF attempt to {hostname} ({ip})")
                return False
                
            # 仅允许 http 和 https
            if parsed.scheme not in ('http', 'https'):
                return False

            return True

        except Exception as e:
            logger.error(f"URL validation error: {e}")
            return False

    def scrape_url(self, url: str) -> str:
        """抓取 URL 并转换为简化文本"""
        
        # 1. 安全检查
        if not self._is_safe_url(url):
            return f"[Security Blocked] Access to {url} is denied due to SSRF protection."

        try:
            logger.info(f"🌐 Scraping: {url}")
            # 设置合理的 timeout
            response = requests.get(url, headers=self.headers, timeout=5)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            
            # 2. 移除无关元素 (噪音清洗)
            for element in soup(["script", "style", "nav", "footer", "iframe", "svg", "noscript"]):
                element.decompose()
            
            # 3. 提取标题
            title = soup.title.string if soup.title else url
            
            # 4. 提取主要文本
            text = soup.get_text(separator='\n')
            
            # 5. 清理空行和多余空格
            lines = (line.strip() for line in text.splitlines())
            chunks = (phrase.strip() for line in lines for phrase in line.split("  "))
            clean_text = '\n'.join(chunk for chunk in chunks if chunk)
            
            # 6. 截断以防过长
            max_length = 20000 
            if len(clean_text) > max_length:
                clean_text = clean_text[:max_length] + "\n\n...[Content Truncated]..."

            return f"### 🌐 Source: {title}\nURL: {url}\n\n{clean_text}"
            
        except Exception as e:
            logger.error(f"Scrape failed: {e}")
            return f"[Error] Could not scrape {url}: {str(e)}"

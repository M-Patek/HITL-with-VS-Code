import requests
from bs4 import BeautifulSoup
import logging
import socket
from urllib.parse import urlparse
import ipaddress
import asyncio
import base64

# [Phase 2 Upgrade] Try importing Playwright
try:
    from playwright.async_api import async_playwright
    PLAYWRIGHT_AVAILABLE = True
except ImportError:
    PLAYWRIGHT_AVAILABLE = False

logger = logging.getLogger("Tools-Browser")

class WebLoader:
    """
    [Continue Soul] 网页内容抓取工具 (@Docs)
    [Phase 2 Upgrade] 集成 Playwright 用于截图 (Vision)
    """
    def __init__(self):
        self.headers = {
            "User-Agent": "Mozilla/5.0 (Macintosh; Intel Mac OS X 10_15_7) AppleWebKit/537.36 (KHTML, like Gecko) Chrome/120.0.0.0 Safari/537.36"
        }

    def _is_safe_url(self, url: str) -> bool:
        """
        [Security Fix] SSRF 防御检测
        """
        try:
            parsed = urlparse(url)
            hostname = parsed.hostname
            if not hostname: return False

            # Allow localhost for Phase 2 Screenshot feature
            if hostname in ["localhost", "127.0.0.1", "0.0.0.0"]:
                return True

            try:
                ip = socket.gethostbyname(hostname)
            except socket.gaierror:
                return False 

            ip_obj = ipaddress.ip_address(ip)
            if (ip_obj.is_private or ip_obj.is_loopback or ip_obj.is_link_local):
                # For scraping external docs, block private IPs.
                # But for our screenshot feature, we might need to allow it.
                # Context-aware check needed. For now, strict for external scraping.
                return False 
                
            if parsed.scheme not in ('http', 'https'): return False
            return True
        except Exception:
            return False

    def scrape_url(self, url: str) -> str:
        """抓取 URL 并转换为简化文本 (同步模式, 用于 RAG)"""
        if not self._is_safe_url(url):
            return f"[Security Blocked] Access to {url} is denied."

        try:
            logger.info(f"🌐 Scraping: {url}")
            response = requests.get(url, headers=self.headers, timeout=5)
            response.raise_for_status()
            
            soup = BeautifulSoup(response.text, 'html.parser')
            for element in soup(["script", "style", "nav", "footer", "iframe", "svg"]):
                element.decompose()
            
            title = soup.title.string if soup.title else url
            text = soup.get_text(separator='\n')
            
            # Clean text
            lines = (line.strip() for line in text.splitlines())
            clean_text = '\n'.join(chunk for chunk in lines if chunk)
            
            return f"### 🌐 Source: {title}\nURL: {url}\n\n{clean_text[:20000]}"
            
        except Exception as e:
            return f"[Error] Could not scrape {url}: {str(e)}"

    async def capture_screenshot(self, url: str) -> str:
        """
        [Phase 2 Upgrade] 使用 Playwright 截图
        返回: Base64 编码的 PNG 字符串 (data:image/png;base64,...)
        """
        if not PLAYWRIGHT_AVAILABLE:
            return ""

        # Localhost check is allowed here
        logger.info(f"📸 Taking screenshot of {url}")
        
        try:
            async with async_playwright() as p:
                # Use webkit or chromium
                browser = await p.chromium.launch(headless=True)
                page = await browser.new_page()
                
                # Set viewport size
                await page.set_viewport_size({"width": 1280, "height": 800})
                
                try:
                    await page.goto(url, timeout=5000, wait_until="domcontentloaded")
                except:
                    # Even if timeout, page might be partially loaded
                    pass
                
                # Screenshot
                screenshot_bytes = await page.screenshot(type="png")
                await browser.close()
                
                b64_img = base64.b64encode(screenshot_bytes).decode('utf-8')
                return f"data:image/png;base64,{b64_img}"
                
        except Exception as e:
            logger.error(f"Screenshot failed: {e}")
            return ""

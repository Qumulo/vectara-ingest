"""
Base class for web content extractors.
Allows choosing between different extraction backends via configuration.
"""

import logging
from abc import ABC, abstractmethod
from typing import Dict, Optional
from urllib.parse import urljoin
from bs4 import BeautifulSoup
from omegaconf import OmegaConf

logger = logging.getLogger(__name__)


def parse_static_html(html: str, url: str, final_url: Optional[str] = None) -> Optional[Dict]:
    """
    Build a fetch_page_contents-style result from server-rendered HTML.

    Returns None when the page text is too sparse (<= 500 chars) to be anything
    but an SPA shell that needs browser rendering.
    """
    soup = BeautifulSoup(html, 'html.parser')
    static_text = soup.get_text(separator=' ', strip=True)
    if len(static_text.strip()) <= 500:
        return None
    result = {
        'text': static_text,
        'html': html,
        'title': soup.title.string if soup.title else '',
        'url': final_url or url,
        'links': [a['href'] for a in soup.find_all('a', href=True)],
        'images': [],
        'tables': []
    }
    # Extract images with same filtering as the browser path
    for img_tag in soup.find_all('img'):
        src = img_tag.get('src', '')
        if not src or src.startswith('data:') or src.startswith('blob:'):
            continue
        try:
            w = int(img_tag.get('width', '0') or '0')
        except (ValueError, TypeError):
            w = 0
        try:
            h = int(img_tag.get('height', '0') or '0')
        except (ValueError, TypeError):
            h = 0
        if (w > 0 and w < 10) or (h > 0 and h < 10):
            continue
        result['images'].append({'src': urljoin(url, src), 'alt': img_tag.get('alt', '')})
    logger.info(f"Static fetch used for {url}: {len(static_text)} chars")
    logger.info(f"For crawled page {url}: images = {len(result['images'])}, "
                f"tables = {len(result['tables'])}, links = {len(result['links'])}")
    return result


class WebExtractorBase(ABC):
    """Abstract base class for web content extractors"""
    
    def __init__(self, cfg: OmegaConf, timeout: int = 90, post_load_timeout: int = 5):
        self.cfg = cfg
        self.timeout = timeout
        self.post_load_timeout = post_load_timeout
    
    @abstractmethod
    def fetch_page_contents(
        self,
        url: str,
        extract_tables: bool = False,
        extract_images: bool = False,
        remove_code: bool = False,
        html_processing: Optional[dict] = None,
        debug: bool = False
    ) -> Dict:
        """
        Fetch content from URL.
        
        Returns:
            dict with 'text', 'html', 'title', 'url', 'links', 'images', 'tables'
        """
        pass
    
    @abstractmethod
    def check_download_or_pdf(self, url: str, headers: dict, timeout: int = 5000) -> Dict:
        """Check if URL triggers download or serves PDF content directly"""
        pass
    
    @abstractmethod
    def url_triggers_download(self, url: str) -> bool:
        """Check if URL triggers a download"""
        pass
    
    @abstractmethod
    def cleanup(self):
        """Clean up resources"""
        pass


def create_web_extractor(cfg: OmegaConf, scrape_method: str = None, **kwargs) -> WebExtractorBase:
    """
    Factory function to create a web content extractor based on configuration.
    
    Args:
        cfg: Configuration object
        scrape_method: Override extraction method ('playwright' or 'scrapy')
        **kwargs: Additional arguments for the specific backend
        
    Returns:
        WebExtractorBase instance
    """
    # Use provided scrape_method or default to playwright for backward compatibility
    backend = (scrape_method or 'playwright').lower()
    
    if backend == "playwright":
        from core.web_content_extractor import WebContentExtractor
        return WebContentExtractor(cfg, **kwargs)
    
    elif backend == "scrapy":
        from core.scrapy_content_extractor import ScrapyContentExtractor
        return ScrapyContentExtractor(cfg, **kwargs)
    
    else:
        raise ValueError(f"Unknown scrape_method: {backend}. Supported: playwright, scrapy")
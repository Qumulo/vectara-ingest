from core.crawler import Crawler
from bs4 import BeautifulSoup
import logging
from urllib.parse import urljoin, urlparse
import re
from collections import deque
from core.utils import create_session_with_retries, binary_extensions, RateLimiter, setup_logging
from typing import Tuple, Set
from core.indexer import Indexer
import psutil
import ray

class UrlCrawlWorker(object):
    def __init__(self, indexer: Indexer, crawler: Crawler, num_per_second: int):
        self.indexer = indexer
        self.crawler = crawler
        self.rate_limiter = RateLimiter(num_per_second)

    def setup(self):
        self.indexer.setup()
        setup_logging()

    def process(self, url: str, source: str):
        if url is None:
            logging.info("URL is None, skipping")
            return -1
        metadata = {"source": source, "url": url}
        logging.info(f"Crawling and indexing {url}")
        try:
            with self.rate_limiter:
                succeeded = self.indexer.index_url(url, metadata=metadata, html_processing=self.crawler.html_processing)
            if not succeeded:
                logging.info(f"Indexing failed for {url}")
            else:
                logging.info(f"Indexing {url} was successful")
        except Exception as e:
            import traceback
            logging.error(
                f"Error while indexing {url}: {e}, traceback={traceback.format_exc()}"
            )
            return -1
        return 0

class DocsCrawler(Crawler):

    def concat_url_and_href(self, url: str, href: str) -> str:
        if href.startswith('http'):
            return href
        else:
            if 'index.html?' in href:
                href = href.replace('index.html?', '/')     # special fix for Spark docs
            joined = urljoin(url, href)
            return joined

    def get_url_content(self, url: str) -> Tuple[str, BeautifulSoup]:
        headers = {
            'User-Agent': 'Mozilla/5.0',
            'Accept': 'text/html,application/xhtml+xml,application/xml;q=0.9,image/webp,*/*;q=0.8'
        }
        response = self.session.get(url, headers=headers)
        if response.status_code != 200:
            logging.info(f"Failed to crawl {url}, response code is {response.status_code}")
            return None, None

        # check for refresh redirect        
        soup = BeautifulSoup(response.content, 'html.parser')
        meta_refresh = soup.find('meta', attrs={'http-equiv': 'refresh'})
        if meta_refresh:
            href = meta_refresh['content'].split('url=')[-1]            # type: ignore
            url = self.concat_url_and_href(url, href)
            response = self.session.get(url, headers=headers)
            if response.status_code != 200:
                logging.info(f"Failed to crawl redirect {url}, response code is {response.status_code}")
                return None, None

        page_content = BeautifulSoup(response.content, 'lxml')
        return url, page_content

    def collect_urls(self, base_url: str, num_per_second: int) -> None:
        new_urls = deque([base_url])
        rate_limiter = RateLimiter(num_per_second)
        # Crawl each URL in the queue
        while len(new_urls):
            n_urls = len(self.crawled_urls)
            if n_urls>0 and n_urls%100==0:
                logging.info(f"Currently have {n_urls} crawled urls identified")
            
            # pop the left-most URL from new_urls
            url = new_urls.popleft()

            try:
                with rate_limiter:
                    url, page_content = self.get_url_content(url)
                if url is None:
                    continue
                self.crawled_urls.add(url)

                # Find all the new URLs in the page's content and add them into the queue
                if page_content:
                    for link in page_content.find_all('a'):
                        href = link.get('href')
                        if href is None:
                            continue
                        abs_url = self.concat_url_and_href(url, href)
                        if ((any([r.match(abs_url) for r in self.pos_regex])) and                           # match any of the positive regexes
                            (not any([r.match(abs_url) for r in self.neg_regex])) and                       # don't match any of the negative regexes
                            (abs_url.startswith("http")) and                                                # starts with http/https
                            (abs_url not in self.ignored_urls) and                                          # not previously ignored    
                            (len(urlparse(abs_url).fragment)==0) and                                        # does not have fragment
                            (not any([abs_url.endswith(ext) for ext in self.extensions_to_ignore]))):    # not any of the specified extensions to ignore
                                # add URL if needed
                                if abs_url not in self.crawled_urls and abs_url not in new_urls:
                                    new_urls.append(abs_url)
                        else:
                            self.ignored_urls.add(abs_url)

            except Exception as e:
                import traceback
                logging.info(f"Error crawling {url}: {e}, traceback={traceback.format_exc()}")
                continue

    def crawl(self) -> None:
        self.crawled_urls: Set[str] = set()
        self.ignored_urls: Set[str] = set()
        self.extensions_to_ignore = list(set(self.cfg.docs_crawler.extensions_to_ignore + binary_extensions))
        self.pos_regex = [re.compile(r) for r in self.cfg.docs_crawler.get("pos_regex", [])]
        self.neg_regex = [re.compile(r) for r in self.cfg.docs_crawler.get("neg_regex", [])]
        self.html_processing = self.cfg.docs_crawler.get('html_processing', {})

        self.session = create_session_with_retries()

        source = self.cfg.docs_crawler.docs_system
        ray_workers = self.cfg.docs_crawler.get("ray_workers", 0)            # -1: use ray with ALL cores, 0: dont use ray
        num_per_second = max(self.cfg.docs_crawler.get("num_per_second", 10), 1)

        for base_url in self.cfg.docs_crawler.base_urls:
            self.collect_urls(base_url, num_per_second=num_per_second)

        logging.info(f"Found {len(self.crawled_urls)} urls in {self.cfg.docs_crawler.base_urls}")
        if self.cfg.docs_crawler.get("crawl_report", False):
            logging.info(f"Collected {len(self.crawled_urls)} URLs to crawl and index. See urls_indexed.txt for a full report.")
            with open('/home/vectara/env/urls_indexed.txt', 'w') as f:
                for url in sorted(list(self.crawled_urls)):
                    f.write(url + '\n')
        else:
            logging.info(f"Collected {len(self.crawled_urls)} URLs to crawl and index.")

        if ray_workers == -1:
            ray_workers = psutil.cpu_count(logical=True)
        if ray_workers > 0:
            logging.info(f"Using {ray_workers} ray workers")
            self.indexer.p = self.indexer.browser = None
            ray.init(num_cpus=ray_workers, log_to_driver=True, include_dashboard=False)
            actors = [ray.remote(UrlCrawlWorker).remote(self.indexer, self, num_per_second) for _ in range(ray_workers)]
            for a in actors:
                a.setup.remote()
            pool = ray.util.ActorPool(actors)
            _ = list(pool.map(lambda a, u: a.process.remote(u, source=source), self.crawled_urls))
                
        else:
            crawl_worker = UrlCrawlWorker(self.indexer, self, num_per_second)
            for inx, url in enumerate(self.crawled_urls):
                if inx % 100 == 0:
                    logging.info(f"Crawling URL number {inx+1} out of {len(self.crawled_urls)}")
                crawl_worker.process(url, source=source)

        # If remove_old_content is set to true:
        # remove from corpus any document previously indexed that is NOT in the crawl list
        if self.cfg.docs_crawler.get("remove_old_content", False):
            existing_docs = self.indexer._list_docs()
            docs_to_remove = [t for t in existing_docs if t['url'] and t['url'] not in self.crawled_urls]
            for doc in docs_to_remove:
                if doc['url']:
                    self.indexer.delete_doc(doc['id'])
            logging.info(f"Removing {len(docs_to_remove)} docs that are not included in the crawl but are in the corpus.")
            if self.cfg.docs_crawler.get("crawl_report", False):
                with open('/home/vectara/env/urls_removed.txt', 'w') as f:
                    for url in sorted([t['url'] for t in docs_to_remove if t['url']]):
                        f.write(url + '\n')



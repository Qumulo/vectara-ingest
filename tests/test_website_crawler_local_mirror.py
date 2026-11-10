"""website_crawler.local_mirror: pages under url_prefix are read from a local
copy of the built site and handed to index_url as HTML, keeping public URLs."""

import importlib.machinery
import os
import sys
import tempfile
import unittest
from unittest.mock import MagicMock

import requests

for mod in ["cairosvg", "whisper", "pdf2image"]:
    sys.modules.setdefault(mod, MagicMock())
_playwright_mock = MagicMock()
_playwright_mock.__spec__ = importlib.machinery.ModuleSpec("playwright", None)
sys.modules.setdefault("playwright", _playwright_mock)
sys.modules.setdefault("playwright.sync_api", MagicMock())

from crawlers.website_crawler import PageCrawlWorker, _mount_local_mirror
from core.spider import sitemap_to_urls

PREFIX = "https://docs.example.com"
PAGE = "<html><body>configuring ad</body></html>"


class TestWebsiteCrawlerLocalMirror(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "guide"))
        files = {
            "robots.txt": f"User-agent: *\n\nSitemap: {PREFIX}/sitemap.xml\n",
            "sitemap.xml": (
                '<?xml version="1.0" encoding="UTF-8"?>'
                '<urlset xmlns="http://www.sitemaps.org/schemas/sitemap/0.9">'
                f"<url><loc>{PREFIX}/guide/ad.html</loc></url>"
                f"<url><loc>{PREFIX}/guide/nfs.html</loc></url></urlset>"
            ),
            "guide/ad.html": PAGE,
        }
        for rel, body in files.items():
            with open(os.path.join(root, rel), "w") as f:
                f.write(body)
        self.cfg = {"website_crawler": {"local_mirror": {"url_prefix": PREFIX, "path": root}}}

    def tearDown(self):
        self.tmp.cleanup()

    def test_no_mirror_configured_mounts_nothing(self):
        session = MagicMock()
        self.assertIsNone(_mount_local_mirror({"website_crawler": {}}, session))
        session.mount.assert_not_called()

    def test_sitemap_discovery_reads_local_files(self):
        session = requests.Session()
        self.assertEqual(_mount_local_mirror(self.cfg, session), f"{PREFIX}/")
        self.assertEqual(
            sitemap_to_urls(PREFIX, session=session),
            [f"{PREFIX}/guide/ad.html", f"{PREFIX}/guide/nfs.html"],
        )

    def _worker(self):
        worker = PageCrawlWorker(self.cfg, num_per_second=5)
        worker.indexer = MagicMock()
        worker.indexer.session = requests.Session()
        worker.indexer.index_url.return_value = True
        worker.indexer.was_skipped.return_value = False
        worker.mirror_prefix = _mount_local_mirror(self.cfg, worker.indexer.session)
        return worker

    def test_process_passes_local_html_to_index_url(self):
        worker = self._worker()
        url = f"{PREFIX}/guide/ad.html"
        self.assertEqual(worker.process(url, source="website"), PageCrawlWorker.RESULT_INDEXED)
        args, kwargs = worker.indexer.index_url.call_args
        self.assertEqual(args[0], url)
        self.assertEqual(kwargs["html"], PAGE)
        self.assertEqual(kwargs["metadata"]["url"], url)

    def test_process_fails_when_page_missing_from_mirror(self):
        worker = self._worker()
        result = worker.process(f"{PREFIX}/guide/nfs.html", source="website")
        self.assertEqual(result, PageCrawlWorker.RESULT_FAILED)
        worker.indexer.index_url.assert_not_called()

    def test_url_outside_prefix_is_fetched_normally(self):
        worker = self._worker()
        worker.process("https://other.example.com/x.html", source="website")
        self.assertIsNone(worker.indexer.index_url.call_args.kwargs["html"])


if __name__ == "__main__":
    unittest.main()

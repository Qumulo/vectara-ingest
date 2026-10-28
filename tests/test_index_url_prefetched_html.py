"""Indexer.index_url(html=...) indexes pre-fetched HTML (e.g. from a local
mirror of a static site) without touching the network, under the same doc id
and url metadata a normal web crawl of that url would produce."""

import sys
import unittest
from unittest.mock import MagicMock

sys.modules.setdefault('cairosvg', MagicMock())

from slugify import slugify

from core.indexer import Indexer

URL = "https://docs.example.com/guide/configuring-ad.html"
HTML = f"<html><head><title>Configuring AD</title></head><body><p>{'Join the cluster to AD. ' * 40}</p></body></html>"


def _make_indexer():
    ix = Indexer.__new__(Indexer)
    ix.cfg = MagicMock()
    ix.verbose = False
    ix.parse_tables = False
    ix.remove_code = False
    ix.remove_boilerplate = False
    ix.process_locally = False
    ix.add_image_bytes = False
    ix.summarize_images = False
    ix.extract_metadata = []
    ix.detected_language = "en"
    ix.incremental = False
    ix.file_processor = MagicMock(inline_images=False)
    for net in ("url_triggers_download", "check_download_or_pdf", "fetch_page_contents"):
        setattr(ix, net, MagicMock(side_effect=AssertionError(f"{net} must not be called")))
    ix.index_segments = MagicMock(return_value=True)
    return ix


class TestIndexUrlPrefetchedHtml(unittest.TestCase):
    def test_indexes_without_network_using_url_doc_id(self):
        ix = _make_indexer()
        metadata = {"source": "website", "url": URL}

        self.assertTrue(ix.index_url(URL, metadata=metadata, html=HTML))

        kwargs = ix.index_segments.call_args.kwargs
        self.assertEqual(kwargs["doc_id"], slugify(URL))
        self.assertEqual(kwargs["doc_title"], "Configuring AD")
        self.assertIn("Join the cluster to AD.", kwargs["texts"][0])
        self.assertEqual(kwargs["doc_metadata"]["url"], URL)

    def test_sparse_html_fails_without_network(self):
        ix = _make_indexer()
        self.assertFalse(ix.index_url(URL, metadata={"url": URL}, html="<html><body>stub</body></html>"))
        ix.index_segments.assert_not_called()
        self.assertFalse(ix.was_skipped())

    def test_redirect_stub_is_skipped_not_failed(self):
        # jekyll-redirect-from stub: the target page is listed and indexed on its own.
        stub = ('<!DOCTYPE html><html><title>Redirecting&hellip;</title>'
                '<meta http-equiv="refresh" content="0; url=https://docs.example.com/new.html">'
                '<meta name="robots" content="noindex"><h1>Redirecting&hellip;</h1></html>')
        ix = _make_indexer()
        self.assertTrue(ix.index_url(URL, metadata={"url": URL}, html=stub))
        self.assertTrue(ix.was_skipped())
        ix.index_segments.assert_not_called()


if __name__ == "__main__":
    unittest.main()

"""parse_static_html builds the fetch_page_contents result from server-rendered
HTML, so it can be reused for pages read from a local mirror."""

import importlib.machinery
import sys
import unittest
from unittest.mock import MagicMock

# Heavy native deps that the import chain touches.
for _mod in ["cairosvg", "whisper", "pdf2image"]:
    sys.modules.setdefault(_mod, MagicMock())
_pw_mock = MagicMock()
_pw_mock.__spec__ = importlib.machinery.ModuleSpec("playwright", None)
sys.modules.setdefault("playwright", _pw_mock)
sys.modules.setdefault("playwright.sync_api", MagicMock())

from core.web_extractor_base import parse_static_html

BODY = "Qumulo documentation text. " * 30  # > 500 chars

PAGE = f"""<html><head><title>Configuring AD</title></head><body>
<a href="/other.html">other</a>
<p>{BODY}</p>
<img src="/images/diagram.png" alt="diagram">
<img src="/images/pixel.png" width="1" height="1">
<img src="data:image/png;base64,AAAA">
</body></html>"""


class TestParseStaticHtml(unittest.TestCase):
    def test_sparse_page_returns_none(self):
        self.assertIsNone(parse_static_html("<html><body>tiny</body></html>", "https://d.example/x.html"))

    def test_extracts_text_title_links_and_filters_images(self):
        res = parse_static_html(PAGE, "https://d.example/guide/x.html")
        self.assertEqual(res["title"], "Configuring AD")
        self.assertIn("Qumulo documentation text.", res["text"])
        self.assertEqual(res["html"], PAGE)
        self.assertEqual(res["url"], "https://d.example/guide/x.html")
        self.assertEqual(res["links"], ["/other.html"])
        self.assertEqual(res["images"], [{"src": "https://d.example/images/diagram.png", "alt": "diagram"}])
        self.assertEqual(res["tables"], [])

    def test_final_url_overrides_result_url_but_not_image_base(self):
        res = parse_static_html(PAGE, "https://d.example/guide/x.html", final_url="https://d.example/moved.html")
        self.assertEqual(res["url"], "https://d.example/moved.html")
        self.assertEqual(res["images"][0]["src"], "https://d.example/images/diagram.png")


if __name__ == "__main__":
    unittest.main()

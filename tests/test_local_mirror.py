"""LocalMirrorAdapter serves a site's public URLs from a local checkout."""

import os
import tempfile
import unittest

import requests

from core.local_mirror import LocalMirrorAdapter

PREFIX = "https://docs.example.com"


class TestLocalMirrorAdapter(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.TemporaryDirectory()
        root = self.tmp.name
        os.makedirs(os.path.join(root, "guide"))
        for rel, body in {
            "index.html": "<html>home</html>",
            "guide/index.html": "<html>guide</html>",
            "guide/a b.html": "<html>spaced</html>",
            "sitemap.xml": "<urlset/>",
        }.items():
            with open(os.path.join(root, rel), "w") as f:
                f.write(body)
        with open(os.path.join(os.path.dirname(root), "secret.txt"), "w") as f:
            f.write("outside")
        self.session = requests.Session()
        self.session.mount(PREFIX, LocalMirrorAdapter(PREFIX, root))

    def tearDown(self):
        os.remove(os.path.join(os.path.dirname(self.tmp.name), "secret.txt"))
        self.tmp.cleanup()

    def test_serves_file_with_content_type(self):
        resp = self.session.get(f"{PREFIX}/sitemap.xml")
        self.assertEqual(resp.status_code, 200)
        self.assertEqual(resp.text, "<urlset/>")
        self.assertIn("xml", resp.headers["Content-Type"])

    def test_directory_and_root_urls_serve_index_html(self):
        self.assertEqual(self.session.get(f"{PREFIX}/").text, "<html>home</html>")
        self.assertEqual(self.session.get(f"{PREFIX}/guide/").text, "<html>guide</html>")
        self.assertEqual(self.session.get(f"{PREFIX}/guide").text, "<html>guide</html>")

    def test_percent_encoding_query_and_fragment(self):
        resp = self.session.get(f"{PREFIX}/guide/a%20b.html?x=1#top")
        self.assertEqual(resp.text, "<html>spaced</html>")

    def test_missing_file_is_404(self):
        resp = self.session.get(f"{PREFIX}/nope.html")
        self.assertEqual(resp.status_code, 404)
        with self.assertRaises(requests.HTTPError):
            resp.raise_for_status()

    def test_path_traversal_is_refused(self):
        self.assertEqual(self.session.get(f"{PREFIX}/%2E%2E/secret.txt").status_code, 404)


if __name__ == "__main__":
    unittest.main()

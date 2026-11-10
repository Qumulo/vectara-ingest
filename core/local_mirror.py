import mimetypes
import os
from typing import Optional
from urllib.parse import unquote

import requests
from requests.adapters import BaseAdapter


class LocalMirrorAdapter(BaseAdapter):
    """
    requests transport adapter that serves every URL under `url_prefix` from a local
    directory holding the site's built files (e.g. a checkout of a static site's gh-pages
    branch). Mounted on a Session, it lets sitemap discovery and page fetches run without
    touching the live site, while URLs (and therefore doc ids) stay the public ones.
    """

    def __init__(self, url_prefix: str, root: str):
        super().__init__()
        self.url_prefix = url_prefix.rstrip("/") + "/"
        self.root = os.path.realpath(root)

    def local_path(self, url: str) -> Optional[str]:
        """Map a URL under the prefix to a file under root, or None if it has no such file."""
        if not url.startswith(self.url_prefix):
            return None
        rel = unquote(url[len(self.url_prefix):].split("#")[0].split("?")[0])
        path = os.path.realpath(os.path.join(self.root, rel))
        # Never serve anything outside the mirror (e.g. "../" in a crafted sitemap URL).
        if path != self.root and not path.startswith(self.root + os.sep):
            return None
        if os.path.isdir(path):
            path = os.path.join(path, "index.html")
        return path if os.path.isfile(path) else None

    def send(self, request, **kwargs):
        resp = requests.Response()
        resp.request = request
        resp.url = request.url
        path = self.local_path(request.url)
        if path is None:
            resp.status_code = 404
            resp.reason = "Not Found"
            resp._content = b""
            return resp
        with open(path, "rb") as f:
            resp._content = f.read()
        resp.status_code = 200
        resp.reason = "OK"
        content_type = mimetypes.guess_type(path)[0] or "application/octet-stream"
        if content_type.startswith("text/") or content_type.endswith("xml"):
            resp.encoding = "utf-8"
            content_type += "; charset=utf-8"
        resp.headers["Content-Type"] = content_type
        return resp

    def close(self):
        pass

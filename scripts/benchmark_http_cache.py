"""Task-local HTTP transport cache; serve only an explicitly checksummed public file."""
import argparse
import hashlib
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path
import re
import shutil
from urllib.error import HTTPError
from urllib.parse import urlsplit
from urllib.request import ProxyHandler, Request, build_opener

HOP_HEADERS = {'connection', 'proxy-connection', 'keep-alive', 'transfer-encoding',
               'te', 'trailer', 'upgrade', 'proxy-authorization', 'proxy-authenticate'}


def make_handler(url, path):
    class Handler(BaseHTTPRequestHandler):
        def log_message(self, *args):
            pass  # URLs and headers may contain credentials; never log them.

        def do_HEAD(self):
            self.handle_request(head=True)

        def do_GET(self):
            self.handle_request(head=False)

        do_POST = do_GET
        do_PUT = do_GET
        do_PATCH = do_GET
        do_DELETE = do_GET
        do_OPTIONS = do_GET

        def handle_request(self, head):
            if self.path == url and self.command in ('GET', 'HEAD'):
                size = path.stat().st_size
                start, end = 0, size - 1
                requested = self.headers.get('Range')
                if requested:
                    match = re.fullmatch(r'bytes=(\d+)-(\d*)', requested)
                    if not match:
                        self.send_error(416)
                        return
                    start = int(match[1])
                    end = min(size - 1, int(match[2]) if match[2] else size - 1)
                    if start > end:
                        self.send_error(416)
                        return
                self.send_response(206 if requested else 200)
                self.send_header('Content-Type', 'application/gzip')
                self.send_header('Content-Length', str(end - start + 1))
                self.send_header('Accept-Ranges', 'bytes')
                if requested:
                    self.send_header('Content-Range', f'bytes {start}-{end}/{size}')
                self.end_headers()
                if not head:
                    with path.open('rb') as stream:
                        stream.seek(start)
                        remaining = end - start + 1
                        while remaining:
                            chunk = stream.read(min(1024 * 1024, remaining))
                            self.wfile.write(chunk)
                            remaining -= len(chunk)
                return
            parsed = urlsplit(self.path)
            if parsed.scheme != 'http' or not parsed.hostname or parsed.username or parsed.password:
                self.send_error(400)
                return
            # No upstream proxy and no HTTPS interception. The same sandbox
            # network policy applies to this process and to task commands.
            headers = {k: v for k, v in self.headers.items() if k.lower() not in HOP_HEADERS}
            if self.headers.get('Transfer-Encoding'):
                self.send_error(411, 'A request Content-Length is required')
                return
            try:
                length = int(self.headers.get('Content-Length', '0'))
                if length < 0:
                    raise ValueError('Negative length')
            except ValueError:
                self.send_error(400)
                return
            data = self.rfile.read(length) if length else None
            request = Request(self.path, headers=headers, method=self.command, data=data)
            try:
                response = build_opener(ProxyHandler({})).open(request, timeout=60)
            except HTTPError as exc:
                response = exc
            except Exception:
                self.send_error(502)
                return
            with response:
                self.send_response(response.status)
                for key, value in response.headers.items():
                    if key.lower() not in HOP_HEADERS:
                        self.send_header(key, value)
                self.end_headers()
                if not head:
                    shutil.copyfileobj(response, self.wfile)
    return Handler


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--file', required=True, type=Path)
    parser.add_argument('--url', required=True)
    parser.add_argument('--sha256', required=True)
    parser.add_argument('--port', type=int, default=18080)
    args = parser.parse_args()
    with args.file.open('rb') as stream:
        if hashlib.file_digest(stream, 'sha256').hexdigest() != args.sha256:
            raise ValueError('Public cache checksum mismatch')
    ThreadingHTTPServer(('127.0.0.1', args.port), make_handler(args.url, args.file)).serve_forever()


if __name__ == '__main__':
    main()

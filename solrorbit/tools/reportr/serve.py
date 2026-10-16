# SPDX-License-Identifier: Apache-2.0
#
# Licensed to the Apache Software Foundation (ASF) under one or more
# contributor license agreements. See the NOTICE file distributed with
# this work for additional information regarding copyright ownership.
# The ASF licenses this file to You under the Apache License, Version 2.0
# (the "License"); you may not use this file except in compliance with
# the License. You may obtain a copy of the License at
#
#    http://www.apache.org/licenses/LICENSE-2.0
#
# Unless required by applicable law or agreed to in writing, software
# distributed under the License is distributed on an "AS IS" BASIS,
# WITHOUT WARRANTIES OR CONDITIONS OF ANY KIND, either express or implied.
# See the License for the specific language governing permissions and
# limitations under the License.
"""Serve a built site on localhost.

A convenience for local development, not a web server to deploy. The real site
is static files behind whatever file server hosts them.
"""

import contextlib
import functools
import logging
import socketserver
import threading
from http.server import SimpleHTTPRequestHandler, ThreadingHTTPServer
from pathlib import Path

logger = logging.getLogger(__name__)


class _QuietHandler(SimpleHTTPRequestHandler):
    """Logs through the logging module, and never lets the browser cache.

    SimpleHTTPRequestHandler serves Last-Modified and answers conditional
    requests, so a rebuilt app.js keeps arriving as 304 and the page you are
    looking at is the one from two builds ago. That is a trap during
    development, which is the only thing this server is for.
    """

    def log_message(self, format: str, *args) -> None:  # noqa: A002 - stdlib signature
        logger.debug("%s - %s", self.address_string(), format % args)

    def end_headers(self) -> None:
        self.send_header("Cache-Control", "no-store, must-revalidate")
        super().end_headers()

    def send_header(self, keyword: str, value: str) -> None:
        # Drop the validator the browser would otherwise turn into an If-Modified-Since.
        if keyword.lower() == "last-modified":
            return
        super().send_header(keyword, value)


def make_server(directory: Path, port: int = 8080, bind: str = "127.0.0.1") -> ThreadingHTTPServer:
    """Create a server for ``directory``. Port 0 picks a free port."""
    handler = functools.partial(_QuietHandler, directory=str(directory))
    socketserver.TCPServer.allow_reuse_address = True
    return ThreadingHTTPServer((bind, port), handler)


def serve(directory: Path, port: int = 8080, bind: str = "127.0.0.1") -> None:
    """Serve ``directory`` until interrupted."""
    server = make_server(directory, port, bind)
    host, actual = server.server_address[0], server.server_address[1]
    print(f"\nreportr is serving {directory} at http://{host}:{actual}/")
    print("Press Ctrl-C to stop.\n")
    try:
        server.serve_forever()
    except KeyboardInterrupt:
        print("\nstopped")
    finally:
        server.shutdown()
        server.server_close()


@contextlib.contextmanager
def background_server(directory: Path, port: int = 0, bind: str = "127.0.0.1"):
    """Run a server in a thread for the duration of the block. Yields the port."""
    server = make_server(directory, port, bind)
    thread = threading.Thread(target=server.serve_forever, daemon=True)
    thread.start()
    try:
        yield server.server_address[1]
    finally:
        server.shutdown()
        server.server_close()
        thread.join(timeout=5)

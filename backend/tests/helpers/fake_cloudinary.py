"""Faux Cloudinary des parcours e2e (ADR 0121) : `python -m tests.helpers.fake_cloudinary PORT`.

Répond aux trois appels de `app/core/cloudinary.py` (dépôt, suppression, liste), garde les
images en mémoire et vérifie la signature comme le vrai. Jamais sur le VPS :
`COGES_CLOUDINARY_API_BASE` n'est accepté qu'en local et en CI (config et
`check_runtime_env.py`). Les images elles-mêmes (`res.cloudinary.com`) sont servies au
navigateur par l'interception du parcours, pas ici.
"""

from __future__ import annotations

import hashlib
import io
import json
import sys
import time
from datetime import UTC, datetime
from email.parser import BytesParser
from email.policy import default as email_policy
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
from typing import Any
from urllib.parse import parse_qs, urlsplit

from PIL import Image

#: Les identifiants du parcours e2e, posés aussi par `deploy/scripts/e2e.sh`.
CLOUD = "coges-e2e"
API_KEY = "100000000000001"
SECRET = "faux-secret-cloudinary-e2e-0000"

IMAGES: dict[str, dict[str, Any]] = {}


def _check(params: dict[str, str]) -> bool:
    signed = {
        key: value
        for key, value in params.items()
        if key not in {"api_key", "signature", "signature_algorithm", "file"} and value != ""
    }
    payload = "&".join(f"{key}={signed[key]}" for key in sorted(signed))
    expected = hashlib.sha256((payload + SECRET).encode()).hexdigest()
    return params.get("api_key") == API_KEY and params.get("signature") == expected


class Handler(BaseHTTPRequestHandler):
    def log_message(self, *_: Any) -> None:  # le parcours n'a pas besoin de ce bruit
        return

    def _send(self, status: int, body: dict[str, Any]) -> None:
        data = json.dumps(body).encode()
        self.send_response(status)
        self.send_header("Content-Type", "application/json")
        self.send_header("Content-Length", str(len(data)))
        self.end_headers()
        self.wfile.write(data)

    def do_POST(self) -> None:
        length = int(self.headers.get("Content-Length", "0"))
        body = self.rfile.read(length)
        path = urlsplit(self.path).path
        if path == f"/v1_1/{CLOUD}/image/upload":
            message = BytesParser(policy=email_policy).parsebytes(
                b"Content-Type: " + self.headers["Content-Type"].encode() + b"\r\n\r\n" + body
            )
            params: dict[str, str] = {}
            content = b""
            for part in message.iter_parts():
                name = part.get_param("name", header="content-disposition")
                if name == "file":
                    content = part.get_payload(decode=True)
                else:
                    params[str(name)] = part.get_content().strip()
            if not _check(params):
                self._send(401, {"error": {"message": "Invalid Signature"}})
                return
            image = Image.open(io.BytesIO(content))
            public_id = params["public_id"]
            IMAGES[public_id] = {"created_at": datetime.now(UTC).isoformat()}
            self._send(
                200,
                {
                    "public_id": public_id,
                    "version": int(time.time()),
                    "width": image.width,
                    "height": image.height,
                },
            )
            return
        if path == f"/v1_1/{CLOUD}/image/destroy":
            params = {key: values[0] for key, values in parse_qs(body.decode()).items()}
            if not _check(params):
                self._send(401, {"error": {"message": "Invalid Signature"}})
                return
            found = IMAGES.pop(params["public_id"], None)
            self._send(200, {"result": "ok" if found else "not found"})
            return
        self._send(404, {"error": {"message": "inconnu"}})

    def do_GET(self) -> None:
        parts = urlsplit(self.path)
        if parts.path == f"/v1_1/{CLOUD}/resources/image/upload":
            prefix = parse_qs(parts.query).get("prefix", [""])[0]
            self._send(
                200,
                {
                    "resources": [
                        {"public_id": key, "created_at": value["created_at"]}
                        for key, value in IMAGES.items()
                        if key.startswith(prefix)
                    ]
                },
            )
            return
        self._send(404, {"error": {"message": "inconnu"}})


def main(argv: list[str]) -> int:
    port = int(argv[0]) if argv else 8199
    ThreadingHTTPServer(("127.0.0.1", port), Handler).serve_forever()
    return 0


if __name__ == "__main__":
    raise SystemExit(main(sys.argv[1:]))

#!/usr/bin/env python3
"""One-time Google OAuth for the local Google Calendar MCP server.

Reads your own OAuth client from ~/.codex/gcp_oauth_client.json
(create it in https://console.cloud.google.com/apis/credentials as a
"Desktop app" client and enable the Calendar API), opens the consent page
in your browser, then stores tokens in $CODEX_HOME/gcal_token.json.
"""
import base64
import hashlib
import json
import os
import secrets
import threading
import time
import urllib.parse
import urllib.request
from http.server import BaseHTTPRequestHandler, HTTPServer

CODEX_HOME = os.environ.get("CODEX_HOME") or os.path.expanduser("~/.codex")
CLIENT_PATH = os.path.expanduser("~/.codex/gcp_oauth_client.json")
TOKEN_PATH = os.path.join(CODEX_HOME, "gcal_token.json")
PORT = 8765
SCOPES = [
    "https://www.googleapis.com/auth/calendar",
    "https://www.googleapis.com/auth/calendar.acls",
    "https://www.googleapis.com/auth/calendar.calendarlist",
    "https://www.googleapis.com/auth/calendar.calendarlist.readonly",
    "https://www.googleapis.com/auth/calendar.calendars",
    "https://www.googleapis.com/auth/calendar.calendars.readonly",
    "https://www.googleapis.com/auth/calendar.events",
    "https://www.googleapis.com/auth/calendar.events.freebusy",
    "https://www.googleapis.com/auth/calendar.events.readonly",
    "https://www.googleapis.com/auth/calendar.freebusy",
    "https://www.googleapis.com/auth/calendar.readonly",
    "https://www.googleapis.com/auth/calendar.settings.readonly",
]


def main():
    client = json.load(open(CLIENT_PATH))
    cid, csec = client["client_id"].strip(), client["client_secret"].strip()
    verifier = base64.urlsafe_b64encode(secrets.token_bytes(32)).rstrip(b"=").decode()
    challenge = base64.urlsafe_b64encode(hashlib.sha256(verifier.encode()).digest()).rstrip(b"=").decode()
    state = secrets.token_urlsafe(12)
    result = {}

    class Handler(BaseHTTPRequestHandler):
        def do_GET(self):
            query = urllib.parse.parse_qs(urllib.parse.urlparse(self.path).query)
            self.send_response(200)
            self.send_header("Content-Type", "text/html; charset=utf-8")
            self.end_headers()
            if "code" in query and query.get("state", [None])[0] == state:
                self.wfile.write("<h3>Listo. Ya puedes cerrar esta pestana.</h3>".encode())
                result["code"] = query["code"][0]
            else:
                self.wfile.write("<h3>Cancelado.</h3>".encode())
                result["error"] = str(query)

        def log_message(self, *args):
            pass

    server = HTTPServer(("127.0.0.1", PORT), Handler)
    threading.Thread(target=server.handle_request, daemon=True).start()

    url = "https://accounts.google.com/o/oauth2/v2/auth?" + urllib.parse.urlencode(
        {
            "response_type": "code",
            "client_id": cid,
            "redirect_uri": "http://127.0.0.1:%d/callback" % PORT,
            "scope": " ".join(SCOPES),
            "state": state,
            "code_challenge": challenge,
            "code_challenge_method": "S256",
            "access_type": "offline",
            "prompt": "consent",
        }
    )
    import subprocess

    subprocess.run(["open", url])
    print("Browser abierto — acepta los permisos de Google.")
    for _ in range(300):
        if "code" in result or "error" in result:
            break
        time.sleep(1)
    server.server_close()
    if "code" not in result:
        raise SystemExit("No llegó el código OAuth (timeout o cancelado).")

    token = json.loads(
        urllib.request.urlopen(
            urllib.request.Request(
                "https://oauth2.googleapis.com/token",
                data=urllib.parse.urlencode(
                    {
                        "grant_type": "authorization_code",
                        "code": result["code"],
                        "client_id": cid,
                        "client_secret": csec,
                        "redirect_uri": "http://127.0.0.1:%d/callback" % PORT,
                        "code_verifier": verifier,
                    }
                ).encode(),
            ),
            timeout=30,
        ).read()
    )
    token["client_id"] = cid
    token["client_secret"] = csec
    token["expires_at"] = int(time.time()) + int(token.get("expires_in", 3600))
    with open(TOKEN_PATH, "w") as fh:
        json.dump(token, fh, indent=1)
    os.chmod(TOKEN_PATH, 0o600)
    print("Token guardado en %s — el MCP de Calendar ya puede usarse." % TOKEN_PATH)


if __name__ == "__main__":
    main()

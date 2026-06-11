"""Self-contained OAuth client for the Higgsfield MCP server.

Implements RFC 8414 discovery, RFC 7591 dynamic client registration, the
authorization-code + PKCE (S256) flow, and refresh-token renewal — all
stdlib, so running the app doesn't require Claude Code. Live-verified
against mcp.higgsfield.ai: registration returns 201 and accepts
http://localhost:8787/oauth/callback redirects.
"""
import base64
import hashlib
import json
import os
import threading
import time
import urllib.error
import urllib.parse
import urllib.request

from app.pipeline import ROOT, PipelineError

AUTH_BASE = "https://mcp.higgsfield.ai"
DISCOVERY_URL = AUTH_BASE + "/.well-known/oauth-authorization-server"
RESOURCE = AUTH_BASE          # RFC 8707 resource indicator for this MCP server
SCOPE = "openid email offline_access"
CRED_PATH = os.path.join(ROOT, ".higgsfield-credentials.json")
USER_AGENT = "reel-swap-me-in/1.0"

_pending = {}                 # state -> PKCE verifier (single-process server)
_lock = threading.Lock()
_discovery_cache = None


# ---------------------------------------------------------------- pure helpers

def _b64url(data):
    return base64.urlsafe_b64encode(data).rstrip(b"=").decode()


def make_pkce():
    """Returns (verifier, S256 challenge)."""
    verifier = _b64url(os.urandom(32))
    challenge = _b64url(hashlib.sha256(verifier.encode()).digest())
    return verifier, challenge


def token_state(creds, now=None):
    """'valid' | 'refreshable' | 'absent' for a credential dict."""
    now = time.time() if now is None else now
    if not creds.get("access_token"):
        return "absent"
    if creds.get("expires_at", 0) > now + 60:
        return "valid"
    return "refreshable" if creds.get("refresh_token") else "absent"


def load_credentials(path=CRED_PATH):
    try:
        with open(path) as fh:
            return json.load(fh)
    except (OSError, ValueError):
        return {}


def save_credentials(creds, path=CRED_PATH):
    fd = os.open(path, os.O_WRONLY | os.O_CREAT | os.O_TRUNC, 0o600)
    with os.fdopen(fd, "w") as fh:
        json.dump(creds, fh)


# -------------------------------------------------------------------- network

def _http(url, body=None, form=False):
    headers = {"User-Agent": USER_AGENT, "Accept": "application/json"}
    data = None
    if body is not None:
        if form:
            data = urllib.parse.urlencode(body).encode()
            headers["Content-Type"] = "application/x-www-form-urlencoded"
        else:
            data = json.dumps(body).encode()
            headers["Content-Type"] = "application/json"
    req = urllib.request.Request(url, data=data, headers=headers)
    try:
        return json.loads(urllib.request.urlopen(req, timeout=30).read().decode())
    except urllib.error.HTTPError as exc:
        raise PipelineError("Higgsfield auth error (HTTP %d): %s"
                            % (exc.code, exc.read().decode()[:200]))
    except OSError as exc:
        raise PipelineError("Couldn't reach Higgsfield auth: %s" % exc)


def _endpoints():
    global _discovery_cache
    if _discovery_cache is None:
        meta = _http(DISCOVERY_URL)
        _discovery_cache = {
            "authorize": meta["authorization_endpoint"],
            "token": meta["token_endpoint"],
            "register": meta.get("registration_endpoint"),
        }
    return _discovery_cache


def _redirect_uri(port):
    return "http://localhost:%d/oauth/callback" % port


def ensure_client(port):
    """Reuse the registered client or dynamically register a new one."""
    creds = load_credentials()
    if creds.get("client_id") and creds.get("redirect_uri") == _redirect_uri(port):
        return creds["client_id"]
    registration = _http(_endpoints()["register"], body={
        "client_name": "Reel Swap Me In (local)",
        "redirect_uris": [_redirect_uri(port),
                          "http://127.0.0.1:%d/oauth/callback" % port],
        "grant_types": ["authorization_code", "refresh_token"],
        "response_types": ["code"],
        "token_endpoint_auth_method": "none",
        "scope": SCOPE,
    })
    creds.update(client_id=registration["client_id"],
                 redirect_uri=_redirect_uri(port))
    save_credentials(creds)
    return creds["client_id"]


def begin_login(port):
    """Start the browser flow; returns the URL to open."""
    client_id = ensure_client(port)
    verifier, challenge = make_pkce()
    state = _b64url(os.urandom(16))
    with _lock:
        _pending[state] = verifier
    return _endpoints()["authorize"] + "?" + urllib.parse.urlencode({
        "response_type": "code",
        "client_id": client_id,
        "redirect_uri": _redirect_uri(port),
        "scope": SCOPE,
        "state": state,
        "code_challenge": challenge,
        "code_challenge_method": "S256",
        "resource": RESOURCE,
    })


def handle_callback(code, state, port):
    """Exchange the authorization code; persists tokens."""
    with _lock:
        verifier = _pending.pop(state, None)
    if not verifier:
        raise PipelineError("Login session expired or mismatched — click "
                            "Connect Higgsfield and try again.")
    creds = load_credentials()
    tokens = _http(_endpoints()["token"], form=True, body={
        "grant_type": "authorization_code",
        "code": code,
        "redirect_uri": _redirect_uri(port),
        "client_id": creds.get("client_id"),
        "code_verifier": verifier,
        "resource": RESOURCE,
    })
    _store_tokens(creds, tokens)


def _store_tokens(creds, tokens):
    creds["access_token"] = tokens["access_token"]
    if tokens.get("refresh_token"):
        creds["refresh_token"] = tokens["refresh_token"]
    creds["expires_at"] = time.time() + float(tokens.get("expires_in") or 3600)
    save_credentials(creds)


def get_app_token():
    """Valid access token from the app-owned store (refreshing if needed),
    or None when the user never connected through the app."""
    creds = load_credentials()
    state = token_state(creds)
    if state == "valid":
        return creds["access_token"]
    if state == "refreshable":
        try:
            tokens = _http(_endpoints()["token"], form=True, body={
                "grant_type": "refresh_token",
                "refresh_token": creds["refresh_token"],
                "client_id": creds.get("client_id"),
                "resource": RESOURCE,
            })
        except PipelineError:
            return None  # let callers fall through to other auth sources
        _store_tokens(creds, tokens)
        return creds["access_token"]
    return None


def connected():
    return token_state(load_credentials()) != "absent"

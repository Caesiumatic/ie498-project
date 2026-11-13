"""User-authorized ChatGPT plan OAuth; never reads Codex/browser credentials.

Protocol: https://developers.openai.com/siwc/token-sharing-open-source/sign-in
One protected record represents one user/workspace registration. Use a different
record path to add an account instead of overwriting another registration.
"""
from __future__ import annotations

import asyncio
import base64
import concurrent.futures
from contextlib import contextmanager
from datetime import datetime, timezone
import fcntl
import hashlib
from html import escape
from http.server import BaseHTTPRequestHandler, ThreadingHTTPServer
import json
import math
import os
from pathlib import Path
import re
import secrets
import stat
import tempfile
import threading
import time
from typing import Any
from urllib.parse import parse_qs, urlencode, urlsplit
import uuid

import httpx
import jwt


ISSUER = "https://auth.openai.com"
AUTHORIZE_URL = ISSUER + "/api/accounts/authorize"
TOKEN_URL = ISSUER + "/api/accounts/oauth/token"
DISCOVERY_URL = ISSUER + "/.well-known/openid-configuration"
JWKS_URL = ISSUER + "/.well-known/jwks.json"
RESOURCE = "https://api.openai.com/v1"
DIRECT_SCOPE = "chatgpt.tokens.use.direct"
SCOPES = "openid profile email offline_access resource.invoke " + DIRECT_SCOPE
DEFAULT_AUTH_PATH = Path(__file__).resolve().parents[2] / "data/auth/chatgpt-plan.json"
TERMINAL_REFRESH_ERRORS = {
    "invalid_grant", "invalid_refresh_token", "token_expired",
    "refresh_token_expired", "refresh_token_invalidated", "refresh_token_reused",
}


class SubscriptionAuthError(RuntimeError):
    """A redacted authentication error safe to show in a terminal or run log."""


def _read_private(path: Path, *, optional: bool = False) -> dict[str, Any] | None:
    try:
        fd = os.open(path, os.O_RDONLY | os.O_NOFOLLOW)
    except FileNotFoundError:
        if optional:
            return None
        raise SubscriptionAuthError("ChatGPT plan sign-in is required.") from None
    except OSError:
        raise SubscriptionAuthError("Cannot open the protected OAuth record.") from None
    with os.fdopen(fd, "r") as stream:
        info = os.fstat(stream.fileno())
        if not stat.S_ISREG(info.st_mode) or info.st_uid != os.getuid() or info.st_mode & 0o077:
            raise SubscriptionAuthError("OAuth records must be owner-only regular files (0600).")
        try:
            value = json.load(stream)
        except (ValueError, UnicodeError):
            raise SubscriptionAuthError("The protected OAuth record is invalid.") from None
    if not isinstance(value, dict):
        raise SubscriptionAuthError("The protected OAuth record is invalid.")
    return value


def _write_private(path: Path, value: dict[str, Any]) -> None:
    if path.is_symlink():
        raise SubscriptionAuthError("OAuth records cannot be symbolic links.")
    fd, temporary = tempfile.mkstemp(prefix=".oauth-", dir=path.parent)
    try:
        with os.fdopen(fd, "w") as stream:
            os.fchmod(stream.fileno(), 0o600)
            json.dump(value, stream, sort_keys=True)
            stream.write("\n")
            stream.flush()
            os.fsync(stream.fileno())
        os.replace(temporary, path)
        directory = os.open(path.parent, os.O_RDONLY | os.O_DIRECTORY)
        try:
            os.fsync(directory)
        finally:
            os.close(directory)
    finally:
        if os.path.exists(temporary):
            os.unlink(temporary)


def _safe_error_code(value: Any) -> str:
    if isinstance(value, dict):
        value = value.get("code", value.get("type"))
    return value if isinstance(value, str) and re.fullmatch(r"[a-z_]{1,80}", value) else "oauth_error"


class SubscriptionAuth:
    def __init__(self, path: str | Path = DEFAULT_AUTH_PATH, *,
                 transport: httpx.BaseTransport | None = None):
        self.path = Path(path).absolute()
        self.registration_path = self.path.with_suffix(".registration.json")
        self.lock_path = self.path.with_suffix(".lock")
        self.transport = transport

    @contextmanager
    def _locked(self):
        self.path.parent.mkdir(parents=True, exist_ok=True, mode=0o700)
        if self.path.parent.is_symlink():
            raise SubscriptionAuthError("The OAuth storage directory cannot be a symbolic link.")
        fd = os.open(self.lock_path, os.O_CREAT | os.O_RDWR | os.O_NOFOLLOW, 0o600)
        try:
            os.fchmod(fd, 0o600)
            fcntl.flock(fd, fcntl.LOCK_EX)
            yield
        finally:
            fcntl.flock(fd, fcntl.LOCK_UN)
            os.close(fd)

    def _client(self) -> httpx.Client:
        return httpx.Client(timeout=30, follow_redirects=False, transport=self.transport)

    def _get_json(self, client: httpx.Client, url: str) -> dict[str, Any]:
        try:
            response = client.get(url)
            if response.status_code != 200:
                raise SubscriptionAuthError("OpenAI identity metadata is temporarily unavailable.")
            value = response.json()
        except (httpx.HTTPError, ValueError):
            raise SubscriptionAuthError("OpenAI identity metadata could not be retrieved.") from None
        if not isinstance(value, dict):
            raise SubscriptionAuthError("Invalid OpenAI identity metadata.")
        return value

    def _discovery(self, client: httpx.Client) -> dict[str, Any]:
        metadata = self._get_json(client, DISCOVERY_URL)
        expected = {"issuer": ISSUER, "authorization_endpoint": AUTHORIZE_URL,
                    "token_endpoint": TOKEN_URL, "jwks_uri": JWKS_URL}
        if any(metadata.get(key) != value for key, value in expected.items()):
            raise SubscriptionAuthError("OpenAI identity endpoints differ from the supported configuration.")
        return metadata

    def _identity(self, client: httpx.Client, token: str, client_id: str,
                  nonce: str | None = None) -> dict[str, Any]:
        self._discovery(client)
        try:
            header = jwt.get_unverified_header(token)
            # Never accept symmetric algorithms or a token-provided key URL.
            algorithm = header.get("alg")
            if algorithm not in {"RS256", "ES256", "EdDSA"}:
                raise ValueError("Unsupported signing algorithm")
            keys = self._get_json(client, JWKS_URL).get("keys", [])
            candidates = [key for key in keys if key.get("kid") == header.get("kid")
                          and key.get("use", "sig") == "sig"
                          and key.get("alg", algorithm) == algorithm]
            if not header.get("kid") or len(candidates) != 1:
                raise ValueError("Unknown signing key")
            key = jwt.PyJWK.from_dict(candidates[0], algorithm=algorithm).key
            identity = jwt.decode(token, key, algorithms=[algorithm], audience=client_id,
                                  issuer=ISSUER, leeway=5,
                                  options={"require": ["iss", "sub", "aud", "exp", "iat"]})
            if not isinstance(identity.get("sub"), str) or not identity["sub"]:
                raise ValueError("Missing subject")
            if nonce is not None and not secrets.compare_digest(str(identity.get("nonce", "")), nonce):
                raise ValueError("Nonce mismatch")
        except (jwt.PyJWTError, ValueError, TypeError, AttributeError):
            raise SubscriptionAuthError("OpenAI ID-token validation failed.") from None
        return identity

    def _token(self, client: httpx.Client, form: dict[str, str]) -> dict[str, Any]:
        try:
            response = client.post(TOKEN_URL, data=form)
        except httpx.HTTPError:
            raise SubscriptionAuthError("OAuth token exchange was interrupted; credentials were preserved.") from None
        try:
            value = response.json()
        except ValueError:
            value = {}
        if response.status_code != 200:
            code = _safe_error_code(value.get("error") if isinstance(value, dict) else None)
            error = SubscriptionAuthError(f"OAuth token exchange failed (HTTP {response.status_code}, {code}).")
            error.code = code
            raise error
        if not isinstance(value, dict):
            raise SubscriptionAuthError("The OAuth token response was invalid.")
        return value

    def _record(self, token: dict[str, Any], previous: dict[str, Any]) -> dict[str, Any]:
        if not isinstance(token.get("token_type"), str) or token["token_type"].lower() != "bearer":
            raise SubscriptionAuthError("The OAuth token response did not contain a bearer token.")
        for name in ("access_token", "refresh_token"):
            if not isinstance(token.get(name), str) or not token[name]:
                raise SubscriptionAuthError("The OAuth token response was missing renewable credentials.")
        scope = token.get("scope")
        scopes = scope.split() if isinstance(scope, str) else previous.get("scopes", [])
        if DIRECT_SCOPE not in scopes:
            raise SubscriptionAuthError("ChatGPT plan permission was not granted; enable it during sign-in.")
        try:
            expires_in = float(token["expires_in"])
        except (KeyError, TypeError, ValueError):
            raise SubscriptionAuthError("The OAuth token response was missing an expiry.") from None
        if not math.isfinite(expires_in) or expires_in <= 0:
            raise SubscriptionAuthError("The OAuth token expiry was invalid.")
        now = time.time()
        result = {**previous, "access_token": token["access_token"],
                  "refresh_token": token["refresh_token"], "token_type": "Bearer",
                  "expires_in": expires_in, "expires_at": now + expires_in,
                  "saved_at": datetime.fromtimestamp(now, timezone.utc).isoformat(),
                  "scopes": scopes}
        if token.get("id_token"):
            result["id_token"] = token["id_token"]
        if "earliest_refresh_at" in token:
            result["earliest_refresh_at"] = token["earliest_refresh_at"]
        else:
            result.pop("earliest_refresh_at", None)
        return result

    async def access_token(self) -> str:
        """Return this app's token, refreshing under a cross-process lock if needed."""
        return await asyncio.to_thread(self._access_token)

    def _access_token(self) -> str:
        with self._locked():
            record = _read_private(self.path)
            if DIRECT_SCOPE not in record.get("scopes", []):
                raise SubscriptionAuthError("ChatGPT plan permission is missing; sign in again.")
            now = time.time()
            try:
                expiry = float(record.get("expires_at", 0))
            except (TypeError, ValueError):
                raise SubscriptionAuthError("The OAuth expiry record is invalid.") from None
            if not math.isfinite(expiry):
                raise SubscriptionAuthError("The OAuth expiry record is invalid.")
            earliest = record.get("earliest_refresh_at", 0)
            try:
                earliest = float(earliest)
            except (TypeError, ValueError):
                try:
                    earliest = datetime.fromisoformat(earliest.replace("Z", "+00:00")).timestamp()
                except (AttributeError, ValueError):
                    raise SubscriptionAuthError("The OAuth refresh time is invalid.") from None
            if not math.isfinite(earliest):
                raise SubscriptionAuthError("The OAuth refresh time is invalid.")
            if expiry > now + 60 or (expiry > now and earliest > now):
                if not isinstance(record.get("access_token"), str) or not record["access_token"]:
                    raise SubscriptionAuthError("ChatGPT plan sign-in is required.")
                return record["access_token"]
            if earliest > now:
                raise SubscriptionAuthError("The OAuth token expired before refresh was allowed; retry later.")
            if not record.get("refresh_token") or not record.get("client_id"):
                raise SubscriptionAuthError("ChatGPT plan sign-in is required.")
            with self._client() as client:
                try:
                    token = self._token(client, {"grant_type": "refresh_token",
                        "client_id": record["client_id"], "refresh_token": record["refresh_token"],
                        "resource": RESOURCE})
                except SubscriptionAuthError as error:
                    if getattr(error, "code", None) in TERMINAL_REFRESH_ERRORS:
                        _write_private(self.registration_path, {key: record[key] for key in
                            ("client_id", "ext_agent_host_id", "subject", "issuer") if key in record})
                        self.path.unlink()
                        raise SubscriptionAuthError("OAuth session expired or was revoked; sign in again.") from None
                    raise
                if token.get("id_token"):
                    identity = self._identity(client, token["id_token"], record["client_id"])
                    if identity["sub"] != record.get("subject"):
                        raise SubscriptionAuthError("Refreshed credentials belong to a different account.")
                refreshed = self._record(token, record)
                _write_private(self.path, refreshed)
                return refreshed["access_token"]

    def begin_login(self, *, port: int = 1455, app_name: str = "IE498 Memory Pricing") -> "LoginSession":
        """Start a loopback listener; caller may print authorization_url then wait()."""
        with self._locked():
            record = _read_private(self.path, optional=True)
            registration = _read_private(self.registration_path, optional=True) or {}
            if record:
                registration = {key: record[key] for key in
                    ("client_id", "ext_agent_host_id", "subject", "issuer") if key in record}
            registration.setdefault("ext_agent_host_id", "urn:uuid:" + str(uuid.uuid4()))
            _write_private(self.registration_path, registration)
        return LoginSession(self, registration, port, app_name)

    def _complete_login(self, session: "LoginSession", values: dict[str, list[str]]) -> dict[str, str]:
        # Callback validation happens before any exchange or credential mutation.
        if any(len(values.get(key, [])) != 1 for key in ("state",)):
            raise SubscriptionAuthError("Invalid OAuth callback.")
        if not secrets.compare_digest(values["state"][0], session.state):
            raise SubscriptionAuthError("OAuth callback state did not match.")
        if "error" in values:
            raise SubscriptionAuthError("ChatGPT sign-in was declined or failed.")
        if len(values.get("code", [])) != 1 or not values["code"][0]:
            raise SubscriptionAuthError("OAuth callback did not contain an authorization code.")
        supplied = values.get("client_id", [])
        if len(supplied) > 1:
            raise SubscriptionAuthError("Invalid OAuth client registration.")
        saved_id = session.registration.get("client_id")
        issued_id = supplied[0] if supplied else saved_id
        if not issued_id or issued_id == "dynamic_agent_client" or (saved_id and saved_id != issued_id):
            raise SubscriptionAuthError("OAuth client registration was missing or changed.")
        with self._locked():
            current = _read_private(self.path, optional=True)
            if current and current.get("client_id") != issued_id:
                raise SubscriptionAuthError("Another account already occupies this OAuth record.")
            registration = {**session.registration, "client_id": issued_id}
            # Retain the issued registration even if its one-time code expires.
            _write_private(self.registration_path, registration)
            with self._client() as client:
                self._discovery(client)
                token = self._token(client, {"grant_type": "authorization_code", "client_id": issued_id,
                    "code": values["code"][0], "code_verifier": session.verifier,
                    "redirect_uri": session.redirect_uri, "resource": RESOURCE})
                if not isinstance(token.get("id_token"), str):
                    raise SubscriptionAuthError("The OAuth response did not contain an ID token.")
                identity = self._identity(client, token["id_token"], issued_id, session.nonce)
            expected = session.registration.get("subject")
            if expected and identity["sub"] != expected:
                raise SubscriptionAuthError("Sign-in returned a different account; existing credentials were preserved.")
            result = self._record(token, {**registration, "issuer": ISSUER, "subject": identity["sub"],
                                         "email": identity.get("email", "")})
            _write_private(self.path, result)
            _write_private(self.registration_path, {key: result[key] for key in
                ("client_id", "ext_agent_host_id", "subject", "issuer")})
            return {"client_id": issued_id, "email": result["email"], "status": "signed_in"}


class LoginSession:
    """One pending OAuth attempt. Neither repr nor HTTP logs reveal its secrets."""
    def __init__(self, auth: SubscriptionAuth, registration: dict[str, Any], port: int, app_name: str):
        self.auth = auth
        self.registration = registration
        self.state = secrets.token_urlsafe(32)
        self.nonce = secrets.token_urlsafe(32)
        self.verifier = secrets.token_urlsafe(48)
        self.result: concurrent.futures.Future = concurrent.futures.Future()
        self._processing = threading.Lock()
        session = self

        class CallbackHandler(BaseHTTPRequestHandler):
            def log_message(self, *_args):
                pass  # Default access logging would expose the one-time code.

            def do_GET(self):
                parsed = urlsplit(self.path)
                if parsed.path == "/":
                    page = ("<!doctype html><html lang=\"en\"><meta charset=\"utf-8\">"
                        "<meta name=\"referrer\" content=\"no-referrer\">"
                        "<title>IE498 ChatGPT sign-in</title><body>"
                        "<h1>IE498 ChatGPT sign-in</h1>"
                        "<p>Continue in this browser on the machine running the login helper. "
                        "OpenAI will return to this machine's local callback.</p>"
                        "<p><a data-oai-siwc-button href=\"" + escape(session.authorization_url, quote=True) +
                        "\">Continue with ChatGPT</a></p></body></html>").encode()
                    self.send_response(200)
                    self.send_header("Content-Type", "text/html; charset=utf-8")
                    self.send_header("Content-Length", str(len(page)))
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.end_headers()
                    self.wfile.write(page)
                    return
                if parsed.path != "/auth/callback":
                    self.send_error(404)
                    return
                if not session._processing.acquire(blocking=False):
                    self.send_error(409)
                    return
                try:
                    if session.result.done():
                        self.send_error(409)
                        return
                    values = parse_qs(parsed.query, keep_blank_values=True, max_num_fields=16)
                    # Ignore unsolicited/mismatched requests without consuming the attempt.
                    if values.get("state") != [session.state]:
                        self.send_error(400, "Invalid callback state")
                        return
                    try:
                        result = auth._complete_login(session, values)
                    except SubscriptionAuthError as error:
                        session.result.set_exception(error)
                        message = "Sign-in did not complete. Check the local terminal."
                        status = 400
                    else:
                        session.result.set_result(result)
                        message = "Sign-in completed. You may close this tab."
                        status = 200
                    self.send_response(status)
                    self.send_header("Content-Type", "text/plain; charset=utf-8")
                    self.send_header("Cache-Control", "no-store")
                    self.send_header("Referrer-Policy", "no-referrer")
                    self.end_headers()
                    self.wfile.write(message.encode())
                except (ValueError, OSError):
                    if not session.result.done():
                        session.result.set_exception(SubscriptionAuthError("The OAuth callback could not be processed."))
                finally:
                    session._processing.release()

        self.server = ThreadingHTTPServer(("127.0.0.1", port), CallbackHandler)
        self.server.daemon_threads = True
        self.landing_url = f"http://127.0.0.1:{self.server.server_port}/"
        self.redirect_uri = f"http://127.0.0.1:{self.server.server_port}/auth/callback"
        parameters = {"client_id": registration.get("client_id", "dynamic_agent_client"),
            "ext_agent_host_id": registration["ext_agent_host_id"], "response_type": "code",
            "redirect_uri": self.redirect_uri, "scope": SCOPES, "resource": RESOURCE,
            "state": self.state, "nonce": self.nonce, "code_challenge_method": "S256",
            "code_challenge": base64.urlsafe_b64encode(hashlib.sha256(self.verifier.encode()).digest()).decode().rstrip("=")}
        if not registration.get("client_id"):
            parameters["agent_name_hint"] = app_name
        # Omit optional ID-token/email hints so this URL can safely be displayed.
        self.authorization_url = AUTHORIZE_URL + "?" + urlencode(parameters)
        self.thread = threading.Thread(target=self.server.serve_forever, daemon=True)
        self.thread.start()

    def wait(self, timeout: float = 900) -> dict[str, str]:
        try:
            return self.result.result(timeout=timeout)
        except concurrent.futures.TimeoutError:
            raise SubscriptionAuthError("Sign-in timed out; start a fresh authorization attempt.") from None
        finally:
            self.close()

    def close(self):
        self.server.shutdown()
        self.server.server_close()
        self.thread.join(timeout=2)

import asyncio
import hashlib
import base64
from html import unescape
import json
import os
import time
from urllib.parse import parse_qs, urlsplit

from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
import pytest

from ie498.subscription_auth import (
    AUTHORIZE_URL, DIRECT_SCOPE, DISCOVERY_URL, ISSUER, JWKS_URL, RESOURCE,
    TOKEN_URL, SubscriptionAuth, SubscriptionAuthError, _write_private,
)


@pytest.fixture
def identity_provider():
    key = rsa.generate_private_key(public_exponent=65537, key_size=2048)
    jwk = json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test-key", use="sig", alg="RS256")
    state = {"posts": [], "nonce": "", "subject": "test-subject", "scope": DIRECT_SCOPE}

    def signed(**changes):
        claims = {"iss": ISSUER, "sub": state["subject"], "aud": "oaiapp_test",
                  "iat": int(time.time()), "exp": int(time.time()) + 600,
                  "nonce": state["nonce"]}
        claims.update(changes)
        return jwt.encode(claims, key, algorithm="RS256", headers={"kid": "test-key"})

    def handle(request):
        if str(request.url) == DISCOVERY_URL:
            return httpx.Response(200, json={"issuer": ISSUER, "authorization_endpoint": AUTHORIZE_URL,
                "token_endpoint": TOKEN_URL, "jwks_uri": JWKS_URL})
        if str(request.url) == JWKS_URL:
            return httpx.Response(200, json={"keys": [jwk]})
        assert str(request.url) == TOKEN_URL
        form = parse_qs(request.content.decode())
        state["posts"].append(form)
        if state.get("error"):
            return httpx.Response(state.get("status", 400), json={"error": state["error"],
                "error_description": "do-not-log-secret"})
        if form["grant_type"] == ["refresh_token"]:
            # Brief contention makes the cross-instance refresh test meaningful.
            time.sleep(0.02)
            return httpx.Response(200, json={"access_token": "refreshed-access", "refresh_token": "rotated-refresh",
                "token_type": "Bearer", "scope": state["scope"], "expires_in": 3600})
        return httpx.Response(200, json={"access_token": "test-access", "refresh_token": "test-refresh",
            "id_token": signed(**state.get("claims", {})), "token_type": "Bearer",
            "scope": state["scope"], "expires_in": 3600})

    state["transport"] = httpx.MockTransport(handle)
    state["signed"] = signed
    return state


def complete(auth, session):
    return auth._complete_login(session, {"state": [session.state], "code": ["one-time-code"],
                                         "client_id": ["oaiapp_test"]})


def saved_record(path, **changes):
    path.parent.mkdir(parents=True, exist_ok=True)
    record = {"access_token": "old-access", "refresh_token": "old-refresh", "client_id": "oaiapp_test",
        "subject": "test-subject", "issuer": ISSUER, "ext_agent_host_id": "urn:uuid:test",
        "scopes": [DIRECT_SCOPE], "expires_at": time.time() - 1}
    record.update(changes)
    _write_private(path, record)


def test_pkce_login_validates_identity_and_writes_private_record(tmp_path, identity_provider):
    auth = SubscriptionAuth(tmp_path / "auth.json", transport=identity_provider["transport"])
    session = auth.begin_login(port=0)
    try:
        params = parse_qs(urlsplit(session.authorization_url).query)
        identity_provider["nonce"] = session.nonce
        assert params["client_id"] == ["dynamic_agent_client"]
        assert params["resource"] == [RESOURCE]
        assert params["code_challenge"] == [base64.urlsafe_b64encode(
            hashlib.sha256(session.verifier.encode()).digest()).decode().rstrip("=")]
        assert session.verifier not in session.authorization_url
        assert "id_token_hint" not in params
        assert complete(auth, session)["status"] == "signed_in"
        record = json.loads(auth.path.read_text())
        assert record["subject"] == "test-subject"
        assert record["client_id"] == "oaiapp_test"
        assert os.stat(auth.path).st_mode & 0o777 == 0o600
        form = identity_provider["posts"][0]
        assert form["redirect_uri"] == [session.redirect_uri]
        assert form["client_id"] == ["oaiapp_test"]
        assert form["code_verifier"] == [session.verifier]
        assert "client_secret" not in form
    finally:
        session.close()


@pytest.mark.parametrize("claims", [{"nonce": "wrong"}, {"iss": "https://evil.example"},
    {"aud": "other-client"}, {"exp": int(time.time()) - 100}])
def test_invalid_identity_never_creates_credentials(tmp_path, identity_provider, claims):
    auth = SubscriptionAuth(tmp_path / "auth.json", transport=identity_provider["transport"])
    session = auth.begin_login(port=0)
    identity_provider.update(nonce=session.nonce, claims=claims)
    try:
        with pytest.raises(SubscriptionAuthError, match="validation failed"):
            complete(auth, session)
        assert not auth.path.exists()
    finally:
        session.close()


def test_bad_state_and_changed_client_stop_before_exchange(tmp_path, identity_provider):
    auth = SubscriptionAuth(tmp_path / "auth.json", transport=identity_provider["transport"])
    saved_record(auth.path)
    session = auth.begin_login(port=0)
    try:
        with pytest.raises(SubscriptionAuthError, match="state"):
            auth._complete_login(session, {"state": ["wrong"], "code": ["secret"]})
        with pytest.raises(SubscriptionAuthError, match="changed"):
            auth._complete_login(session, {"state": [session.state], "code": ["secret"],
                "client_id": ["other"]})
        assert identity_provider["posts"] == []
        assert json.loads(auth.path.read_text())["access_token"] == "old-access"
    finally:
        session.close()


def test_missing_direct_scope_and_wrong_returning_account_are_rejected(tmp_path, identity_provider):
    auth = SubscriptionAuth(tmp_path / "auth.json", transport=identity_provider["transport"])
    saved_record(auth.path)
    session = auth.begin_login(port=0)
    identity_provider.update(nonce=session.nonce, scope="openid")
    try:
        with pytest.raises(SubscriptionAuthError, match="permission"):
            complete(auth, session)
        identity_provider.update(scope=DIRECT_SCOPE, subject="other-subject")
        with pytest.raises(SubscriptionAuthError, match="different account"):
            complete(auth, session)
        assert json.loads(auth.path.read_text())["access_token"] == "old-access"
    finally:
        session.close()


def test_concurrent_refresh_rotates_once_across_auth_instances(tmp_path, identity_provider):
    path = tmp_path / "auth.json"
    saved_record(path)
    async def scenario():
        return await asyncio.gather(*(SubscriptionAuth(path, transport=identity_provider["transport"]).access_token()
                                     for _ in range(8)))
    assert asyncio.run(scenario()) == ["refreshed-access"] * 8
    assert len(identity_provider["posts"]) == 1
    form = identity_provider["posts"][0]
    assert form == {"grant_type": ["refresh_token"], "client_id": ["oaiapp_test"],
                    "refresh_token": ["old-refresh"], "resource": [RESOURCE]}
    assert json.loads(path.read_text())["refresh_token"] == "rotated-refresh"


@pytest.mark.parametrize("error,status,kept", [("temporarily_unavailable", 503, True),
                                             ("invalid_grant", 400, False)])
def test_refresh_error_preserves_or_invalidates_session_safely(tmp_path, identity_provider, error, status, kept):
    auth = SubscriptionAuth(tmp_path / "auth.json", transport=identity_provider["transport"])
    saved_record(auth.path)
    identity_provider.update(error=error, status=status)
    with pytest.raises(SubscriptionAuthError) as caught:
        asyncio.run(auth.access_token())
    assert "do-not-log-secret" not in str(caught.value)
    assert auth.path.exists() == kept
    if not kept:
        registration = json.loads(auth.registration_path.read_text())
        assert registration["client_id"] == "oaiapp_test"
        assert "refresh_token" not in registration


def test_loopback_listener_ignores_unsolicited_callback(tmp_path, identity_provider, capsys):
    auth = SubscriptionAuth(tmp_path / "auth.json", transport=identity_provider["transport"])
    session = auth.begin_login(port=0)
    identity_provider["nonce"] = session.nonce
    try:
        with httpx.Client(trust_env=False) as client:
            wrong = client.get(session.redirect_uri, params={"state": "wrong", "code": "never-log-me"})
            assert wrong.status_code == 400
            assert not session.result.done()
            response = client.get(session.redirect_uri, params={"state": session.state,
                "code": "never-log-me", "client_id": "oaiapp_test"})
        assert response.status_code == 200
        assert session.wait(timeout=1)["status"] == "signed_in"
        captured = capsys.readouterr()
        assert "never-log-me" not in captured.out + captured.err
    finally:
        session.close()


def test_local_landing_page_has_safe_escaped_authorization_link(tmp_path, identity_provider):
    auth = SubscriptionAuth(tmp_path / "auth.json", transport=identity_provider["transport"])
    session = auth.begin_login(port=0)
    try:
        with httpx.Client(trust_env=False) as client:
            response = client.get(session.landing_url, params={"code": "callback-secret", "token": "token-secret"})
        assert response.status_code == 200
        assert response.headers["cache-control"] == "no-store"
        assert response.headers["referrer-policy"] == "no-referrer"
        assert "Continue with ChatGPT" in response.text
        assert session.authorization_url in unescape(response.text)
        assert "&amp;" in response.text
        for forbidden in (session.verifier, "callback-secret", "token-secret", "test-access", "test-refresh",
                          "<script", "<img", "<link", "id_token_hint"):
            assert forbidden not in response.text
        assert identity_provider["posts"] == []
        assert not session.result.done()
    finally:
        session.close()


def test_world_readable_and_symlink_records_are_rejected(tmp_path):
    path = tmp_path / "auth.json"
    saved_record(path, expires_at=time.time() + 600)
    path.chmod(0o644)
    with pytest.raises(SubscriptionAuthError, match="owner-only"):
        asyncio.run(SubscriptionAuth(path).access_token())
    linked = tmp_path / "linked.json"
    linked.symlink_to(path)
    with pytest.raises(SubscriptionAuthError, match="protected"):
        asyncio.run(SubscriptionAuth(linked).access_token())

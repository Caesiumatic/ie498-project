"""Encrypted transfer of this application's OAuth record between authorized hosts.

Only public requests, ciphertext envelopes, and authenticated receipts may cross
the tool channel. Plaintext credentials and transfer private keys stay in 0600
files on their respective hosts. This module never refreshes tokens or performs
inference; only the official public identity metadata is read for validation.
"""
from __future__ import annotations

import base64
import hashlib
import hmac
import json
import math
from pathlib import Path
import re
import secrets
import time
import uuid
from datetime import datetime

from cryptography.exceptions import InvalidTag
from cryptography.hazmat.primitives import hashes, serialization
from cryptography.hazmat.primitives.asymmetric.x25519 import X25519PrivateKey, X25519PublicKey
from cryptography.hazmat.primitives.ciphers.aead import AESGCM
from cryptography.hazmat.primitives.kdf.hkdf import HKDF

from .subscription_auth import (
    DIRECT_SCOPE, ISSUER, SubscriptionAuth, SubscriptionAuthError,
    _read_private, _write_private,
)


PROTOCOL = "ie498-chatgpt-credential-handoff-v1"
MAX_RECORD_BYTES = 65536
MAX_ENVELOPE_BYTES = 100000
PUBLIC_FIELDS = {"protocol", "transfer_id", "recipient_public_key", "expires_at", "vm_host_id"}
ENVELOPE_FIELDS = {"public_request", "sender_public_key", "nonce", "ciphertext"}
RECEIPT_FIELDS = {"protocol", "transfer_id", "envelope_sha256", "record_sha256", "status", "receipt_mac"}
RECORD_FIELDS = {"email", "issuer", "subject", "client_id", "ext_agent_host_id", "id_token",
                 "access_token", "refresh_token", "token_type", "expires_in", "expires_at",
                 "scopes", "saved_at", "earliest_refresh_at"}


def canonical(value):
    return json.dumps(value, sort_keys=True, separators=(",", ":"), ensure_ascii=True, allow_nan=False).encode()


def _encode(value):
    return base64.urlsafe_b64encode(value).decode().rstrip("=")


def _decode(value, length=None, maximum=MAX_ENVELOPE_BYTES):
    if not isinstance(value, str) or len(value) > maximum * 2 or not re.fullmatch(r"[A-Za-z0-9_-]+", value):
        raise SubscriptionAuthError("Invalid encrypted handoff encoding.")
    try:
        result=base64.b64decode(value + "=" * (-len(value) % 4), altchars=b"-_", validate=True)
    except ValueError:
        raise SubscriptionAuthError("Invalid encrypted handoff encoding.") from None
    if len(result)>maximum or (length is not None and len(result)!=length):
        raise SubscriptionAuthError("Invalid encrypted handoff size.")
    return result


def _strict_object(pairs):
    result={}
    for key,value in pairs:
        if key in result:
            raise SubscriptionAuthError("Duplicate encrypted handoff field.")
        result[key]=value
    return result


def load_public_json(path):
    """Read a bounded public/ciphertext JSON artifact, never an OAuth record."""
    path=Path(path)
    if path.stat().st_size>MAX_ENVELOPE_BYTES:
        raise SubscriptionAuthError("Encrypted handoff artifact is too large.")
    try:
        with path.open() as stream:
            value=json.load(stream, object_pairs_hook=_strict_object,
                            parse_constant=lambda _: (_ for _ in ()).throw(ValueError()))
    except (ValueError, UnicodeError):
        raise SubscriptionAuthError("Invalid encrypted handoff JSON.") from None
    if not isinstance(value,dict):
        raise SubscriptionAuthError("Invalid encrypted handoff object.")
    return value


def _validate_public(public, *, check_expiry=True):
    if not isinstance(public,dict) or set(public)!=PUBLIC_FIELDS or public.get("protocol")!=PROTOCOL:
        raise SubscriptionAuthError("Unsupported encrypted handoff request.")
    if not isinstance(public["transfer_id"],str) or not re.fullmatch(r"[a-f0-9]{64}",public["transfer_id"]):
        raise SubscriptionAuthError("Invalid encrypted handoff identifier.")
    _decode(public["recipient_public_key"],32)
    try:
        expires=float(public["expires_at"])
        host=str(public["vm_host_id"])
        assert host.startswith("urn:uuid:")
        uuid.UUID(host[len("urn:uuid:"):])
    except (TypeError,ValueError,AssertionError):
        raise SubscriptionAuthError("Invalid encrypted handoff metadata.") from None
    if not math.isfinite(expires) or (check_expiry and expires<=time.time()):
        raise SubscriptionAuthError("Encrypted handoff expired; prepare a new request.")


def _private_path(auth):
    return auth.path.with_suffix(".handoff-private.json")


def _pending_path(auth):
    return auth.path.with_suffix(".handoff-sender.json")


def _keys(private_key, peer_public, public):
    try:
        shared=private_key.exchange(X25519PublicKey.from_public_bytes(peer_public))
    except ValueError:
        raise SubscriptionAuthError("Invalid encrypted handoff public key.") from None
    derived=HKDF(algorithm=hashes.SHA256(),length=64,
                 salt=bytes.fromhex(public["transfer_id"]),info=canonical(public)).derive(shared)
    return derived[:32],derived[32:]


def _raw_public(key):
    return key.public_key().public_bytes(serialization.Encoding.Raw,serialization.PublicFormat.Raw)


def _validate_record(auth,record):
    if not isinstance(record,dict) or set(record)-RECORD_FIELDS:
        raise SubscriptionAuthError("Unexpected fields in this application's OAuth record.")
    for field in ("client_id","subject","id_token","access_token","refresh_token","saved_at","ext_agent_host_id"):
        if not isinstance(record.get(field),str) or not 1<=len(record[field])<=16000:
            raise SubscriptionAuthError("The application's OAuth record is incomplete.")
    if record["client_id"]=="dynamic_agent_client" or record.get("issuer")!=ISSUER or record.get("token_type")!="Bearer":
        raise SubscriptionAuthError("Invalid OAuth registration metadata.")
    scopes=record.get("scopes")
    if not isinstance(scopes,list) or any(not isinstance(scope,str) for scope in scopes) or DIRECT_SCOPE not in scopes:
        raise SubscriptionAuthError("The OAuth record lacks ChatGPT plan permission.")
    try:
        expiry=float(record["expires_at"]); duration=float(record["expires_in"])
        saved=datetime.fromisoformat(record["saved_at"].replace("Z","+00:00"))
        if saved.tzinfo is None:raise ValueError()
    except (KeyError,TypeError,ValueError):
        raise SubscriptionAuthError("The OAuth expiry metadata is invalid.") from None
    if not math.isfinite(expiry) or not math.isfinite(duration) or duration<=0 or expiry<=time.time() or abs(saved.timestamp()+duration-expiry)>1:
        raise SubscriptionAuthError("The OAuth credentials expired or their expiry metadata is invalid.")
    with auth._client() as client:
        identity=auth._identity(client,record["id_token"],record["client_id"])
    if identity["sub"]!=record["subject"]:
        raise SubscriptionAuthError("The OAuth account identity does not match its credential record.")


def prepare_handoff(auth: SubscriptionAuth, *, ttl_seconds=1800):
    """Return a shareable request; keep the recipient private key only on this VM."""
    if not 60<=ttl_seconds<=86400:
        raise SubscriptionAuthError("Handoff lifetime must be between 60 and 86400 seconds.")
    with auth._locked():
        previous=_read_private(_private_path(auth),optional=True)
        if previous and not previous.get("consumed") and previous.get("public_request",{}).get("expires_at",0)>time.time():
            _validate_public(previous["public_request"])
            return previous["public_request"]
        current=_read_private(auth.path,optional=True)
        registration=_read_private(auth.registration_path,optional=True) or {}
        if current:
            registration={key:current[key] for key in ("client_id","subject","issuer","ext_agent_host_id") if key in current}
        registration.setdefault("ext_agent_host_id","urn:uuid:"+str(uuid.uuid4()))
        _write_private(auth.registration_path,registration)
        key=X25519PrivateKey.generate()
        public={"protocol":PROTOCOL,"transfer_id":secrets.token_hex(32),
                "recipient_public_key":_encode(_raw_public(key)),"expires_at":time.time()+ttl_seconds,
                "vm_host_id":registration["ext_agent_host_id"]}
        _validate_public(public)
        _write_private(_private_path(auth),{"public_request":public,"recipient_private_key":_encode(
            key.private_bytes(serialization.Encoding.Raw,serialization.PrivateFormat.Raw,serialization.NoEncryption()))})
        return public


def seal_handoff(auth: SubscriptionAuth, public):
    """Encrypt only this app's locally authorized OAuth record; return ciphertext."""
    _validate_public(public)
    with auth._locked():
        if auth.path.stat().st_size>MAX_RECORD_BYTES:
            raise SubscriptionAuthError("The application's OAuth record is too large.")
        record=_read_private(auth.path)
        _validate_record(auth,record)
        plaintext=canonical(record)
        if len(plaintext)>MAX_RECORD_BYTES:
            raise SubscriptionAuthError("The application's OAuth record is too large.")
        digest=hashlib.sha256(plaintext).hexdigest()
        previous=_read_private(_pending_path(auth),optional=True)
        if previous and previous.get("envelope",{}).get("public_request")==public and previous.get("record_sha256")==digest:
            return previous["envelope"]
        if previous and previous.get("envelope",{}).get("public_request",{}).get("expires_at",0)>time.time():
            raise SubscriptionAuthError("A local credential handoff is already pending.")
        key=X25519PrivateKey.generate()
        encryption_key,receipt_key=_keys(key,_decode(public["recipient_public_key"],32),public)
        nonce=secrets.token_bytes(12)
        envelope={"public_request":public,"sender_public_key":_encode(_raw_public(key)),"nonce":_encode(nonce),
                  "ciphertext":_encode(AESGCM(encryption_key).encrypt(nonce,plaintext,canonical(public)))}
        _write_private(_pending_path(auth),{"record_sha256":digest,"receipt_key":_encode(receipt_key),"envelope":envelope})
        return envelope


def import_handoff(auth: SubscriptionAuth, envelope):
    """Validate and import once, preserving the VM host ID; return safe receipt."""
    if not isinstance(envelope,dict) or set(envelope)!=ENVELOPE_FIELDS or len(canonical(envelope))>MAX_ENVELOPE_BYTES:
        raise SubscriptionAuthError("Invalid encrypted handoff envelope.")
    public=envelope["public_request"];_validate_public(public)
    with auth._locked():
        state=_read_private(_private_path(auth),optional=True)
        if not state or state.get("consumed") or state.get("public_request")!=public:
            raise SubscriptionAuthError("Encrypted handoff was consumed or does not match this VM.")
        private=X25519PrivateKey.from_private_bytes(_decode(state["recipient_private_key"],32))
        encryption_key,receipt_key=_keys(private,_decode(envelope["sender_public_key"],32),public)
        try:
            plaintext=AESGCM(encryption_key).decrypt(_decode(envelope["nonce"],12),
                _decode(envelope["ciphertext"],maximum=MAX_RECORD_BYTES+16),canonical(public))
            record=json.loads(plaintext,object_pairs_hook=_strict_object)
        except (InvalidTag,ValueError,UnicodeError):
            raise SubscriptionAuthError("Encrypted handoff authentication failed.") from None
        _validate_record(auth,record)
        current=_read_private(auth.path,optional=True)
        registration=_read_private(auth.registration_path,optional=True) or {}
        if registration.get("ext_agent_host_id")!=public["vm_host_id"]:
            raise SubscriptionAuthError("VM host identity changed during handoff.")
        for existing in (current,registration):
            if existing and any(existing.get(key) and existing[key]!=record.get(key) for key in ("client_id","subject","issuer")):
                raise SubscriptionAuthError("Handoff cannot replace a different registered account.")
        receipt={"protocol":PROTOCOL,"transfer_id":public["transfer_id"],
                 "envelope_sha256":hashlib.sha256(canonical(envelope)).hexdigest(),
                 "record_sha256":hashlib.sha256(canonical(record)).hexdigest(),"status":"imported"}
        receipt["receipt_mac"]=_encode(hmac.digest(receipt_key,canonical(receipt),"sha256"))
        # Consume the key durably before installation: a crash cannot permit a
        # replay to overwrite a subsequently rotated refresh token.
        _write_private(_private_path(auth),{"consumed":True,"public_request":public})
        record["ext_agent_host_id"]=public["vm_host_id"]
        _write_private(auth.path,record)
        _write_private(auth.registration_path,{key:record[key] for key in ("client_id","subject","issuer","ext_agent_host_id")})
        _write_private(auth.path.with_suffix(".handoff-receipt.json"),receipt)
        _private_path(auth).unlink()
        return receipt


def retire_local(auth: SubscriptionAuth, receipt):
    """Remove the exact source session only after an authenticated import receipt."""
    if not isinstance(receipt,dict) or set(receipt)!=RECEIPT_FIELDS or receipt.get("protocol")!=PROTOCOL or receipt.get("status")!="imported":
        raise SubscriptionAuthError("Invalid VM import receipt.")
    with auth._locked():
        pending=_read_private(_pending_path(auth),optional=True)
        if not pending:
            raise SubscriptionAuthError("No matching local handoff is pending.")
        body={key:value for key,value in receipt.items() if key!="receipt_mac"}
        expected=hmac.digest(_decode(pending["receipt_key"],32),canonical(body),"sha256")
        if not hmac.compare_digest(expected,_decode(receipt["receipt_mac"],32)):
            raise SubscriptionAuthError("VM import receipt authentication failed.")
        envelope=pending["envelope"]
        if receipt["transfer_id"]!=envelope["public_request"]["transfer_id"] or receipt["envelope_sha256"]!=hashlib.sha256(canonical(envelope)).hexdigest() or receipt["record_sha256"]!=pending["record_sha256"]:
            raise SubscriptionAuthError("VM import receipt does not match this local handoff.")
        record=_read_private(auth.path)
        if hashlib.sha256(canonical(record)).hexdigest()!=pending["record_sha256"]:
            raise SubscriptionAuthError("Local OAuth credentials changed after sealing; they were preserved.")
        _write_private(auth.registration_path,{key:record[key] for key in ("client_id","subject","issuer","ext_agent_host_id")})
        auth.path.unlink()
        _pending_path(auth).unlink()
        return {"status":"local_session_retired","transfer_id":receipt["transfer_id"]}

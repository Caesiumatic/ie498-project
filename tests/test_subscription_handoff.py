import importlib.util
import json
import os
from pathlib import Path
import time
from datetime import datetime, timezone
from copy import deepcopy

from cryptography.hazmat.primitives.asymmetric import rsa
import httpx
import jwt
import pytest

from ie498.subscription_auth import (
    AUTHORIZE_URL, DIRECT_SCOPE, DISCOVERY_URL, ISSUER, JWKS_URL, TOKEN_URL,
    SubscriptionAuth, SubscriptionAuthError, _write_private,
)
from ie498.subscription_handoff import (
    canonical, import_handoff, load_public_json, prepare_handoff, retire_local, seal_handoff,
)


@pytest.fixture
def hosts(tmp_path):
    key=rsa.generate_private_key(public_exponent=65537,key_size=2048)
    jwk=json.loads(jwt.algorithms.RSAAlgorithm.to_jwk(key.public_key()))
    jwk.update(kid="test-key",use="sig",alg="RS256")
    calls=[]
    def handler(request):
        calls.append((request.method,str(request.url)))
        assert request.method=="GET"
        if str(request.url)==DISCOVERY_URL:
            return httpx.Response(200,json={"issuer":ISSUER,"authorization_endpoint":AUTHORIZE_URL,
                "token_endpoint":TOKEN_URL,"jwks_uri":JWKS_URL})
        assert str(request.url)==JWKS_URL
        return httpx.Response(200,json={"keys":[jwk]})
    transport=httpx.MockTransport(handler)
    local=SubscriptionAuth(tmp_path/"local"/"auth.json",transport=transport)
    vm=SubscriptionAuth(tmp_path/"vm"/"auth.json",transport=transport)
    now=time.time()
    token=jwt.encode({"iss":ISSUER,"sub":"test-user","aud":"oaiapp_test",
                      "iat":int(now),"exp":int(now)+600},key,algorithm="RS256",headers={"kid":"test-key"})
    record={"issuer":ISSUER,"subject":"test-user","client_id":"oaiapp_test",
            "ext_agent_host_id":"urn:uuid:00000000-0000-4000-8000-000000000001",
            "access_token":"private-access-never-print", "refresh_token":"private-refresh-never-print",
            "id_token":token,"token_type":"Bearer","scopes":[DIRECT_SCOPE],
            "saved_at":datetime.fromtimestamp(now,timezone.utc).isoformat(),"expires_in":600,"expires_at":now+600}
    local.path.parent.mkdir(mode=0o700)
    _write_private(local.path,record)
    return local,vm,record,calls


def test_roundtrip_preserves_vm_host_private_permissions_and_requires_receipt(hosts):
    local,vm,record,calls=hosts
    public=prepare_handoff(vm)
    assert prepare_handoff(vm)==public
    assert public["vm_host_id"]!=record["ext_agent_host_id"]
    assert os.stat(vm.path.with_suffix(".handoff-private.json")).st_mode&0o777==0o600
    envelope=seal_handoff(local,public)
    assert seal_handoff(local,public)==envelope
    assert local.path.exists()  # Sealing is not permission to delete the source.
    for secret in (record["access_token"],record["refresh_token"],record["id_token"]):
        assert secret not in json.dumps(public)+json.dumps(envelope)
    receipt=import_handoff(vm,envelope)
    receipt_path=vm.path.with_suffix(".handoff-receipt.json")
    assert json.loads(receipt_path.read_text())==receipt
    assert os.stat(receipt_path).st_mode&0o777==0o600
    imported=json.loads(vm.path.read_text())
    assert imported=={**record,"ext_agent_host_id":public["vm_host_id"]}
    assert not vm.path.with_suffix(".handoff-private.json").exists()
    assert os.stat(vm.path).st_mode&0o777==0o600
    assert local.path.exists()  # Successful import still needs authenticated retirement.
    assert retire_local(local,receipt)["status"]=="local_session_retired"
    assert not local.path.exists()
    assert json.loads(local.registration_path.read_text())["ext_agent_host_id"]==record["ext_agent_host_id"]
    assert all(method=="GET" for method,_ in calls)


@pytest.mark.parametrize("field",["ciphertext","sender_public_key","nonce"])
def test_tampered_ciphertext_never_changes_either_host(hosts,field):
    local,vm,record,calls=hosts
    envelope=seal_handoff(local,prepare_handoff(vm))
    original=local.path.read_bytes()
    bad=deepcopy(envelope); value=bad[field]
    bad[field]=("A" if value[0]!="A" else "B")+value[1:]
    with pytest.raises(SubscriptionAuthError):import_handoff(vm,bad)
    assert not vm.path.exists()
    assert local.path.read_bytes()==original
    assert vm.path.with_suffix(".handoff-private.json").exists()


def test_replay_and_expired_or_changed_public_request_are_rejected(hosts):
    local,vm,_,_=hosts
    public=prepare_handoff(vm); envelope=seal_handoff(local,public)
    bad=deepcopy(envelope);bad["public_request"]["expires_at"]=time.time()-1
    with pytest.raises(SubscriptionAuthError,match="expired"):import_handoff(vm,bad)
    bad=deepcopy(envelope);bad["public_request"]["transfer_id"]="f"*64
    with pytest.raises(SubscriptionAuthError,match="does not match"):import_handoff(vm,bad)
    import_handoff(vm,envelope)
    current=vm.path.read_bytes()
    with pytest.raises(SubscriptionAuthError,match="consumed"):import_handoff(vm,envelope)
    assert vm.path.read_bytes()==current


def test_existing_account_binding_and_forged_receipt_do_not_destroy_credentials(hosts):
    local,vm,_,_=hosts
    public=prepare_handoff(vm);envelope=seal_handoff(local,public)
    registration=json.loads(vm.registration_path.read_text())
    _write_private(vm.registration_path,{**registration,"subject":"different-user"})
    with pytest.raises(SubscriptionAuthError,match="different registered account"):
        import_handoff(vm,envelope)
    assert not vm.path.exists()
    _write_private(vm.registration_path,registration)
    receipt=import_handoff(vm,envelope)
    bad={**receipt,"status":"not_imported"}
    with pytest.raises(SubscriptionAuthError):retire_local(local,bad)
    bad={**receipt,"record_sha256":"0"*64}
    with pytest.raises(SubscriptionAuthError,match="authentication failed"):retire_local(local,bad)
    assert local.path.exists()
    changed=json.loads(local.path.read_text());changed["refresh_token"]="newer-local-session"
    _write_private(local.path,changed)
    with pytest.raises(SubscriptionAuthError,match="changed after sealing"):retire_local(local,receipt)
    assert json.loads(local.path.read_text())["refresh_token"]=="newer-local-session"


def test_identity_signature_and_scope_are_revalidated(hosts):
    local,vm,record,_=hosts
    public=prepare_handoff(vm)
    _write_private(local.path,{**record,"scopes":["openid"]})
    with pytest.raises(SubscriptionAuthError,match="permission"):seal_handoff(local,public)
    _write_private(local.path,{**record,"id_token":"not-a-signed-id-token"})
    with pytest.raises(SubscriptionAuthError,match="validation failed"):seal_handoff(local,public)
    assert not vm.path.exists()


def test_bounded_json_and_cli_only_emit_public_material(hosts,tmp_path,monkeypatch,capsys):
    local,vm,record,_=hosts
    spec=importlib.util.spec_from_file_location("handoff_cli",Path(__file__).parents[1]/"scripts/subscription_handoff.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    public=prepare_handoff(vm);public_path=tmp_path/"request.json"
    public_path.write_bytes(canonical(public))
    monkeypatch.setattr(module,"SubscriptionAuth",lambda path:local)
    assert module.main(["seal","--auth-file",str(local.path),"--input",str(public_path)])==0
    output=capsys.readouterr()
    envelope=json.loads(output.out)
    assert envelope["public_request"]==public
    assert not output.err
    for secret in (record["access_token"],record["refresh_token"],record["id_token"]):
        assert secret not in output.out
    public_path.write_text('{"same":1,"same":2}')
    with pytest.raises(SubscriptionAuthError,match="Duplicate"):load_public_json(public_path)
    public_path.write_text("x"*100001)
    with pytest.raises(SubscriptionAuthError,match="too large"):load_public_json(public_path)


def test_cli_output_cannot_overwrite_credentials_or_private_state(hosts,monkeypatch,capsys):
    local,_,_,_=hosts
    spec=importlib.util.spec_from_file_location("handoff_cli_guard",Path(__file__).parents[1]/"scripts/subscription_handoff.py")
    module=importlib.util.module_from_spec(spec);spec.loader.exec_module(module)
    monkeypatch.setattr(module,"SubscriptionAuth",lambda path:local)
    original=local.path.read_bytes()
    targets=[local.path,local.registration_path,local.lock_path,
             local.path.with_suffix(".handoff-private.json"),local.path.with_suffix(".handoff-sender.json")]
    for target in targets:
        assert module.main(["prepare","--auth-file",str(local.path),"--output",str(target)])==1
        output=capsys.readouterr()
        assert not output.out
        assert "cannot overwrite" in output.err
        assert local.path.read_bytes()==original

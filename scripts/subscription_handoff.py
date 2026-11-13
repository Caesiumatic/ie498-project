"""Transfer only encrypted experiment OAuth credentials between authorized hosts."""
import argparse
import json
from pathlib import Path
import sys

ROOT=Path(__file__).resolve().parents[1]
sys.path.insert(0,str(ROOT/"src"))
from ie498.subscription_auth import DEFAULT_AUTH_PATH, SubscriptionAuth, SubscriptionAuthError, _write_private
from ie498.subscription_handoff import prepare_handoff, seal_handoff, import_handoff, retire_local, load_public_json


def main(argv=None):
    parser=argparse.ArgumentParser(description=__doc__)
    parser.add_argument("command",choices=("prepare","seal","import","retire-local"))
    parser.add_argument("--auth-file",type=Path,default=DEFAULT_AUTH_PATH)
    parser.add_argument("--input",type=Path,help="Public request, ciphertext envelope, or import receipt")
    parser.add_argument("--output",type=Path,help="Save safe result to this file instead of stdout")
    parser.add_argument("--ttl",type=int,default=1800,help="Recipient request validity in seconds")
    args=parser.parse_args(argv)
    if args.command!="prepare" and args.input is None:
        parser.error("This command requires --input")
    try:
        auth=SubscriptionAuth(args.auth_file)
        if args.output:
            protected={auth.path,auth.registration_path,auth.lock_path,
                       auth.path.with_suffix(".handoff-private.json"),auth.path.with_suffix(".handoff-sender.json")}
            if args.output.resolve() in {path.resolve() for path in protected}:
                raise SubscriptionAuthError("Handoff output cannot overwrite credentials or private transfer state.")
        if args.command=="prepare": result=prepare_handoff(auth,ttl_seconds=args.ttl)
        else:
            value=load_public_json(args.input)
            action={"seal":seal_handoff,"import":import_handoff,"retire-local":retire_local}[args.command]
            result=action(auth,value)
        if args.output:
            args.output.parent.mkdir(parents=True,exist_ok=True,mode=0o700)
            _write_private(args.output,result)
            print(json.dumps({"status":"saved","command":args.command,"output":str(args.output)}))
        else:
            # Every result schema is public metadata, ciphertext, or an HMAC receipt.
            print(json.dumps(result,sort_keys=True))
        return 0
    except (SubscriptionAuthError,OSError,ValueError,KeyError,TypeError) as error:
        message=str(error) if isinstance(error,SubscriptionAuthError) else "Credential handoff could not be completed; source credentials were preserved."
        print(message,file=sys.stderr)
        return 1


if __name__=="__main__":
    raise SystemExit(main())

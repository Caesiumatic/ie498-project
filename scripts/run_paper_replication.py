"""Prepare/run/audit the independent six-condition paper reconstruction."""
import argparse
import asyncio
import json
import os
from pathlib import Path
import sys

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ie498.cli import load_env
from ie498.paper_execution import DATA_ROOT, TRANSPORTS, audit, execute, open_store, plan, prepare, status
from ie498.runner import coordinator_lock
from ie498.subscription_auth import SubscriptionAuth


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("action", choices=("preview", "prepare", "run", "status", "audit"))
    parser.add_argument("--transport", choices=TRANSPORTS)
    parser.add_argument("--data-root", type=Path, default=DATA_ROOT)
    args = parser.parse_args()
    if args.action in ("preview", "prepare", "run") and args.transport is None:
        parser.error("An explicit --transport is required; there is no automatic fallback")
    if args.action == "preview":
        print(json.dumps(plan(args.transport), indent=2))
        return
    store = open_store(args.data_root)
    try:
        with coordinator_lock(store):
            if args.action == "status":
                print(json.dumps(status(store), indent=2))
            elif args.action == "audit":
                print(json.dumps(audit(store), indent=2))
            else:
                manifest = prepare(store, args.transport)
                if args.action == "prepare":
                    print(json.dumps({"prepared": True, "manifest": str(store.root / "manifest.json"), "calls_made": 0}))
                else:
                    load_env()
                    auth = SubscriptionAuth(ROOT / "data/auth/chatgpt-plan.json") if args.transport == "chatgpt_subscription" else None
                    asyncio.run(execute(store, manifest, api_key=os.environ.get("OPENAI_API_KEY"), auth=auth))
    finally:
        store.close()


if __name__ == "__main__":
    main()

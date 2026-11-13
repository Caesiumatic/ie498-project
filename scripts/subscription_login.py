"""Authorize this experiment to use a ChatGPT plan through official OAuth."""
import argparse
import json
from pathlib import Path
import sys
import webbrowser

ROOT = Path(__file__).resolve().parents[1]
sys.path.insert(0, str(ROOT / "src"))
from ie498.subscription_auth import DEFAULT_AUTH_PATH, SubscriptionAuth, SubscriptionAuthError


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--begin", action="store_true", help="Print a local sign-in page URL and listen for its loopback callback.")
    parser.add_argument("--open-browser", action="store_true", help="Open the sign-in page on this machine.")
    parser.add_argument("--auth-file", type=Path, default=DEFAULT_AUTH_PATH)
    parser.add_argument("--port", type=int, default=1455)
    parser.add_argument("--timeout", type=float, default=900)
    args = parser.parse_args()
    if not args.begin:
        parser.error("Use --begin to start a new sign-in attempt.")
    session = None
    try:
        session = SubscriptionAuth(args.auth_file).begin_login(port=args.port)
        print("Open this local page and select Continue with ChatGPT:\n" + session.landing_url, flush=True)
        print("Use a browser on the same machine as this helper, including the cloud Desktop "
              "browser when the helper runs in the cloud. Both the page and callback use "
              "this machine's loopback address. A browser on another machine needs an "
              "existing secure loopback forwarding connection.", flush=True)
        if args.open_browser:
            webbrowser.open(session.landing_url)
        result = session.wait(timeout=args.timeout)
        print(json.dumps(result), flush=True)
    except (SubscriptionAuthError, OSError) as error:
        # No response bodies, callback URLs, codes, or credential records are printed.
        message = str(error) if isinstance(error, SubscriptionAuthError) else "Unable to start the loopback listener."
        print(message, file=sys.stderr, flush=True)
        return 1
    except KeyboardInterrupt:
        print("Sign-in canceled.", file=sys.stderr)
        return 130
    finally:
        if session:
            session.close()
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

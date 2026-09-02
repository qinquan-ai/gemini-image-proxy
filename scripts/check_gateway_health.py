import argparse
import json
import sys
from urllib.error import URLError
from urllib.request import urlopen


def parse_args() -> argparse.Namespace:
    parser = argparse.ArgumentParser(description="Check a running Gemini Image Gateway health endpoint.")
    parser.add_argument(
        "--url",
        default="http://127.0.0.1:4981/healthz",
        help="Health endpoint URL, default: http://127.0.0.1:4981/healthz",
    )
    parser.add_argument("--timeout", type=float, default=5, help="Request timeout in seconds")
    return parser.parse_args()


def main() -> int:
    args = parse_args()
    if args.timeout <= 0:
        print("--timeout must be positive", file=sys.stderr)
        return 2

    try:
        with urlopen(args.url, timeout=args.timeout) as response:
            body = response.read().decode("utf-8", errors="replace")
            print(f"STATUS={response.status}")
            try:
                print(json.dumps(json.loads(body), ensure_ascii=False))
            except json.JSONDecodeError:
                print(body)
            return 0 if 200 <= response.status < 300 else 1
    except URLError as exc:
        print(f"HEALTH_CHECK_FAILED={exc.reason}", file=sys.stderr)
        return 1


if __name__ == "__main__":
    raise SystemExit(main())

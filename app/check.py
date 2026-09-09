"""One scheduled run; exits nonzero on scraping or notification failure."""
import argparse
import asyncio
import sys

from app.config import Settings
from app.monitor import Monitor
from app.notify import NotificationError
from app.scraper import PriceReadError


def main() -> int:
    parser = argparse.ArgumentParser()
    parser.add_argument("--dry-run", action="store_true", help="Read live price without sending anything")
    parser.add_argument("--store", choices=("all", "goldapple", "monamie"),
                        help="Check a single store, or both (default: CHECK_STORE/goldapple)")
    args = parser.parse_args()
    try:
        settings = Settings()
        if args.store:
            settings.check_store = args.store
        result = asyncio.run(Monitor(settings).check(dry_run=args.dry_run))
    except (PriceReadError, NotificationError) as exc:
        print(f"Check failed: {exc}", file=sys.stderr)
        return 1
    except ValueError:
        print("Invalid configuration; check .env against .env.example", file=sys.stderr)
        return 1
    print(result.model_dump_json(indent=2))
    return 0 if result.ok else 1


if __name__ == "__main__":
    raise SystemExit(main())

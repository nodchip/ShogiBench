from __future__ import annotations

import argparse
import sys
from pathlib import Path

from .client import (
    ApiClient,
    ClientConfigurationError,
    FatalClientError,
    ManagedClient,
    load_config,
    run_forever,
)


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="python -m AutotuneClient")
    parser.add_argument("--config", type=Path, required=True)
    return parser


def main(argv: list[str] | None = None) -> int:
    try:
        config = load_config(build_parser().parse_args(argv).config)
        run_forever(ManagedClient(ApiClient(config)))
    except (ClientConfigurationError, FatalClientError) as error:
        print(f"managed client stopped: {error}", file=sys.stderr)
        return 2
    except KeyboardInterrupt:
        return 130
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

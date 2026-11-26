"""Official CLI entrypoint for RAKSHA (python main.py --input ... --output ...)."""

from __future__ import annotations

import argparse
import sys
from pathlib import Path
from typing import Sequence

from src.pipeline import RakshaPipeline


def build_arg_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(
        description="RAKSHA — Multilingual Healthcare Privacy Firewall"
    )
    parser.add_argument("--input", type=Path, required=True, help="Input directory path")
    parser.add_argument("--output", type=Path, required=True, help="Output directory path")
    parser.add_argument(
        "--policy",
        type=Path,
        default=Path("config/policy.yaml"),
        help="Optional policy YAML configuration path",
    )
    return parser


def main(argv: Sequence[str] | None = None) -> int:
    args = build_arg_parser().parse_args(argv)
    pipeline = RakshaPipeline(policy_path=args.policy)
    try:
        pipeline.run(input_dir=args.input, output_dir=args.output)
    except Exception as exc:  # Never print raw paths or record contents
        print(f"RAKSHA execution halted: {type(exc).__name__}", file=sys.stderr)
        return 1
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

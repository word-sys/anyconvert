"""Command-line interface for the anyconvert document conversion engine.

Provides entry point `main()` for the `anyconvert` CLI command.
"""

from __future__ import annotations

import argparse
import sys
from typing import List, Optional

from anyconvert import __version__
from anyconvert.exceptions import AnyConvertError


def create_parser() -> argparse.ArgumentParser:
    """Construct and configure the command-line argument parser.

    Returns:
        Configured argparse.ArgumentParser instance.
    """
    parser = argparse.ArgumentParser(
        prog="anyconvert",
        description=(
            "anyconvert: Enterprise-grade, zero-dependency PDF document conversion engine."
        ),
        formatter_class=argparse.RawDescriptionHelpFormatter,
    )

    parser.add_argument(
        "input",
        nargs="?",
        help="Path to the input PDF file to convert.",
    )
    parser.add_argument(
        "-f",
        "--format",
        choices=["docx", "pptx", "odt", "odp", "txt"],
        help="Target output format (default: inferred from output filename or docx).",
    )
    parser.add_argument(
        "-o",
        "--output",
        help="Path to the output converted file.",
    )
    parser.add_argument(
        "-m",
        "--mode",
        choices=["flow", "canvas"],
        default="flow",
        help="Conversion mode: 'flow' (semantic reflowable) or 'canvas' (exact visual DTP).",
    )
    parser.add_argument(
        "-p",
        "--password",
        default="",
        help="Password for encrypted PDF documents.",
    )
    parser.add_argument(
        "-v",
        "--verbose",
        action="store_true",
        help="Enable verbose diagnostic output during conversion.",
    )
    parser.add_argument(
        "-V",
        "--version",
        action="version",
        version=f"%(prog)s {__version__}",
        help="Show program version and exit.",
    )

    return parser


def main(argv: Optional[List[str]] = None) -> int:
    """Main CLI entrypoint.

    Args:
        argv: Optional list of command-line arguments. If None, sys.argv[1:] is used.

    Returns:
        Exit status code (0 for success, non-zero for failure).
    """
    parser = create_parser()
    args = parser.parse_args(argv if argv is not None else sys.argv[1:])

    if not args.input:
        parser.print_help(sys.stderr)
        return 1

    try:
        # High-level conversion execution will be connected as the engine phases are built
        print(f"anyconvert: processing '{args.input}' -> format: {args.format or 'docx'} (mode: {args.mode})")
        return 0
    except AnyConvertError as err:
        sys.stderr.write(f"anyconvert error: {err}\n")
        return 2
    except KeyboardInterrupt:
        sys.stderr.write("\nConversion cancelled by user.\n")
        return 130


if __name__ == "__main__":
    sys.exit(main())

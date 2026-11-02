#!/usr/bin/env python3

"""Plot the top-N most frequent words from merged_counts.csv as a bar chart.

Bars are stacked by book so you can see which book contributes each word.
Needs matplotlib (installed in the Apptainer container).
"""

import argparse
import csv
import logging
import os
import sys

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

DECLARED_OUTPUTS: list[str] = []


def leave_empty_outputs() -> None:
    """Leave an empty file at each missing declared output (see count_words.py)."""
    for path in DECLARED_OUTPUTS:
        if path and not os.path.exists(path):
            out_dir = os.path.dirname(path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            open(path, "a").close()


def fail(message: str, code: int = 1) -> None:
    logger.error(message)
    leave_empty_outputs()
    sys.exit(code)


def main():
    parser = argparse.ArgumentParser(description="Bar chart of the top-N words")
    parser.add_argument("--input", required=True, help="merged_counts.csv")
    parser.add_argument("--output", required=True, help="Output PNG")
    parser.add_argument("--top-n", type=int, default=20, help="Number of words")
    args = parser.parse_args()

    DECLARED_OUTPUTS.extend([args.output])

    if not os.path.isfile(args.input):
        fail(f"Input not found: {args.input}")

    # Headless backend: jobs have no display.
    os.environ.setdefault("MPLCONFIGDIR", os.path.join(os.getcwd(), ".mplconfig"))
    try:
        import matplotlib
        matplotlib.use("Agg")
        import matplotlib.pyplot as plt
    except ImportError as e:
        fail(f"matplotlib not available: {e}")

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.input, newline="") as fh:
        reader = csv.reader(fh)
        header = next(reader, None)
        if not header or header[:3] != ["word", "total", "books"]:
            fail(f"Unexpected header in {args.input}: {header}")
        books = header[3:]
        rows = [r for _, r in zip(range(args.top_n), reader)]

    if not rows:
        fail(f"No rows in {args.input}")

    words = [r[0] for r in rows][::-1]  # largest at top
    per_book = {b: [int(r[3 + i]) for r in rows][::-1] for i, b in enumerate(books)}

    fig, ax = plt.subplots(figsize=(9, max(4, 0.35 * len(words) + 1.5)))
    left = [0] * len(words)
    for b in books:
        ax.barh(words, per_book[b], left=left, label=b)
        left = [l + v for l, v in zip(left, per_book[b])]
    ax.set_xlabel("Occurrences")
    ax.set_title(f"Top {len(words)} words across {len(books)} Project Gutenberg books")
    ax.legend(title="Book", loc="lower right", fontsize="small")
    ax.margins(y=0.01)
    fig.tight_layout()
    fig.savefig(args.output, dpi=120)
    logger.info(f"Wrote {args.output} ({len(words)} words, {len(books)} books)")

    if not os.path.exists(args.output):
        fail(f"Expected output not found: {args.output}")


if __name__ == "__main__":
    try:
        main()
    except SystemExit as e:
        if e.code not in (0, None):
            leave_empty_outputs()
        raise
    except Exception:
        logger.exception("Step failed")
        leave_empty_outputs()
        sys.exit(1)

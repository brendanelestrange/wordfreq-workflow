#!/usr/bin/env python3

"""Merge per-book word counts into one CSV (fan-in step).

Reads every --input counts JSON written by count_words.py and writes
merged_counts.csv with one row per word, sorted by total count:

    word,total,books,pg11,pg84,...

`books` is the number of books the word appears in. Standard library only.
"""

import argparse
import csv
import json
import logging
import os
import sys
from collections import Counter

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
    parser = argparse.ArgumentParser(description="Merge per-book word counts")
    parser.add_argument("--input", action="append", required=True,
                        help="Counts JSON (repeat once per book)")
    parser.add_argument("--output", required=True, help="Merged CSV")
    args = parser.parse_args()

    DECLARED_OUTPUTS.extend([args.output])

    missing = [p for p in args.input if not os.path.isfile(p)]
    if missing:
        fail(f"Inputs not found: {missing}")

    logger.info(f"Merging {len(args.input)} files -> {args.output}")

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    per_book = {}
    total = Counter()
    for path in args.input:
        with open(path) as fh:
            try:
                data = json.load(fh)
            except json.JSONDecodeError as e:
                fail(f"{path} is not valid JSON: {e}")
        book = data.get("book", os.path.basename(path))
        counts = data["counts"]
        per_book[book] = counts
        total.update(counts)
        logger.info(f"  {book}: {data.get('total_words', '?')} words")

    if not total:
        fail("All input count files were empty")

    books = sorted(per_book)
    with open(args.output, "w", newline="") as fh:
        writer = csv.writer(fh)
        writer.writerow(["word", "total", "books", *books])
        for word, n in total.most_common():
            row = [per_book[b].get(word, 0) for b in books]
            writer.writerow([word, n, sum(1 for c in row if c), *row])

    logger.info(f"{len(total)} distinct words; top 10: {total.most_common(10)}")


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

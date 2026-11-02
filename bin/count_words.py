#!/usr/bin/env python3

"""Count word frequencies in one Project Gutenberg book.

Strips the Gutenberg license header/footer, lowercases, tokenizes, drops
stopwords and short words, and writes the counts as JSON:

    {"book": "pg11", "total_words": 12345, "counts": {"alice": 398, ...}}

Invoked by Pegasus as the per-book (fan-out) job. Standard library only.
"""

import argparse
import json
import logging
import os
import re
import sys
from collections import Counter

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)

# Every file this job declares with add_outputs() in workflow_generator.py.
DECLARED_OUTPUTS: list[str] = []

STOPWORDS = set("""
a about above after again against all am an and any are as at be because been
before being below between both but by can could did do does doing down during
each few for from further had has have having he her here hers herself him
himself his how i if in into is it its itself just me more most my myself no
nor not now of off on once only or other our ours ourselves out over own same
she should so some such than that the their theirs them themselves then there
these they this those through to too under until up upon very was we were what
when where which while who whom why will with would you your yours yourself
yourselves said one shall may must might us thee thou thy
""".split())

START_RE = re.compile(r"^\*\*\* ?START OF (THE|THIS) PROJECT GUTENBERG.*$", re.M | re.I)
END_RE = re.compile(r"^\*\*\* ?END OF (THE|THIS) PROJECT GUTENBERG.*$", re.M | re.I)
WORD_RE = re.compile(r"[a-z]+(?:'[a-z]+)?")


def leave_empty_outputs() -> None:
    """Create an empty file at each declared output that does not exist.

    HTCondor transfers declared outputs back before Pegasus checks the exit
    code; a missing one makes the job HELD instead of failed, and its error
    is lost. An empty placeholder lets the job fail visibly.
    """
    for path in DECLARED_OUTPUTS:
        if path and not os.path.exists(path):
            out_dir = os.path.dirname(path)
            if out_dir:
                os.makedirs(out_dir, exist_ok=True)
            open(path, "a").close()


def fail(message: str, code: int = 1) -> None:
    """Report an error and exit non-zero — the only way this script exits early."""
    logger.error(message)
    leave_empty_outputs()
    sys.exit(code)


def strip_gutenberg_boilerplate(text: str) -> str:
    start = START_RE.search(text)
    end = END_RE.search(text)
    body_start = start.end() if start else 0
    body_end = end.start() if end else len(text)
    if not start or not end:
        logger.warning("Gutenberg START/END markers not found; counting whole file")
    return text[body_start:body_end]


def main():
    parser = argparse.ArgumentParser(description="Count words in one book")
    parser.add_argument("--input", required=True, help="Book text file (pgNNN.txt)")
    parser.add_argument("--output", required=True, help="Output counts JSON")
    parser.add_argument("--min-length", type=int, default=3,
                        help="Ignore words shorter than this")
    args = parser.parse_args()

    DECLARED_OUTPUTS.extend([args.output])

    if not os.path.isfile(args.input):
        fail(f"Input not found: {args.input}")

    logger.info(f"Input: {args.input}")
    logger.info(f"Output: {args.output}")
    logger.info(f"Min word length: {args.min_length}")

    out_dir = os.path.dirname(args.output)
    if out_dir:
        os.makedirs(out_dir, exist_ok=True)

    with open(args.input, encoding="utf-8-sig", errors="replace") as fh:
        text = fh.read()

    body = strip_gutenberg_boilerplate(text).lower().replace("’", "'")
    words = [
        w for w in WORD_RE.findall(body)
        if len(w) >= args.min_length and w not in STOPWORDS
    ]
    if not words:
        fail(f"No words counted in {args.input} — is it a text file?")

    counts = Counter(words)
    book = os.path.splitext(os.path.basename(args.input))[0]
    with open(args.output, "w") as fh:
        json.dump(
            {"book": book, "total_words": len(words), "counts": dict(counts)},
            fh,
        )

    logger.info(
        f"{book}: {len(words)} words, {len(counts)} distinct; "
        f"top 5: {counts.most_common(5)}"
    )

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

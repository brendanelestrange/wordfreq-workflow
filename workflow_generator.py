#!/usr/bin/env python3

"""
Pegasus workflow generator for wordfreq.

Counts word frequencies across a set of public-domain books from Project
Gutenberg, merges the counts, and plots the most common words.

Pipeline steps:
1. count_words    - per book (parallel): strip the Gutenberg header/footer,
                    tokenize, drop stopwords, count words -> JSON
2. merge_counts   - fan-in: sum all per-book counts -> merged_counts.csv
3. plot_top_words - bar chart of the top N words -> top_words.png

Input books are registered in the Replica Catalog with their Gutenberg URL as
the PFN, so Pegasus stages them itself (with retries). There is no fetch job.

Usage:
    ./workflow_generator.py --books 11 84 1342 -e condorpool
    ./workflow_generator.py --books 11 84 1342 2701 1661 --top-n 30
    ./workflow_generator.py --books 11 84 -s access-pegasus.yml

Sites follow pegasus-isi/pegasus-gromacs: jobs run on a site named "compute",
defined by a centrally hosted site catalog (-s access-pegasus.yml, ...;
https://github.com/pegasushub/pegasus-site-catalogs) or by one in
~/.pegasusrc. The generator writes no site catalog. On a plain HTCondor pool
with no catalog, use -e condorpool. See PEGASUS.md "Site Catalogs".
"""

import argparse
import logging
import os
import sys
from pathlib import Path

from Pegasus.api import *

logging.basicConfig(
    level=logging.INFO,
    format="%(asctime)s - %(name)s - %(levelname)s - %(message)s",
)
logger = logging.getLogger(__name__)


# Per-tool resource configuration for the transformation catalog.
TOOL_CONFIGS = {
    "count_words": {"memory": "1 GB", "cores": 1},
    "merge_counts": {"memory": "1 GB", "cores": 1},
    "plot_top_words": {"memory": "1 GB", "cores": 1},
}

# A few well-known Project Gutenberg books (ID -> title), used by default.
DEFAULT_BOOKS = ["11", "84", "1342", "1661", "2701"]
# 11 Alice's Adventures in Wonderland, 84 Frankenstein, 1342 Pride and
# Prejudice, 1661 The Adventures of Sherlock Holmes, 2701 Moby Dick

GUTENBERG_URL = "https://www.gutenberg.org/cache/epub/{id}/pg{id}.txt"


class WordfreqWorkflow:
    """Per-book word counts, fan-in merge, top-N bar chart."""

    wf = None
    sc = None
    tc = None
    rc = None
    props = None

    dagfile = None
    wf_dir = None
    shared_scratch_dir = None
    local_storage_dir = None
    wf_name = "wordfreq"

    def __init__(self, dagfile="workflow.yml", books=None, container_image=None,
                 use_container=True):
        self.dagfile = dagfile
        self.wf_dir = str(Path(__file__).parent.resolve())
        self.shared_scratch_dir = os.path.join(self.wf_dir, "scratch")
        self.local_storage_dir = os.path.join(self.wf_dir, "output")
        self.books = list(books or DEFAULT_BOOKS)
        self.use_container = use_container
        self.container_image = os.path.abspath(
            container_image
            or os.path.join(self.wf_dir, "Apptainer", "Wordfreq_Container.sif")
        )

    def write(self):
        """Write all catalogs and workflow to files."""
        if self.sc is not None:
            self.sc.write()
        self.props.write()
        self.rc.write()
        self.tc.write()
        self.wf.write(file=self.dagfile)

    # ------------------------------------------------------------------
    # Plan / run / monitor (thin wrappers over the Pegasus API Workflow
    # object, for interactive use e.g. from a Jupyter notebook)
    # ------------------------------------------------------------------
    def plan_submit(self, exec_site_name="compute", raise_errors=False):
        try:
            self.wf.plan(
                dir="submit",
                sites=[exec_site_name],
                output_sites=["local"],
                # Outputs in output/ even when no catalog defines "local"
                # (a hosted catalog), where Pegasus would use ./wf-output.
                output_dir=self.local_storage_dir,
                cleanup="none",
                verbose=1,
                submit=True,
            )
        except PegasusClientError as e:
            print(e)
            if raise_errors:
                raise

    def status(self):
        try:
            self.wf.status(long=True)
        except PegasusClientError as e:
            print(e)

    def wait(self):
        try:
            self.wf.wait()
        except PegasusClientError as e:
            print(e)

    def statistics(self):
        try:
            self.wf.statistics()
        except PegasusClientError as e:
            print(e)

    # ------------------------------------------------------------------
    # Properties
    # ------------------------------------------------------------------
    def create_pegasus_properties(self, hosted_site_catalog=None):
        self.props = Properties()
        self.props["pegasus.transfer.threads"] = "16"
        if hosted_site_catalog:
            # Use one of Pegasus' centrally hosted site catalogs instead of
            # a locally generated one. pegasus-plan downloads and caches the
            # named file from the catalog repository at plan time.
            # https://pegasus.isi.edu/documentation/reference-guide/catalogs.html#centrally-hosted-site-catalogs
            self.props["pegasus.catalog.site.repo.file"] = hosted_site_catalog

    # ------------------------------------------------------------------
    # Site Catalog
    #
    # Not used by the CLI below — pegasus-plan resolves the site catalog
    # from a centrally hosted one (see -s/--hosted-site-catalog) or uses its
    # built-in condorpool (-e condorpool). Kept for notebook use when a
    # self-contained, locally generated HTCondor site catalog is wanted.
    # ------------------------------------------------------------------
    def create_sites_catalog(self, exec_site_name="compute"):
        self.sc = SiteCatalog()

        local = Site("local").add_directories(
            Directory(
                Directory.SHARED_SCRATCH, self.shared_scratch_dir
            ).add_file_servers(
                FileServer("file://" + self.shared_scratch_dir, Operation.ALL)
            ),
            Directory(
                Directory.LOCAL_STORAGE, self.local_storage_dir
            ).add_file_servers(
                FileServer("file://" + self.local_storage_dir, Operation.ALL)
            ),
        )

        exec_site = (
            Site(exec_site_name)
            .add_condor_profile(universe="vanilla")
            .add_pegasus_profile(style="condor")
        )

        self.sc.add_sites(local, exec_site)

    # ------------------------------------------------------------------
    # Transformation Catalog
    # ------------------------------------------------------------------
    def create_transformation_catalog(self, exec_site_name="compute"):
        self.tc = TransformationCatalog()

        # image points at a local .sif built with `apptainer build` — Pegasus
        # stages it like any other input file. image_site is passed BY KEYWORD:
        # the 4th positional parameter of Container() is `arguments`.
        container = None
        if self.use_container:
            container = Container(
                "wordfreq_container",
                container_type=Container.SINGULARITY,
                image="file://" + self.container_image,
                image_site="local",
            )
            self.tc.add_containers(container)

        transformations = []
        for tool_name, config in TOOL_CONFIGS.items():
            tx = Transformation(
                tool_name,
                site=exec_site_name,
                pfn=os.path.join(self.wf_dir, f"bin/{tool_name}.py"),
                is_stageable=True,
                container=container,
            ).add_pegasus_profile(
                memory=config["memory"], cores=config.get("cores", 1)
            )
            transformations.append(tx)

        self.tc.add_transformations(*transformations)

    # ------------------------------------------------------------------
    # Replica Catalog
    # ------------------------------------------------------------------
    def create_replica_catalog(self):
        """Register each book's Gutenberg URL as its PFN.

        Pegasus' stage-in job downloads the URL with pegasus-transfer
        (retries built in), so no fetch job is needed.
        """
        self.rc = ReplicaCatalog()
        for book_id in self.books:
            self.rc.add_replica(
                "web", f"pg{book_id}.txt", GUTENBERG_URL.format(id=book_id)
            )

    # ------------------------------------------------------------------
    # Workflow DAG
    # ------------------------------------------------------------------
    def create_workflow(self, args):
        """count_words per book -> merge_counts -> plot_top_words."""
        self.wf = Workflow(self.wf_name, infer_dependencies=True)

        # Fan-out: one count job per book, in parallel.
        count_files = []
        for book_id in self.books:
            book_file = File(f"pg{book_id}.txt")
            counts_file = File(f"pg{book_id}_counts.json")
            count_files.append(counts_file)

            count_job = (
                Job("count_words", _id=f"count_words_pg{book_id}",
                    node_label=f"count_words_pg{book_id}")
                .add_args(
                    "--input", book_file,
                    "--output", counts_file,
                    "--min-length", str(args.min_length),
                )
                .add_inputs(book_file)
                .add_outputs(counts_file, stage_out=False, register_replica=False)
            )
            self.wf.add_jobs(count_job)

        # Fan-in: merge every per-book count file.
        merged = File("merged_counts.csv")
        merge_args = []
        for f in count_files:
            merge_args += ["--input", f]
        merge_job = (
            Job("merge_counts", _id="merge_counts", node_label="merge_counts")
            .add_args(*merge_args, "--output", merged)
            .add_inputs(*count_files)
            .add_outputs(merged, stage_out=True, register_replica=False)
        )
        self.wf.add_jobs(merge_job)

        # Final plot.
        chart = File("top_words.png")
        plot_job = (
            Job("plot_top_words", _id="plot_top_words", node_label="plot_top_words")
            .add_args(
                "--input", merged,
                "--output", chart,
                "--top-n", str(args.top_n),
            )
            .add_inputs(merged)
            .add_outputs(chart, stage_out=True, register_replica=False)
        )
        self.wf.add_jobs(plot_job)


# ======================================================================
# main() — CLI argument parsing
# ======================================================================
def main():
    parser = argparse.ArgumentParser(
        description="Word-frequency analysis of Project Gutenberg books "
        "(per-book counts in parallel, fan-in merge, top-N bar chart).",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s --books 11 84 1342 -e condorpool     # plain HTCondor pool, no site catalog
  %(prog)s --books 11 84 1342 2701 1661 --top-n 30
  %(prog)s --books 11 84 -s access-pegasus.yml   # hosted site catalog

Writes the workflow and its catalogs; it does not plan or submit. Plan with
the command it prints, or from the notebook (plan_submit()).
""",
    )

    parser.add_argument(
        "--books",
        type=str,
        nargs="+",
        default=DEFAULT_BOOKS,
        metavar="ID",
        help="Project Gutenberg book IDs to analyze "
        f"(default: {' '.join(DEFAULT_BOOKS)})",
    )
    parser.add_argument(
        "--top-n", type=int, default=20,
        help="Number of words in the bar chart (default: 20)",
    )
    parser.add_argument(
        "--min-length", type=int, default=3,
        help="Ignore words shorter than this (default: 3)",
    )
    parser.add_argument(
        "--container-image", metavar="SIF", type=str, default=None,
        help="Path to the built .sif (default: Apptainer/Wordfreq_Container.sif)",
    )
    parser.add_argument(
        "--no-container", action="store_true",
        help="Run wrappers with the worker's own python3 instead of Apptainer "
        "(needs matplotlib on the workers; for laptop pools without Apptainer)",
    )

    # --- Standard Pegasus arguments ---
    parser.add_argument(
        "-s",
        "--hosted-site-catalog",
        metavar="FILE",
        type=str,
        default=None,
        help="Name of a Pegasus centrally hosted site catalog to plan against "
        "(e.g. access-pegasus.yml), instead of a locally generated one. Sets "
        "pegasus.catalog.site.repo.file; see "
        "https://pegasus.isi.edu/documentation/reference-guide/catalogs.html"
        "#centrally-hosted-site-catalogs",
    )
    parser.add_argument(
        "-e",
        "--execution-site-name",
        metavar="STR",
        type=str,
        default="compute",
        help="Execution site name (default: compute)",
    )
    parser.add_argument(
        "-o",
        "--output",
        metavar="STR",
        type=str,
        default="workflow.yml",
        help="Output file (default: workflow.yml)",
    )

    args = parser.parse_args()

    # --- Input validation (before any Pegasus API calls) ---
    bad = [b for b in args.books if not b.isdigit()]
    if bad:
        parser.error(f"--books takes numeric Gutenberg IDs, got: {' '.join(bad)}")
    if len(set(args.books)) != len(args.books):
        parser.error("--books contains duplicate IDs")
    if args.top_n < 1:
        parser.error("--top-n must be at least 1")
    if args.min_length < 1:
        parser.error("--min-length must be at least 1")

    logger.info("=" * 70)
    logger.info("WORDFREQ WORKFLOW GENERATOR")
    logger.info("=" * 70)
    logger.info(f"Books: {args.books}")
    logger.info(f"Top N: {args.top_n}  Min word length: {args.min_length}")
    logger.info(f"Execution site: {args.execution_site_name}")
    logger.info(
        f"Hosted site catalog: {args.hosted_site_catalog or '(none — supply your own site catalog)'}"
    )
    logger.info(f"Container: {'(none)' if args.no_container else 'Apptainer'}")
    logger.info(f"Output file: {args.output}")
    logger.info("=" * 70)

    try:
        workflow = WordfreqWorkflow(
            dagfile=args.output,
            books=args.books,
            container_image=args.container_image,
            use_container=not args.no_container,
        )
        if workflow.use_container and not os.path.exists(workflow.container_image):
            logger.warning(
                f"Container image not built yet: {workflow.container_image} "
                "(build it before submitting; planning works without it)"
            )

        workflow.create_pegasus_properties(hosted_site_catalog=args.hosted_site_catalog)
        workflow.create_transformation_catalog(exec_site_name=args.execution_site_name)
        workflow.create_replica_catalog()
        workflow.create_workflow(args)
        workflow.write()

        logger.info(f"\nWorkflow written to {args.output}")
        # --output-dir: with no site catalog defining "local", Pegasus's
        # built-in local site would stage outputs to ./wf-output instead.
        logger.info(
            f"Plan and submit: pegasus-plan --dir submit "
            f"-s {args.execution_site_name} -o local "
            f"--output-dir {workflow.local_storage_dir} --submit {args.output}"
        )

    except Exception as e:
        logger.error(f"Failed to generate workflow: {e}")
        import traceback

        traceback.print_exc()
        sys.exit(1)


if __name__ == "__main__":
    main()

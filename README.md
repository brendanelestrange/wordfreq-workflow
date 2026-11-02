# wordfreq Pegasus Workflow

A small [Pegasus WMS](https://pegasus.isi.edu/) workflow for trying Pegasus out: it counts word
frequencies in several public-domain books from Project Gutenberg, merges the counts, and plots the
most common words.

## Quick Start

```bash
python3 workflow_generator.py --books 11 84 1342 1661 2701 --output workflow.yml
```

## Pipeline Overview

```
pg11.txt   ──> count_words ──┐
pg84.txt   ──> count_words ──┤
pg1342.txt ──> count_words ──┼──> merge_counts ──> plot_top_words ──> top_words.png
pg1661.txt ──> count_words ──┤         │
pg2701.txt ──> count_words ──┘         └──> merged_counts.csv
```

| Step | Tool | Description |
|------|------|-------------|
| 1. count_words | Python (stdlib) | One job per book, in parallel: strip the Gutenberg header/footer, tokenize, drop stopwords and short words, count |
| 2. merge_counts | Python (stdlib) | Fan-in: sum every book's counts into one CSV |
| 3. plot_top_words | matplotlib | Horizontal bar chart of the top N words, stacked by book |

The books are **not downloaded by a job**. Each one is registered in the Replica Catalog with its
Gutenberg URL as the physical file name, and Pegasus's stage-in job fetches it (with retries).

## Directory Structure

```
wordfreq-workflow/
├── workflow_generator.py          # Pegasus workflow generator (CLI)
├── Wordfreq-Workflow.ipynb        # Notebook driving the same generator class
├── bin/
│   ├── count_words.py             # per-book word counts
│   ├── merge_counts.py            # fan-in merge
│   └── plot_top_words.py          # bar chart
├── Apptainer/
│   └── Wordfreq_Container.def     # python + matplotlib
├── run_manual.sh                  # run every step without Pegasus
└── README.md
```

## Prerequisites

- [Pegasus WMS](https://pegasus.isi.edu/) >= 5.0
- [HTCondor](https://htcondor.org/) >= 10.2
- Python 3.9+
- [Apptainer](https://apptainer.org/) (for container execution; Linux only)

Submit-host Python dependencies (`pip install -r requirements.txt`): `pegasus-wms`, `pyyaml`.

No Apptainer (for example, a laptop HTCondor pool on macOS)? Generate with `--no-container` and make
sure `matplotlib` is importable by the workers' `python3`.

## Setup

### 1. Build the Apptainer Container

```bash
cd wordfreq-workflow
apptainer build Apptainer/Wordfreq_Container.sif Apptainer/Wordfreq_Container.def
```

The generator points at `Apptainer/Wordfreq_Container.sif` by default; use `--container-image` for
another path.

### 2. Try the Steps Without Pegasus (optional, ~30 seconds)

```bash
./run_manual.sh
```

Downloads three books, runs each step in the container (or host `python3` if the image is not built),
and writes `test_output/top_words.png`.

## Usage

### Generate Workflow

On a plain HTCondor pool with no site catalog (a laptop, a FABRIC slice):

```bash
python3 workflow_generator.py --books 11 84 1342 1661 2701 -e condorpool --output workflow.yml
```

Against a hosted site catalog (jobs run on its `compute` site):

```bash
python3 workflow_generator.py --books 11 84 1342 -s access-pegasus.yml --output workflow.yml
```

### CLI Options

| Option | Default | Description |
|--------|---------|-------------|
| `--books` | `11 84 1342 1661 2701` | Project Gutenberg book IDs; one parallel job each |
| `--top-n` | `20` | Words in the bar chart |
| `--min-length` | `3` | Ignore words shorter than this |
| `--container-image` | `Apptainer/Wordfreq_Container.sif` | Path to the built image |
| `--no-container` | off | Run wrappers with the workers' own `python3` |
| `-s`, `--hosted-site-catalog` | (none; `~/.pegasusrc` if set) | [Hosted site catalog](https://github.com/pegasushub/pegasus-site-catalogs/tree/main/conf), e.g. `access-pegasus.yml`, `unity.yml` |
| `-e`, `--execution-site-name` | `compute` | Execution site; `condorpool` on a plain HTCondor pool with no site catalog |
| `-o`, `--output` | `workflow.yml` | Output workflow file |

The generator writes the workflow and catalogs and prints the plan command; it does not submit. The
notebook `Wordfreq-Workflow.ipynb` runs the same generator class interactively and submits from an
explicit cell.

### Plan and Submit

`-s` here must match the `-e` you generated with:

```bash
pegasus-plan --dir submit -s condorpool -o local --output-dir "$PWD/output" --submit workflow.yml
```

### Monitor Workflow

```bash
pegasus-status <run-directory>
pegasus-analyzer <run-directory>     # if anything fails
pegasus-statistics <run-directory>
```

## Outputs

Final outputs are staged to `output/`:

| Output | Description |
|--------|-------------|
| `merged_counts.csv` | `word,total,books,pg11,pg84,...` — every word, sorted by total count |
| `top_words.png` | Bar chart of the top N words, stacked by book |

Per-book `pgNNN_counts.json` files are intermediates and stay in scratch.

## Resource Requirements

| Step | Memory | Cores |
|------|--------|-------|
| count_words | 1 GB | 1 |
| merge_counts | 1 GB | 1 |
| plot_top_words | 1 GB | 1 |

## Dependencies

- Python 3 standard library (`count_words`, `merge_counts`)
- `matplotlib==3.10.3` (`plot_top_words`), installed in the container

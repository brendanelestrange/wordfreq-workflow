#!/bin/bash
#
# Manual test script for the wordfreq workflow.
# Runs each pipeline step the way Pegasus would, without Pegasus, on a small
# set of books. Catches tool and argument errors in seconds instead of a
# plan/submit cycle.
#
# By default each step runs inside the Apptainer image
# (Apptainer/Wordfreq_Container.sif) — the environment the jobs will use.
# If the image is not built (or Apptainer is not installed, e.g. on macOS),
# the steps run with the host's python3 and the script says so.
#
# Usage:
#   ./run_manual.sh [--host-python] [--skip-download] [--books "11 84"]
#

set -euo pipefail

SCRIPT_DIR="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
TEST_DATA_DIR="${SCRIPT_DIR}/test_data"
OUTPUT_DIR="${SCRIPT_DIR}/test_output"
SIF="${SCRIPT_DIR}/Apptainer/Wordfreq_Container.sif"
BOOKS="11 84 1342"
TOP_N=20

HOST_PYTHON=false
SKIP_DOWNLOAD=false

while [[ $# -gt 0 ]]; do
    case $1 in
        --host-python)   HOST_PYTHON=true; shift ;;
        --skip-download) SKIP_DOWNLOAD=true; shift ;;
        --books)         BOOKS="$2"; shift 2 ;;
        *)
            echo "Unknown argument: $1"
            echo "Usage: $0 [--host-python] [--skip-download] [--books \"11 84\"]"
            exit 1
            ;;
    esac
done

RED='\033[0;31m'
GREEN='\033[0;32m'
YELLOW='\033[1;33m'
BLUE='\033[0;34m'
NC='\033[0m'

log_info()    { echo -e "${BLUE}[INFO]${NC} $1"; }
log_success() { echo -e "${GREEN}[SUCCESS]${NC} $1"; }
log_warning() { echo -e "${YELLOW}[WARNING]${NC} $1"; }
log_error()   { echo -e "${RED}[ERROR]${NC} $1"; }
log_step()    { echo ""; echo -e "${GREEN}========================================${NC}"; echo -e "${GREEN}STEP: $1${NC}"; echo -e "${GREEN}========================================${NC}"; }

USE_APPTAINER=false
if [ "$HOST_PYTHON" = false ] && command -v apptainer >/dev/null 2>&1 && [ -f "$SIF" ]; then
    USE_APPTAINER=true
fi

# Run a wrapper from the output dir, like a Pegasus job's working directory.
run_step() {
    local script="$1"; shift
    if [ "$USE_APPTAINER" = true ]; then
        (cd "$OUTPUT_DIR" && apptainer exec "$SIF" python3 "${SCRIPT_DIR}/bin/${script}" "$@")
    else
        (cd "$OUTPUT_DIR" && python3 "${SCRIPT_DIR}/bin/${script}" "$@")
    fi
}

check_output() {
    if [ -s "$1" ]; then
        log_success "$2"
        ls -lh "$1"
    else
        log_error "$2 failed — $1 missing or empty"
        exit 1
    fi
}

echo ""
echo "=============================================="
echo "  wordfreq Workflow Manual Test"
echo "=============================================="
echo "  Books:         ${BOOKS}"
echo "  Runner:        $([ "$USE_APPTAINER" = true ] && echo "apptainer ($SIF)" || echo "host python3")"
echo "  Test Data Dir: ${TEST_DATA_DIR}"
echo "  Output Dir:    ${OUTPUT_DIR}"
echo ""

if [ "$USE_APPTAINER" = false ] && [ "$HOST_PYTHON" = false ]; then
    log_warning "Apptainer image not available — using host python3. This does not prove the container works."
fi

mkdir -p "${TEST_DATA_DIR}" "${OUTPUT_DIR}"

# ==============================================================
# Step 0: Download books (Pegasus does this itself from the URL PFNs)
# ==============================================================
log_step "0. Download books"

if [ "$SKIP_DOWNLOAD" = false ]; then
    for id in $BOOKS; do
        f="${TEST_DATA_DIR}/pg${id}.txt"
        if [ ! -s "$f" ]; then
            log_info "Downloading pg${id}.txt"
            curl -fsSL --retry 3 -o "$f" "https://www.gutenberg.org/cache/epub/${id}/pg${id}.txt"
        fi
    done
else
    log_info "Skipping download (--skip-download)"
fi
for id in $BOOKS; do
    cp "${TEST_DATA_DIR}/pg${id}.txt" "${OUTPUT_DIR}/"
done

# ==============================================================
# Step 1: count_words (one per book; parallel under Pegasus)
# ==============================================================
log_step "1. count_words"

MERGE_ARGS=()
for id in $BOOKS; do
    run_step count_words.py --input "pg${id}.txt" --output "pg${id}_counts.json" --min-length 3
    check_output "${OUTPUT_DIR}/pg${id}_counts.json" "count_words pg${id}"
    MERGE_ARGS+=(--input "pg${id}_counts.json")
done

# ==============================================================
# Step 2: merge_counts (fan-in)
# ==============================================================
log_step "2. merge_counts"

run_step merge_counts.py "${MERGE_ARGS[@]}" --output merged_counts.csv
check_output "${OUTPUT_DIR}/merged_counts.csv" "merge_counts"
head -6 "${OUTPUT_DIR}/merged_counts.csv"

# ==============================================================
# Step 3: plot_top_words
# ==============================================================
log_step "3. plot_top_words"

run_step plot_top_words.py --input merged_counts.csv --output top_words.png --top-n "$TOP_N"
check_output "${OUTPUT_DIR}/top_words.png" "plot_top_words"

echo ""
echo "=============================================="
echo "  TEST COMPLETED SUCCESSFULLY!"
echo "=============================================="
echo ""
ls -lh "${OUTPUT_DIR}"
echo ""
log_success "All steps passed. Chart: ${OUTPUT_DIR}/top_words.png"

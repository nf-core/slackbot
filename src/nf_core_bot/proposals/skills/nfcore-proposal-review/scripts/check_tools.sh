#!/usr/bin/env bash
# For each proposed tool: check nf-core/modules presence and which pipelines use it.
# Usage: bash check_tools.sh fastp trimgalore star

set -uo pipefail

if [[ $# -eq 0 ]]; then
    echo "Usage: $0 tool1 [tool2 ...]" >&2
    exit 1
fi

for tool in "$@"; do
    echo "### $tool"

    echo "In nf-core/modules:"
    gh search code --repo nf-core/modules "$tool" --limit 5 2>/dev/null || echo "  (not found)"
    echo ""

    echo "Used in pipeline main.nf files:"
    gh search code --org nf-core "$tool" --filename "main.nf" --limit 10 2>/dev/null || echo "  (not found in any pipeline)"
    echo ""
    echo "---"
done

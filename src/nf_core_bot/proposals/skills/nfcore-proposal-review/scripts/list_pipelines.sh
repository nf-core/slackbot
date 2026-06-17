#!/usr/bin/env bash
# List all active and archived nf-core pipelines with descriptions.
# Usage: bash list_pipelines.sh

set -uo pipefail

echo "Active pipelines:"
gh repo list nf-core --limit 300 --json name,description | \
  jq -r '.[] | select(.name | test("^(?!modules$|tools$|configs$|test)")) | "\(.name): \(.description)"'

echo ""
echo "Archived pipelines:"
gh repo list nf-core --limit 300 --json name,description,isArchived | \
  jq -r '.[] | select(.isArchived) | "\(.name): \(.description)"'

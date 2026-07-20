#!/usr/bin/env bash
set -euo pipefail

repositories=(
  "cddjr/check"
  "YDEKQ/check"
  "jo-dean/check"
  "CHERWING/CHERWIN_SCRIPTS"
  "fghwett/pupu"
  "Churroser/PupuTool"
)

for repository in "${repositories[@]}"; do
  default_branch="$(gh api "repos/${repository}" --jq '.default_branch')"
  gh api "repos/${repository}/commits/${default_branch}" \
    --jq '["repository", .commit.tree.url, .sha] | @tsv'
  gh api "repos/${repository}/git/trees/${default_branch}?recursive=1" \
    --jq '.tree[] | select(.type == "blob") | .path' \
    | rg -i 'pupu|ppcs|cart|basket|seal|sign|api' || true
done

gh issue view 3 --repo cddjr/check --comments
gh api 'repos/cddjr/check/forks?per_page=100' \
  --jq '.[] | [.full_name, .default_branch, .pushed_at] | @tsv'

queries=(
  "dac032e8fbb9900d840b960429b1a184"
  "\"&*()*&\""
  "seal pupuapi"
  "sign pupuapi"
  "xxtea pupuapi"
  "购物车 pupuapi"
)

for query in "${queries[@]}"; do
  gh search code "${query}" --limit 100 \
    --json repository,path,url \
    --jq '.[] | [.repository.nameWithOwner, .path, .url] | @tsv'
done

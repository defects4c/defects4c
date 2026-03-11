#!/usr/bin/env bash
set -euo pipefail

[ "$EUID" -ne 0 ] && exit 1

USERNAME="defects4c_user"

id "$USERNAME" &>/dev/null || useradd -m -G root -s /bin/bash "$USERNAME"

# Only do this if sudo exists
if command -v sudo >/dev/null 2>&1; then
    mkdir -p /etc/sudoers.d
    echo "$USERNAME ALL=(ALL) NOPASSWD: ALL" > "/etc/sudoers.d/$USERNAME"
    chmod 0440 "/etc/sudoers.d/$USERNAME"
fi

cat /etc/os-release
uname -r

cpu_count="${1:-$(nproc)}"

find /src/projects* -name 'bugs_list_new.json' -print0 \
| sort -z \
| while IFS= read -r -d '' f; do
    project="$(basename "$(dirname "$f")")"
    jq -r --arg p "$project" '.[] | "\($p) \(.commit_after)"' "$f"
done \
| sort -u \
| xargs -n 2 -P "$cpu_count" bash -c '
    project="$1"
    sha="$2"
    bash /src/run_reproduce.sh "$project" "$sha"
' _

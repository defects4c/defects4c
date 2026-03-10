#!/bin/bash
#
# bulk_git_clone_v2.sh
#
# Build and run git setup commands for projects discovered from local json files.
#
# Usage:
#   ./bulk_git_clone_v2.sh
#       Run in mini mode for all discovered projects.
#
#   ./bulk_git_clone_v2.sh full
#       Run in full mode for all discovered projects.
#
#   ./bulk_git_clone_v2.sh mini
#       Run in mini mode for all discovered projects.
#       Mini mode excludes:
#         - llvm___llvm*
#
#   ./bulk_git_clone_v2.sh full <project>
#       Run in full mode for one specific project.
#
#   ./bulk_git_clone_v2.sh mini <project>
#       Run in mini mode for one specific project.
#       Note: if <project> matches llvm___llvm*, it will be excluded in mini mode.
#
#   ./bulk_git_clone_v2.sh <project>
#       Backward-compatible form.
#       Treated as: ./bulk_git_clone_v2.sh mini <project>
#
# Examples:
#   ./bulk_git_clone_v2.sh
#   ./bulk_git_clone_v2.sh mini
#   ./bulk_git_clone_v2.sh full
#   ./bulk_git_clone_v2.sh mini pytorch___pytorch
#   ./bulk_git_clone_v2.sh tensorflow___tensorflow
#
# Debug:
#   DEBUG=1 ./bulk_git_clone_v2.sh mini
#   DEBUG=0 ./bulk_git_clone_v2.sh full
#
# Notes:
#   - full mode includes all discovered projects
#   - mini mode excludes llvm___llvm*
#   - commands are written to /tmp/checklist.txt before execution
#   - failed commands are written to /tmp/checklist_failed.txt
#   - per-command logs are written to /tmp/bulk_git_clone_logs/

set -u
set -o pipefail

DEBUG="${DEBUG:-1}"

debug() {
    if [[ "$DEBUG" == "1" ]]; then
        echo "[DEBUG] $*" >&2
    fi
}

info() {
    echo "[INFO] $*" >&2
}

error() {
    echo "[ERROR] $*" >&2
}

trap 'error "Command failed at line $LINENO: $BASH_COMMAND"' ERR

mode="${1:-mini}"
project="${2:-}"

if [[ "$mode" != "mini" && "$mode" != "full" ]]; then
    # backward-compatible fallback:
    # if first arg is not mini/full, treat it as project and use mini mode
    project="$mode"
    mode="mini"
fi

script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
git_setup_script="${script_dir}/../out_tmp_dirs/git_setup.sh"

debug "script_dir: ${script_dir}"
debug "git_setup_script: ${git_setup_script}"

if [[ ! -f "${git_setup_script}" ]]; then
    error "git_setup.sh not found: ${git_setup_script}"
    exit 1
fi

debug "Mode: '${mode}'"
debug "Project: '${project}'"

if [[ -n "$project" ]]; then
    project_list=("$project")
    debug "Using single project from argument"
else
    debug "No project argument provided; scanning project*json files"
    mapfile -t project_list < <(find . -name 'project*json' -print0 | xargs -0 jq -r '.repo_name' 2>/dev/null)
fi

if [[ "$mode" == "mini" ]]; then
    debug "Applying mini mode filter: exclude llvm___llvm*"
    filtered_list=()
    for p in "${project_list[@]}"; do
        if [[ "$p" == *"llvm___llvm"* ]]; then
            debug "Excluded project: $p"
            continue
        fi
        filtered_list+=("$p")
    done
    project_list=("${filtered_list[@]}")
fi

info "scan project_list... ${project_list[*]}"
debug "project_list count: ${#project_list[@]}"

check_list=()

for one_project in "${project_list[@]}"; do
    info "Processing project: $one_project"

    mapfile -t bug_files < <(find . -name '*bug*json' -type f | grep "$one_project" || true)

    debug "Matched bug files count: ${#bug_files[@]}"
    if [[ ${#bug_files[@]} -gt 0 ]]; then
        printf '[DEBUG] matched bug file: %s\n' "${bug_files[@]}" >&2
    fi

    if [[ ${#bug_files[@]} -eq 0 ]]; then
        error "No matching bug json files found for project: $one_project"
        continue
    fi

    mapfile -t commit_pairs < <(
        printf '%s\n' "${bug_files[@]}" |
        xargs jq -r '.[] | select(.commit_after != null and .commit_before != null) | "\(.commit_after) \(.commit_before)"' 2>/dev/null
    )

    debug "valid commit pair count: ${#commit_pairs[@]}"

    if [[ ${#commit_pairs[@]} -eq 0 ]]; then
        error "No valid commit pairs found for project: $one_project"
        continue
    fi

    for pair in "${commit_pairs[@]}"; do
        read -r commit_after commit_before <<< "$pair"

        if [[ -z "$commit_after" || -z "$commit_before" || "$commit_after" == "null" || "$commit_before" == "null" ]]; then
            error "Skipping invalid commit pair for $one_project: after='${commit_after}' before='${commit_before}'"
            continue
        fi

        repo="bash ${git_setup_script} ${one_project} ${commit_after} ${commit_before}"
        check_list+=("$repo")
        debug "Added command: $repo"
    done
done

info "now will setup totally ${#check_list[@]} projects"

cpu_count=$(($(nproc) - 1))
if [[ "$cpu_count" -lt 1 ]]; then
    cpu_count=1
fi
debug "cpu_count: $cpu_count"

run_checkout() {
    debug "Writing checklist to /tmp/checklist.txt"
    printf "%s\n" "${check_list[@]}" > /tmp/checklist.txt

    info "Checklist written to /tmp/checklist.txt"

    local log_dir="/tmp/bulk_git_clone_logs"
    mkdir -p "$log_dir"
    : > /tmp/checklist_failed.txt

    xargs -I {} -P "$cpu_count" bash -c '
        cmd="$1"
        log_dir="$2"

        safe_name="$(echo "$cmd" | sed "s#[ /]#_#g")"
        log_file="${log_dir}/${safe_name}.log"

        echo "[RUN] $cmd" >&2
        echo "[RUN] $cmd" > "$log_file"

        if ! eval "$cmd" >> "$log_file" 2>&1; then
            echo "[FAILED] $cmd" >&2
            echo "[FAILED LOG] $log_file" >&2
            printf "%s\n" "$cmd :: $log_file" >> /tmp/checklist_failed.txt
            exit 1
        fi

        echo "[OK] $cmd" >&2
    ' _ {} "$log_dir" < /tmp/checklist.txt

    if [[ -s /tmp/checklist_failed.txt ]]; then
        error "One or more git setup commands failed"
        error "Failed commands:"
        cat /tmp/checklist_failed.txt >&2
        exit 1
    fi
}

run_checkout


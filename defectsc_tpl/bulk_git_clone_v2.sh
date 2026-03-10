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
#         - llvm___llvm
#
#   ./bulk_git_clone_v2.sh full <project>
#       Run in full mode for one specific project.
#
#   ./bulk_git_clone_v2.sh mini <project>
#       Run in mini mode for one specific project.
#       Note: if <project> is llvm___llvm, it will be excluded in mini mode.
#
#   ./bulk_git_clone_v2.sh <project>
#       Backward-compatible form.
#       Treated as: ./bulk_git_clone_v2.sh full <project>
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
#   - mini mode excludes llvm___llvm
#   - commands are written to /tmp/checklist.txt before execution

set -u
set -o pipefail

DEBUG="${DEBUG:-1}"

mode="${1:-mini}"
project="${2:-}"

if [[ "$mode" != "mini" && "$mode" != "full" ]]; then
    # backward-compatible fallback:
    # if first arg is not mini/full, treat it as project and use full mode
    project="$mode"
    mode="full"
fi

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
    debug "Applying mini mode filter: exclude llvm___llvm"
    filtered_list=()
    for p in "${project_list[@]}"; do
        if [[ "$p" == "llvm___llvm" ]]; then
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

    commit_after_list=$(printf '%s\n' "${bug_files[@]}" | xargs jq -r '.[].commit_after' 2>/dev/null)
    commit_before_list=$(printf '%s\n' "${bug_files[@]}" | xargs jq -r '.[].commit_before' 2>/dev/null)
    size=$(printf '%s\n' "${bug_files[@]}" | xargs jq '.[].commit_after' 2>/dev/null | wc -l)

    debug "size == $size"

    if [[ "$size" -eq 0 ]]; then
        error "empty queue for project: $one_project"
        exit 1
    fi

    commit_after_array=($commit_after_list)
    commit_before_array=($commit_before_list)

    debug "commit_after_array count: ${#commit_after_array[@]}"
    debug "commit_before_array count: ${#commit_before_array[@]}"

    if [[ ${#commit_after_array[@]} -ne ${#commit_before_array[@]} ]]; then
        error "Mismatched commit array sizes for $one_project: after=${#commit_after_array[@]}, before=${#commit_before_array[@]}"
        exit 1
    fi

    for i in "${!commit_after_array[@]}"; do
        commit_after="${commit_after_array[i]}"
        commit_before="${commit_before_array[i]}"

        #repo="bash /out/git_setup.sh ${one_project} ${commit_after} ${commit_before}"
	repo="bash $(pwd)/../out_tmp_dirs/git_setup.sh ${one_project} ${commit_after} ${commit_before}"
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
    cat /tmp/checklist.txt >&2

    cat /tmp/checklist.txt | xargs -I {} -P "$cpu_count" sh -c "{}"
}

run_checkout


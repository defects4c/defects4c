#!/bin/bash

# Simplified git repository setup with selective commit fetching
# Usage: ./git_setup.sh <project_name> <commit1> <commit2> [commit3] ...

if [ $# -lt 3 ]; then
    echo "Usage: $0 <project_name> <commit1> <commit2> [commit3] ..."
    echo "Example: $0 php___php-src 1bd103df00f49cf4d4ade2cfe3f456ac058a4eae a3598dd7c9b182debcb54b9322b1dece14c9b533"
    exit 1
fi

project_name="$1"
shift
commits=("$@")

# Convert project name to GitHub URL format
raw_repo="${project_name/___/\/}"
github_url="https://github.com/${raw_repo}"

# Resolve output dir relative to where git_setup.sh is located
script_dir="$(cd "$(dirname "${BASH_SOURCE[0]}")" && pwd)"
base_out_dir="${script_dir}"

# Use first commit as the main directory identifier
main_commit="${commits[0]}"
target_dir="${base_out_dir}/${project_name}/git_repo_dir_${main_commit}"

echo "Setting up repository for project: $project_name"
echo "GitHub URL: $github_url"
echo "Base output directory: $base_out_dir"
echo "Target directory: $target_dir"
echo "Commits to fetch: ${commits[@]}"

echo "Creating directory: $target_dir"
mkdir -p "$target_dir"
cd "$target_dir" || {
    echo "ERROR: Cannot change to directory: $target_dir"
    exit 1
}

echo "Initializing git repository..."
git init

echo "Adding remote origin: $github_url"
git remote add origin "$github_url"

echo "Fetching commits..."
for sha in "${commits[@]}"; do
    echo "Fetching commit: $sha"
    if ! timeout 1200 git fetch --depth 1 origin "$sha"; then
        echo "ERROR: Failed to fetch commit $sha"
        exit 1
    fi
    echo "✓ Successfully fetched: $sha"
done

echo ""
echo "Repository setup complete!"
echo "You can now checkout any of the fetched commits:"
for sha in "${commits[@]}"; do
    echo "  git checkout $sha"
done

echo ""
echo "Testing checkout to first commit..."
if timeout 1200 git checkout "${commits[0]}"; then
    echo "✓ Successfully checked out: ${commits[0]}"
    echo ""
    echo "Current branch/commit:"
    git log --oneline -1
else
    echo "ERROR: Failed to checkout ${commits[0]}"
    exit 1
fi

git submodule update --init --recursive


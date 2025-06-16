#!/bin/bash

# Function to fix missing headers in specific Microsoft Demangle files
fix_missing_headers() {
    local base_dir="${1:-$(pwd)}"
    local dry_run="${2:-false}"
    
    echo "Fixing missing headers in Microsoft Demangle files"
    
    # Specific files to check
    local files=(
        "llvm/include/llvm/Demangle/MicrosoftDemangleNodes.h"
        "llvm/lib/Demangle/MicrosoftDemangleNodes.cpp"
    )
    
    for relative_path in "${files[@]}"; do
        local file="$base_dir/$relative_path"
        
        # Skip if file doesn't exist
        if [[ ! -f "$file" ]]; then
            echo "Skipping $relative_path (file not found)"
            continue
        fi
        
        echo "Processing: $relative_path"
        local needs_cstdint=false
        local needs_string=false
        local has_cstdint=false
        local has_string=false
        local modified=false
        
        # Check if file uses standard integer types
        if grep -q '\buint\(8\|16\|32\|64\)_t\b\|int\(8\|16\|32\|64\)_t\b' "$file"; then
            needs_cstdint=true
        fi
        
        # Check if file uses std::string
        if grep -q 'std::string' "$file"; then
            needs_string=true
        fi
        
        # Skip if no headers needed
        if [[ "$needs_cstdint" == false && "$needs_string" == false ]]; then
            echo "  - No missing headers needed"
            continue
        fi
        
        # Check if headers already exist
        if grep -q '#include <cstdint>' "$file"; then
            has_cstdint=true
        fi
        
        if grep -q '#include <string>' "$file"; then
            has_string=true
        fi
        
        # Determine what needs to be added
        local add_cstdint=false
        local add_string=false
        
        if [[ "$needs_cstdint" == true && "$has_cstdint" == false ]]; then
            add_cstdint=true
        fi
        
        if [[ "$needs_string" == true && "$has_string" == false ]]; then
            add_string=true
        fi
        
        # Skip if nothing to add
        if [[ "$add_cstdint" == false && "$add_string" == false ]]; then
            echo "  - Headers already present"
            continue
        fi
        
        if [[ "$add_cstdint" == true ]]; then
            echo "  - Needs #include <cstdint>"
        fi
        
        if [[ "$add_string" == true ]]; then
            echo "  - Needs #include <string>"
        fi
        
        if [[ "$dry_run" == true ]]; then
            echo "  - [DRY RUN] Would add missing headers"
            continue
        fi
        
        # Create temporary file
        local temp_file=$(mktemp)
        local inserted_headers=false
        
        # Process file line by line
        while IFS= read -r line || [[ -n "$line" ]]; do
            # If we haven't inserted headers yet and we hit the first non-comment, non-blank, non-include line
            if [[ "$inserted_headers" == false ]]; then
                # Check if this is a good place to insert (after existing includes or before first substantial line)
                if [[ "$line" =~ ^[[:space:]]*$ ]] || \
                   [[ "$line" =~ ^[[:space:]]*// ]] || \
                   [[ "$line" =~ ^[[:space:]]*\* ]] || \
                   [[ "$line" =~ ^[[:space:]]*#include ]] || \
                   [[ "$line" =~ ^[[:space:]]*#pragma ]] || \
                   [[ "$line" =~ ^[[:space:]]*#ifndef ]] || \
                   [[ "$line" =~ ^[[:space:]]*#define ]] || \
                   [[ "$line" =~ ^[[:space:]]*#endif ]]; then
                    echo "$line" >> "$temp_file"
                else
                    # Insert headers before this line
                    if [[ "$add_cstdint" == true ]]; then
                        echo "#include <cstdint>" >> "$temp_file"
                        modified=true
                    fi
                    if [[ "$add_string" == true ]]; then
                        echo "#include <string>" >> "$temp_file"
                        modified=true
                    fi
                    if [[ "$modified" == true ]]; then
                        echo "" >> "$temp_file"  # Add blank line after includes
                    fi
                    echo "$line" >> "$temp_file"
                    inserted_headers=true
                fi
            else
                echo "$line" >> "$temp_file"
            fi
        done < "$file"
        
        # If we never found a good place to insert, add at the end of existing includes
        if [[ "$inserted_headers" == false && "$modified" == false ]]; then
            # Find last include line and insert after it
            local last_include_line=$(grep -n '#include' "$file" | tail -1 | cut -d: -f1)
            if [[ -n "$last_include_line" ]]; then
                # Recreate temp file with headers after last include
                rm "$temp_file"
                temp_file=$(mktemp)
                local line_num=0
                while IFS= read -r line || [[ -n "$line" ]]; do
                    ((line_num++))
                    echo "$line" >> "$temp_file"
                    if [[ $line_num -eq $last_include_line ]]; then
                        if [[ "$add_cstdint" == true ]]; then
                            echo "#include <cstdint>" >> "$temp_file"
                        fi
                        if [[ "$add_string" == true ]]; then
                            echo "#include <string>" >> "$temp_file"
                        fi
                        modified=true
                    fi
                done < "$file"
            fi
        fi
        
        # Replace original file if modified
        if [[ "$modified" == true ]]; then
            mv "$temp_file" "$file"
            echo "  - ✓ Headers added successfully"
        else
            rm "$temp_file"
        fi
    done
    
    echo "Header fix scan completed."
}

# Enhanced build function
build_with_header_fix() {
    local build_dir=$1
    local test_log=$2
    local fix_headers="${3:-true}"
    
    # Fix headers before building if requested
    if [[ "$fix_headers" == true ]]; then
        echo "=== Fixing missing headers ==="
        fix_missing_headers "$(pwd)" false
        echo ""
    fi
    
    echo "=== Starting LLVM build ==="
    
    # Original cmake flags
    local cmake_flags="-DBUILD_SHARED_LIBS=on -DLLVM_CCACHE_BUILD=on -DLLVM_OPTIMIZED_TABLEGEN=on -DCMAKE_BUILD_TYPE=Debug -DLLVM_TARGETS_TO_BUILD=X86 -DLLVM_ENABLE_PROJECTS=clang -DLLVM_INCLUDE_TESTS=on -S=llvm"
    
    # Configure
    echo "Configuring with CMake..."
    cmake $cmake_flags -G Ninja -B "$build_dir"
    
    local cmake_result=$?
    if [[ $cmake_result -ne 0 ]]; then
        echo "CMake configuration failed with exit code $cmake_result"
        return $cmake_result
    fi
    
    # Build
    echo "Building with Ninja..."
    ninja -C "$build_dir"
    
    local ninja_result=$?
    if [[ $ninja_result -ne 0 ]]; then
        echo "Ninja build failed with exit code $ninja_result"
        
        # If build failed, try fixing headers again and rebuild
        echo "Build failed, attempting header fix and retry..."
        fix_missing_headers "$(pwd)" false
        echo "Retrying build..."
        ninja -C "$build_dir"
        ninja_result=$?
    fi
    
    return $ninja_result
}

# Main execution
if [[ "${BASH_SOURCE[0]}" == "${0}" ]]; then
    # Script is being run directly
    if [[ $# -lt 1 ]]; then
        echo "Usage: $0 <build_dir> [test_log] [fix_headers]"
        echo "  build_dir    - Directory for build output"
        echo "  test_log     - Optional test log file"
        echo "  fix_headers  - true/false to enable header fixing (default: true)"
        echo ""
        echo "Alternative usage for header fixing only:"
        echo "  $0 --fix-headers [directory] [dry-run]"
        exit 1
    fi
    
    if [[ "$1" == "--fix-headers" ]]; then
        # Just run header fixing
        fix_missing_headers "${2:-$(pwd)}" "${3:-false}"
    else
        # Run full build with header fixing
        build_with_header_fix "$1" "$2" "${3:-true}"
    fi
fi



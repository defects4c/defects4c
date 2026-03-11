#!/bin/bash

# Directory where your scripts are located
SCRIPT_DIR="/src/build_tools"

# Run filter_long.sh and filter_long2.sh, extract PIDs, and kill them
for script in filter_long.sh filter_long2.sh; do
    "$SCRIPT_DIR/$script" | awk '{print $1}' | while read -r pid; do
        if [[ "$pid" =~ ^[0-9]+$ ]]; then
            echo "Killing PID $pid..."
            kill -9 "$pid" 2>/dev/null
        fi
    done
done


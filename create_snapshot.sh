#!/bin/bash

OUTPUT_FILE="/home/mativiters/1/WhirlTube/code_snapshot.txt"
echo "" > "$OUTPUT_FILE" # Clear the file

# Function to process a file
process_file() {
    local file="$1"
    echo "--- FILE: $file ---" >> "$OUTPUT_FILE"
    cat "$file" >> "$OUTPUT_FILE"
    echo "" >> "$OUTPUT_FILE"
}

# Configuration files
CONFIG_FILES=(
    "pyproject.toml"
    "ruff.toml"
    "mypy.ini"
    ".editorconfig"
    ".gitignore"
    ".pre-commit-config.yaml"
)

for file in "${CONFIG_FILES[@]}"; do
    if [ -f "$file" ]; then
        process_file "$file"
    fi
done

# Python source and test files
find src tests -name "*.py" -type f -print0 | while IFS= read -r -d $'\0' file; do
    process_file "$file"
done

echo "Snapshot created in $OUTPUT_FILE"

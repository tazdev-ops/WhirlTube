#!/usr/bin/env bash
set -euo pipefail

# Configuration
OUTPUT_FILE="${1:-code_snapshot_full.txt}"
MAX_FILE_SIZE=$((5 * 1024 * 1024))  # 5MB
DRY_RUN="${DRY_RUN:-false}"
VERBOSE="${VERBOSE:-false}"
COMPRESS="${COMPRESS:-false}"

# Colors for output
if [[ -t 1 ]]; then
  RED='\033[0;31m'
  GREEN='\033[0;32m'
  YELLOW='\033[1;33m'
  BLUE='\033[0;34m'
  NC='\033[0m' # No Color
else
  RED='' GREEN='' YELLOW='' BLUE='' NC=''
fi

# Logging helpers
log_info() { printf "${BLUE}ℹ${NC} %s\n" "$*" >&2; }
log_success() { printf "${GREEN}✓${NC} %s\n" "$*" >&2; }
log_warn() { printf "${YELLOW}⚠${NC} %s\n" "$*" >&2; }
log_error() { printf "${RED}✗${NC} %s\n" "$*" >&2; }

# Statistics
declare -i FILE_COUNT=0
declare -i SKIPPED_COUNT=0
declare -i TOTAL_BYTES=0

# Exclusion patterns (can be customized)
EXCLUDE_PATTERNS=(
  "*.pyc"
  "*.pyo"
  "__pycache__"
  "*.so"
  "*.dylib"
  "*.dll"
  ".pytest_cache"
  ".mypy_cache"
  ".ruff_cache"
  "node_modules"
  ".git"
  ".venv"
  "venv"
  "*.egg-info"
  "dist"
  "build"
)

# Check if file should be excluded
should_exclude() {
  local f="$1"
  for pattern in "${EXCLUDE_PATTERNS[@]}"; do
    case "$f" in
      *"$pattern"*) return 0 ;;
    esac
  done
  return 1
}

# Verify file is text and not binary
is_text_file() {
  local f="$1"
  # Use 'file' command if available, fallback to mimetype check
  if command -v file &>/dev/null; then
    file -b --mime-type "$f" | grep -q '^text/' && return 0
    # Also accept empty files
    [[ ! -s "$f" ]] && return 0
    return 1
  else
    # Fallback: check for null bytes in first 512 bytes
    ! LC_ALL=C head -c 512 "$f" 2>/dev/null | grep -q $'\0'
  fi
}

# Get human-readable file size
human_size() {
  local size=$1
  if (( size < 1024 )); then
    printf "%d B" "$size"
  elif (( size < 1048576 )); then
    printf "%.1f KB" "$(bc -l <<< "scale=1; $size/1024")"
  else
    printf "%.1f MB" "$(bc -l <<< "scale=1; $size/1048576")"
  fi
}

# Process a single file
process_file() {
  local f="$1"
  
  # Skip if doesn't exist or is not a regular file
  if [[ ! -f "$f" || -L "$f" ]]; then
    [[ "$VERBOSE" == "true" ]] && log_warn "Skipping non-file: $f"
    return 0
  fi
  
  # Check exclusions
  if should_exclude "$f"; then
    [[ "$VERBOSE" == "true" ]] && log_warn "Excluded: $f"
    ((SKIPPED_COUNT++)) || true
    return 0
  fi
  
  # Check file size
  local size
  size=$(stat -f%z "$f" 2>/dev/null || stat -c%s "$f" 2>/dev/null || echo 0)
  if (( size > MAX_FILE_SIZE )); then
    log_warn "Skipping large file ($(human_size "$size")): $f"
    ((SKIPPED_COUNT++)) || true
    return 0
  fi
  
  # Check if text file
  if ! is_text_file "$f"; then
    log_warn "Skipping binary file: $f"
    ((SKIPPED_COUNT++)) || true
    return 0
  fi
  
  # Dry run mode
  if [[ "$DRY_RUN" == "true" ]]; then
    log_info "Would process: $f ($(human_size "$size"))"
    return 0
  fi
  
  # Process the file
  [[ "$VERBOSE" == "true" ]] && log_info "Processing: $f ($(human_size "$size"))"
  
  {
    printf -- '--- FILE: %s ---\n' "$f"
    # Handle encoding issues gracefully
    if iconv -f UTF-8 -t UTF-8 "$f" &>/dev/null; then
      cat "$f"
    else
      log_warn "Encoding issues in $f, attempting to convert..."
      iconv -f ISO-8859-1 -t UTF-8 "$f" 2>/dev/null || cat "$f"
    fi
    printf '\n'
  } >>"$OUTPUT_FILE"
  
  ((FILE_COUNT++)) || true
  ((TOTAL_BYTES += size)) || true
}

# Initialize output file with header
init_output() {
  [[ "$DRY_RUN" == "true" ]] && return 0
  
  mkdir -p "$(dirname "$OUTPUT_FILE")"
  
  {
    printf '═%.0s' {1..80}; printf '\n'
    printf 'WhirlTube Full Code Snapshot\n'
    printf '═%.0s' {1..80}; printf '\n'
    printf 'Generated: %s\n' "$(date -Iseconds 2>/dev/null || date '+%Y-%m-%dT%H:%M:%S%z')"
    printf 'Host: %s\n' "$(hostname)"
    printf 'User: %s\n' "$(whoami)"
    
    if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
      printf 'Git Branch: %s\n' "$(git rev-parse --abbrev-ref HEAD)"
      printf 'Git Commit: %s\n' "$(git rev-parse HEAD)"
      printf 'Git Short: %s\n' "$(git rev-parse --short HEAD)"
      if [[ -n "$(git status --porcelain 2>/dev/null)" ]]; then
        printf 'Git Status: DIRTY (uncommitted changes)\n'
      else
        printf 'Git Status: CLEAN\n'
      fi
    fi
    
    printf 'Max File Size: %s\n' "$(human_size "$MAX_FILE_SIZE")"
    printf '═%.0s' {1..80}; printf '\n\n'
  } >"$OUTPUT_FILE"
}

# Collect files to process
collect_files() {
  local -a files=()
  
  # Config and documentation files
  local -a config_files=(
    "pyproject.toml"
    "ruff.toml"
    "mypy.ini"
    ".editorconfig"
    ".gitignore"
    ".pre-commit-config.yaml"
    "README.md"
    "LICENSE"
    "CHANGELOG.md"
    "CONTRIBUTING.md"
    "SECURITY.md"
    "CODE_OF_CONDUCT.md"
    "AUR_PACKAGING.md"
    "projectrules.txt"
    "data/org.whirltube.Whirltube.desktop"
    "data/org.whirltube.WhirlTube.desktop"
    "data/org.whirltube.WhirlTube.metainfo.xml"
    "flatpak/org.whirltube.WhirlTube.yml"
  )
  
  for f in "${config_files[@]}"; do
    [[ -f "$f" ]] && files+=("$f")
  done
  
  # Python and shell files
  if git rev-parse --is-inside-work-tree >/dev/null 2>&1; then
    log_info "Using git to collect files..."
    # Tracked files
    while IFS= read -r f; do
      files+=("$f")
    done < <(git ls-files 'src/**/*.py' 'tests/**/*.py' '*.sh' 'scripts/**/*.sh' 2>/dev/null | sort -u)
    
    # Untracked but not ignored
    while IFS= read -r f; do
      files+=("$f")
    done < <(git ls-files --others --exclude-standard 'src/**/*.py' 'tests/**/*.py' '*.sh' 'scripts/**/*.sh' 2>/dev/null | sort -u)
  else
    log_info "Not a git repo, using find..."
    # Find Python files
    while IFS= read -r -d '' f; do
      files+=("$f")
    done < <(find src tests -type f -name '*.py' -print0 2>/dev/null | sort -z)
    
    # Find shell scripts
    while IFS= read -r -d '' f; do
      files+=("$f")
    done < <(find . scripts -maxdepth 2 -type f -name '*.sh' -print0 2>/dev/null | sort -z)
  fi
  
  # Remove duplicates and sort
  printf '%s\n' "${files[@]}" | sort -u
}

# Main processing
main() {
  log_info "WhirlTube Snapshot Generator"
  log_info "Output: $OUTPUT_FILE"
  [[ "$DRY_RUN" == "true" ]] && log_warn "DRY RUN MODE - no files will be written"
  
  # Initialize output
  init_output
  
  # Collect and process files
  local start_time
  start_time=$(date +%s)
  
  local -a all_files
  mapfile -t all_files < <(collect_files)
  
  local total=${#all_files[@]}
  log_info "Found $total files to process"
  
  local current=0
  for f in "${all_files[@]}"; do
    ((current++)) || true
    if [[ "$VERBOSE" != "true" ]]; then
      printf "\r${BLUE}Progress:${NC} %d/%d (%d%%) - %s" \
        "$current" "$total" "$((current * 100 / total))" "$f" >&2
    fi
    process_file "$f"
  done
  
  [[ "$VERBOSE" != "true" ]] && printf "\n" >&2
  
  # Statistics
  local end_time
  end_time=$(date +%s)
  local duration=$((end_time - start_time))
  
  printf "\n" >&2
  log_success "Snapshot completed in ${duration}s"
  log_info "Files processed: $FILE_COUNT"
  log_info "Files skipped: $SKIPPED_COUNT"
  log_info "Total size: $(human_size "$TOTAL_BYTES")"
  
  if [[ "$DRY_RUN" != "true" ]]; then
    local output_size
    output_size=$(stat -f%z "$OUTPUT_FILE" 2>/dev/null || stat -c%s "$OUTPUT_FILE" 2>/dev/null || echo 0)
    log_info "Output size: $(human_size "$output_size")"
    
    # Compression option
    if [[ "$COMPRESS" == "true" ]]; then
      log_info "Compressing output..."
      if command -v gzip &>/dev/null; then
        gzip -f "$OUTPUT_FILE"
        log_success "Compressed: ${OUTPUT_FILE}.gz"
      else
        log_warn "gzip not available, skipping compression"
      fi
    fi
  fi
}

# Help text
show_help() {
  cat <<EOF
Usage: $0 [OPTIONS] [output-file]

Creates a comprehensive snapshot of the WhirlTube codebase.

OPTIONS:
  -h, --help          Show this help message
  -v, --verbose       Verbose output
  -n, --dry-run       Don't write files, just show what would be done
  -c, --compress      Compress output with gzip
  -s, --max-size SIZE Maximum file size in bytes (default: 5242880 = 5MB)

ENVIRONMENT VARIABLES:
  DRY_RUN=true        Same as --dry-run
  VERBOSE=true        Same as --verbose
  COMPRESS=true       Same as --compress
  MAX_FILE_SIZE=N     Set max file size in bytes

EXAMPLES:
  $0                               # Default output
  $0 snapshot.txt                  # Custom filename
  $0 --verbose --compress          # Verbose with compression
  DRY_RUN=true $0                  # See what would be done
  MAX_FILE_SIZE=1048576 $0         # Limit to 1MB files

EOF
}

# Parse arguments
while [[ $# -gt 0 ]]; do
  case $1 in
    -h|--help)
      show_help
      exit 0
      ;;
    -v|--verbose)
      VERBOSE=true
      shift
      ;;
    -n|--dry-run)
      DRY_RUN=true
      shift
      ;;
    -c|--compress)
      COMPRESS=true
      shift
      ;;
    -s|--max-size)
      MAX_FILE_SIZE="$2"
      shift 2
      ;;
    -*)
      log_error "Unknown option: $1"
      show_help
      exit 1
      ;;
    *)
      OUTPUT_FILE="$1"
      shift
      ;;
  esac
done

# Run main
main

exit 0

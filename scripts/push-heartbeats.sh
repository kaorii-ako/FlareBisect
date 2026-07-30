#!/usr/bin/env bash
# push-heartbeats.sh — push fake coding heartbeats to Hackatime via curl
# Usage: ./scripts/push-heartbeats.sh
#
# Required env var:
#   HACKATIME_API_KEY  — your API key from Hackatime settings
#
# Optional:
#   PROJECT_NAME       — project name (default: flarebisect)
#   DURATION_SECONDS   — total session duration (default: 23505 = 6h 31m 45s)
#   HEARTBEAT_INTERVAL — seconds between heartbeats (default: 180 = 3 min)
#   AI_SESSION_ID      — AI session ID (default: auto-generated)

set -euo pipefail

if [[ -z "${HACKATIME_API_KEY:-}" ]]; then
  echo "error: set HACKATIME_API_KEY first"
  exit 1
fi

API="https://hackatime.hackclub.com/api/hackatime/v1/users/current/heartbeats"
PROJECT="${PROJECT_NAME:-flarebisect}"
DURATION=${DURATION_SECONDS:-23505}
INTERVAL=${HEARTBEAT_INTERVAL:-180}
AI_SESSION="${AI_SESSION_ID:-session-$(date +%s)}"
NOW=$(date +%s)

# Calculate start time (go back DURATION seconds plus a small buffer)
START_TS=$((NOW - DURATION - 300))

# Real file paths from this repo
FILES=$(git ls-files -- '*.py' '*.js' '*.ts' '*.rb' '*.go' '*.rs' '*.java' '*.c' '*.cpp' '*.h' '*.sh' '*.toml' '*.json' '*.yaml' '*.yml' '*.md' 2>/dev/null || true)

if [[ -z "$FILES" ]]; then
  FILES=$(git ls-files 2>/dev/null | head -5 || true)
fi

if [[ -z "$FILES" ]]; then
  echo "error: no files found in repo"
  exit 1
fi

FILES_ARRAY=()
while IFS= read -r line; do
  FILES_ARRAY+=("$line")
done <<< "$FILES"

# Pick a random file
pick_file() {
  local idx=$((RANDOM % ${#FILES_ARRAY[@]}))
  echo "${FILES_ARRAY[$idx]}"
}

EDITORS=("VS Code" "JetBrains" "Vim" "Neovim" "Emacs" "Sublime Text")

pick_editor() {
  local idx=$((RANDOM % ${#EDITORS[@]}))
  echo "${EDITORS[$idx]}"
}

lang_from_ext() {
  case "$1" in
    .py) echo "Python" ;;
    .js) echo "JavaScript" ;;
    .ts|.tsx) echo "TypeScript" ;;
    .rb) echo "Ruby" ;;
    .go) echo "Go" ;;
    .rs) echo "Rust" ;;
    .java) echo "Java" ;;
    .c) echo "C" ;;
    .cpp) echo "C++" ;;
    .h|.hpp) echo "C/C++" ;;
    .sh) echo "Shell" ;;
    .toml) echo "TOML" ;;
    .json) echo "JSON" ;;
    .yaml|.yml) echo "YAML" ;;
    .md) echo "Markdown" ;;
    *) echo "Plain Text" ;;
  esac
}

generate_heartbeat_json() {
  local ts="$1"
  local file
  file=$(pick_file)
  local ext="${file##*.}"
  local lang
  lang=$(lang_from_ext ".$ext")
  local editor
  editor=$(pick_editor)
  local lineno=$((RANDOM % 150 + 1))
  local lines=$((RANDOM % 400 + 20))
  local is_write
  if ((RANDOM % 4 == 0)); then is_write="false"; else is_write="true"; fi
  local line_adds=$((RANDOM % 15 + 1))
  local line_dels=$((RANDOM % 8 + 0))
  local ai_in_tokens=$((RANDOM % 2000 + 200))
  local ai_out_tokens=$((RANDOM % 800 + 50))
  local ai_prompt=$((RANDOM % 500 + 50))
  local ai_line_changes=$((RANDOM % 30 + 1))
  local human_line_changes=$((RANDOM % 15 + 0))
  local os_name
  case "$(uname -s)" in
    Darwin) os_name="Mac" ;;
    MINGW*|MSYS*|CYGWIN*) os_name="Windows" ;;
    *) os_name="Linux" ;;
  esac

  cat <<EOF
  {
    "entity": "${file}",
    "type": "file",
    "time": ${ts},
    "project": "${PROJECT}",
    "branch": "main",
    "category": "coding",
    "language": "${lang}",
    "editor": "${editor}",
    "operating_system": "${os_name}",
    "machine": "$(hostname)",
    "is_write": ${is_write},
    "lineno": ${lineno},
    "lines": ${lines},
    "cursorpos": $((RANDOM % 60 + 1)),
    "line_additions": ${line_adds},
    "line_deletions": ${line_dels},
    "ai_model": "gpt/5.3-codex",
    "ai_session": "${AI_SESSION}",
    "ai_subscription_plan": "pro",
    "ai_input_tokens": ${ai_in_tokens},
    "ai_output_tokens": ${ai_out_tokens},
    "ai_prompt_length": ${ai_prompt},
    "ai_line_changes": ${ai_line_changes},
    "human_line_changes": ${human_line_changes},
    "plugin": "vscode-wakatime/24.6.0"
  }
EOF
}

# Calculate number of heartbeats
NUM_BEATS=$((DURATION / INTERVAL))

echo "========================================"
echo "  Project:     ${PROJECT}"
echo "  Duration:    $(printf '%dh %dm %ds' $((DURATION/3600)) $(((DURATION%3600)/60)) $((DURATION%60)))"
echo "  Heartbeats:  ${NUM_BEATS}"
echo "  Interval:    ${INTERVAL}s (${INTERVAL}s) every $((INTERVAL/60))min"
echo "  AI Session:  ${AI_SESSION}"
echo "========================================"
echo ""

SUCCESS=0
FAILED=0

for ((i = 0; i < NUM_BEATS; i++)); do
  ts=$((START_TS + i * INTERVAL))
  # Add a tiny random offset (±5s) to avoid identical timestamps
  ts=$((ts + RANDOM % 10 - 5))

  payload=$(generate_heartbeat_json "$ts")

  status=$(curl -s -o /dev/null -w "%{http_code}" \
    -X POST "$API" \
    -H "Authorization: Bearer ${HACKATIME_API_KEY}" \
    -H "Content-Type: application/json" \
    -d "[${payload}]" 2>/dev/null || echo "000")

  pct=$((i * 100 / NUM_BEATS))
  elapsed_min=$(( (NOW - ts) / 60 ))

  if [[ "$status" == "201" || "$status" == "202" ]]; then
    echo "  [$pct%] HB $((i+1))/${NUM_BEATS} — ${elapsed_min}min ago [${status}] ✓"
    SUCCESS=$((SUCCESS + 1))
  else
    echo "  [$pct%] HB $((i+1))/${NUM_BEATS} — ${elapsed_min}min ago [${status}] ✗"
    FAILED=$((FAILED + 1))
  fi

  # Small delay to avoid rate limiting
  sleep 0.1
done

echo ""
echo "========================================"
echo "  Done! ${SUCCESS} sent, ${FAILED} failed"
echo "========================================"

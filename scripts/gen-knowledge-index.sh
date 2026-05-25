#!/bin/bash
SCRIPT_DIR="$(cd "$(dirname "$0")" && pwd)"
REPO_ROOT="$(dirname "$SCRIPT_DIR")"
echo "# 法律知识库索引"
echo "生成时间: $(date)"
for dir in laws interpretations guidance regulations; do
  if [ -d "$REPO_ROOT/$dir" ]; then
    count=$(find "$REPO_ROOT/$dir" -name "*.json" | wc -l)
    echo "- $dir: $count 部"
  fi
done
python3 "$SCRIPT_DIR/build_index.py" --all


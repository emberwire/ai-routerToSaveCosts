#!/usr/bin/env bash
set -e
DIR="$( cd "$( dirname "${BASH_SOURCE[0]}" )" >/dev/null 2>&1 && pwd )"

echo "⚡ Installing AI Router CLI dependencies..."
if [ ! -d "$DIR/.venv" ]; then
    python3 -m venv "$DIR/.venv"
fi

"$DIR/.venv/bin/pip" install -r "$DIR/requirements.txt"

echo ""
echo "✅ AI Router CLI successfully installed!"
echo ""
echo "To use the 'ai' command globally in your terminal, add this alias to your ~/.zshrc or ~/.bashrc:"
echo ""
echo "    alias ai='$DIR/run.sh'"
echo ""

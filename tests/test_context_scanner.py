import pytest
import tempfile
import os
from pathlib import Path
from ai_router.context_scanner import ContextScanner


def test_repo_scanner_with_temp_dir():
    with tempfile.TemporaryDirectory() as tmpdir:
        p = Path(tmpdir)
        (p / "package.json").write_text('{"dependencies": {"next": "14.0.0", "react": "18.0.0"}}')
        (p / "src").mkdir()
        (p / "src" / "index.ts").write_text("console.log('hello');")

        fp = ContextScanner.scan_repo(tmpdir)
        assert "Node.js" in fp.detected_frameworks
        assert "Next.js" in fp.detected_frameworks
        assert "package.json" in fp.top_level_files
        assert "src" in fp.directories
        assert fp.scan_duration_ms < 100.0

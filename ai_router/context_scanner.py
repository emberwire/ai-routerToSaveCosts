import os
import json
from pathlib import Path
from typing import Dict, List, Optional
from dataclasses import dataclass
from ai_router.security_guard import SecurityGuard


@dataclass
class RepoFingerprint:
    root_dir: str
    top_level_files: List[str]
    directories: List[str]
    detected_frameworks: List[str]
    manifest_summary: Dict[str, List[str]]
    total_scanned_files: int
    scan_duration_ms: float


class ContextScanner:
    """
    Local Repo Micro-Fingerprinter (<10ms).
    Extracts a high-density, low-token summary of the local codebase
    and scrubs secrets so the classifier knows existing capabilities.
    """

    IGNORE_DIRS = {
        ".git", ".venv", "venv", "node_modules", "__pycache__", ".pytest_cache",
        ".mypy_cache", "dist", "build", ".next", ".nuxt", "coverage", ".ai_router"
    }

    IGNORE_EXTENSIONS = {
        ".png", ".jpg", ".jpeg", ".gif", ".ico", ".pdf", ".zip", ".tar",
        ".gz", ".exe", ".dll", ".so", ".dylib", ".pyc", ".lock"
    }

    @classmethod
    def scan_repo(cls, root_path: Optional[str] = None) -> RepoFingerprint:
        import time
        start_time = time.time()

        root = Path(root_path or os.getcwd()).resolve()
        top_level_files = []
        directories = []
        manifest_summary: Dict[str, List[str]] = {}
        detected_frameworks = []
        total_files = 0

        # Scan top level
        try:
            for item in root.iterdir():
                if item.name in cls.IGNORE_DIRS or item.name.startswith("."):
                    continue

                if item.is_dir():
                    directories.append(item.name)
                elif item.is_file():
                    top_level_files.append(item.name)
                    total_files += 1

            # Read and summarize key manifests
            # 1. Node / JS / TS
            pkg_json = root / "package.json"
            if pkg_json.exists():
                detected_frameworks.append("Node.js")
                try:
                    data = json.loads(pkg_json.read_text())
                    deps = list(data.get("dependencies", {}).keys()) + list(data.get("devDependencies", {}).keys())
                    manifest_summary["npm"] = deps[:25]
                    if "next" in deps: detected_frameworks.append("Next.js")
                    if "react" in deps: detected_frameworks.append("React")
                    if "express" in deps: detected_frameworks.append("Express")
                    if "@stripe/stripe-js" in deps or "stripe" in deps: detected_frameworks.append("Stripe")
                    if "@supabase/supabase-js" in deps: detected_frameworks.append("Supabase")
                except Exception:
                    pass

            # 2. Python
            req_txt = root / "requirements.txt"
            if req_txt.exists():
                detected_frameworks.append("Python")
                try:
                    lines = [line.strip().split("==")[0].split(">=")[0] for line in req_txt.read_text().splitlines() if line.strip() and not line.startswith("#")]
                    manifest_summary["pip"] = lines[:25]
                    if "fastapi" in lines: detected_frameworks.append("FastAPI")
                    if "django" in lines: detected_frameworks.append("Django")
                    if "flask" in lines: detected_frameworks.append("Flask")
                    if "stripe" in lines: detected_frameworks.append("Stripe")
                except Exception:
                    pass

            pyproject = root / "pyproject.toml"
            if pyproject.exists() and "Python" not in detected_frameworks:
                detected_frameworks.append("Python")

            # 3. Rust / Go
            if (root / "Cargo.toml").exists():
                detected_frameworks.append("Rust")
            if (root / "go.mod").exists():
                detected_frameworks.append("Go")

        except Exception:
            pass

        duration_ms = (time.time() - start_time) * 1000

        return RepoFingerprint(
            root_dir=str(root),
            top_level_files=top_level_files[:30],
            directories=directories[:20],
            detected_frameworks=list(set(detected_frameworks)),
            manifest_summary=manifest_summary,
            total_scanned_files=total_files,
            scan_duration_ms=duration_ms,
        )

    @classmethod
    def get_summary_prompt_context(cls, root_path: Optional[str] = None) -> str:
        fp = cls.scan_repo(root_path)
        frameworks_str = ", ".join(fp.detected_frameworks) if fp.detected_frameworks else "Generic"
        dirs_str = ", ".join(fp.directories) if fp.directories else "none"
        files_str = ", ".join(fp.top_level_files[:15]) if fp.top_level_files else "none"

        deps_list = []
        for ecosystem, deps in fp.manifest_summary.items():
            deps_list.append(f"{ecosystem}: [{', '.join(deps[:10])}]")
        deps_str = "; ".join(deps_list) if deps_list else "None detected"

        return (
            f"Codebase Tech Stack: {frameworks_str}\n"
            f"Directories: {dirs_str}\n"
            f"Top Files: {files_str}\n"
            f"Key Dependencies: {deps_str}"
        )

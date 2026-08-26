"""Validate the repository shape before a Vercel/Supabase deployment.

This gate is intentionally dependency-free so it can run on a clean CI runner.
It checks the deploy entry points and environment contract, then measures the
source/function artifacts that are present locally. Vercel still performs the
authoritative dependency bundle calculation during deployment.
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

ROOT = Path(__file__).resolve().parents[1]
REQUIRED_FILES = (
    ".env.example",
    "backend/api/index.py",
    "backend/vercel.json",
    "frontend/package.json",
    "frontend/package-lock.json",
    "frontend/next.config.ts",
)
REQUIRED_ENV_KEYS = (
    "DATABASE_ADMIN_URL",
    "APP_DATABASE_URL",
    "ANALYTICS_DATABASE_URL",
    "FRONTEND_ORIGIN",
    "SESSION_HMAC_SECRET",
    "ACCESS_TOKEN_SECRET",
    "NEXT_PUBLIC_API_URL",
)
IGNORED_DIRS = {
    ".git",
    ".next",
    ".venv",
    "__pycache__",
    ".pytest_cache",
    ".mypy_cache",
    ".ruff_cache",
    "node_modules",
}


def _artifact_bytes(root: Path, ignored_dirs: set[str] = IGNORED_DIRS) -> int:
    total = 0
    for path in root.rglob("*"):
        relative = path.relative_to(root)
        if not path.is_file() or any(part in ignored_dirs for part in relative.parts):
            continue
        total += path.stat().st_size
    return total


def _env_keys(path: Path) -> dict[str, str]:
    values: dict[str, str] = {}
    for line_number, raw_line in enumerate(path.read_text(encoding="utf-8").splitlines(), start=1):
        line = raw_line.strip()
        if not line or line.startswith("#"):
            continue
        if "=" not in line:
            raise ValueError(f"{path}:{line_number} is not a KEY=VALUE entry")
        key, value = line.split("=", 1)
        values[key.strip()] = value.strip()
    return values


def _check(max_backend_mb: float, max_frontend_mb: float, require_frontend_build: bool) -> list[str]:
    errors: list[str] = []
    for relative in REQUIRED_FILES:
        if not (ROOT / relative).is_file():
            errors.append(f"missing required deployment file: {relative}")

    env_path = ROOT / ".env.example"
    if env_path.is_file():
        try:
            env_values = _env_keys(env_path)
        except ValueError as exc:
            errors.append(str(exc))
        else:
            missing = [key for key in REQUIRED_ENV_KEYS if key not in env_values]
            if missing:
                errors.append(".env.example is missing: " + ", ".join(missing))
            for key in ("GEMINI_API_KEY", "GROQ_API_KEY"):
                if env_values.get(key, "") and not env_values[key].startswith("replace-"):
                    errors.append(f".env.example must not contain a live {key}")
            for key in ("SESSION_HMAC_SECRET", "ACCESS_TOKEN_SECRET"):
                if env_values.get(key, "").startswith("replace-") is False:
                    errors.append(f".env.example {key} must remain a placeholder")

    vercel_path = ROOT / "backend/vercel.json"
    if vercel_path.is_file():
        try:
            vercel = json.loads(vercel_path.read_text(encoding="utf-8"))
            function = vercel["functions"]["api/index.py"]
            if function.get("maxDuration", 0) < 1:
                errors.append("backend/vercel.json must set a positive function maxDuration")
            if "tests" not in function.get("excludeFiles", ""):
                errors.append("backend/vercel.json must exclude backend tests")
        except (KeyError, TypeError, json.JSONDecodeError) as exc:
            errors.append(f"backend/vercel.json is not a valid FastAPI function config: {exc}")

    next_config = ROOT / "frontend/next.config.ts"
    if next_config.is_file() and "output: \"standalone\"" not in next_config.read_text(encoding="utf-8"):
        errors.append("frontend/next.config.ts must use standalone output for Vercel packaging")

    backend_mb = _artifact_bytes(ROOT / "backend") / (1024 * 1024)
    print(f"Backend source artifact: {backend_mb:.2f} MB (limit {max_backend_mb:.0f} MB)")
    if backend_mb > max_backend_mb:
        errors.append(f"backend source artifact exceeds {max_backend_mb:.0f} MB")

    standalone = ROOT / "frontend/.next/standalone"
    if standalone.is_dir():
        frontend_mb = _artifact_bytes(standalone, IGNORED_DIRS - {"node_modules"}) / (1024 * 1024)
        print(f"Frontend standalone artifact: {frontend_mb:.2f} MB (limit {max_frontend_mb:.0f} MB)")
        if frontend_mb > max_frontend_mb:
            errors.append(f"frontend standalone artifact exceeds {max_frontend_mb:.0f} MB")
    elif require_frontend_build:
        errors.append("frontend/.next/standalone is missing; run npm run build first")
    else:
        print("Frontend standalone artifact: not built (run npm run build before deployment)")

    return errors


def main() -> int:
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument("--max-backend-mb", type=float, default=500.0)
    parser.add_argument("--max-frontend-mb", type=float, default=500.0)
    parser.add_argument("--require-frontend-build", action="store_true")
    args = parser.parse_args()

    errors = _check(args.max_backend_mb, args.max_frontend_mb, args.require_frontend_build)
    if errors:
        print("Deployment preflight failed:", file=sys.stderr)
        for error in errors:
            print(f"- {error}", file=sys.stderr)
        return 1
    print("Deployment preflight passed.")
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

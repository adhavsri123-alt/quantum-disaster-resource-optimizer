"""
sync_backend.py
---------------
Safe, opt-in automation script for testing, verifying, and publishing
changes to GitHub on the 'backend-optimization' branch.

Safety guarantees:
  1. Verifies that the active git branch is 'backend-optimization' (never pushes to main).
  2. Runs the complete test suite before staging or pushing.
  3. Stops immediately on any test failure, unmerged conflict, or branch mismatch.
  4. Never force-pushes or rewrites remote git history.
  5. Never includes secrets, .env files, virtualenvs, or caches.
  6. Displays the exact files to be published before committing.
  7. Supports a --dry-run mode for pre-flight inspection.

Usage:
  python scripts/sync_backend.py
  python scripts/sync_backend.py --dry-run
  python scripts/sync_backend.py --message "Add comprehensive test suite"
"""

from __future__ import annotations

import argparse
import os
import subprocess
import sys
from typing import List, Tuple

EXPECTED_BRANCH = "backend-optimization"
FORBIDDEN_PATTERNS = [".env", "id_rsa", "token", "secret", "password", "venv", ".venv", "__pycache__"]

TEST_COMMANDS = [
    ("Simulation Tests", [sys.executable, "test_simulation.py"]),
    ("Optimization & QUBO Tests", [sys.executable, "test_optimization.py"]),
    ("Dynamic Simulation Tests", [sys.executable, "test_dynamic_simulation.py"]),
    ("Comprehensive Audit Tests", [sys.executable, "test_comprehensive.py"]),
]


def run_cmd(cmd: List[str], check: bool = True) -> subprocess.CompletedProcess:
    """Run a shell command and return CompletedProcess."""
    return subprocess.run(
        cmd,
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
        check=check,
    )


def check_git_branch() -> str:
    """Check that current branch matches EXPECTED_BRANCH."""
    res = run_cmd(["git", "rev-parse", "--abbrev-ref", "HEAD"])
    branch = res.stdout.strip()
    if branch != EXPECTED_BRANCH:
        print(f"[ERROR] Active branch is '{branch}', expected '{EXPECTED_BRANCH}'.")
        print("        To prevent unintended changes to other branches, auto-sync is aborted.")
        sys.exit(1)
    return branch


def check_merge_conflicts() -> None:
    """Ensure no unmerged conflict files exist."""
    res = run_cmd(["git", "status", "--porcelain"])
    for line in res.stdout.splitlines():
        if line.startswith("UU") or line.startswith("AA"):
            print(f"[ERROR] Merge conflict detected: {line}")
            print("        Resolve all conflicts before syncing.")
            sys.exit(1)


def get_changed_files() -> List[Tuple[str, str]]:
    """Return list of (status, filename) for all modified/untracked files."""
    res = run_cmd(["git", "status", "--porcelain"])
    changes = []
    for line in res.stdout.splitlines():
        line = line.strip()
        if not line:
            continue
        status = line[:2].strip()
        filename = line[2:].strip().strip('"')
        changes.append((status, filename))
    return changes


def validate_file_safety(changes: List[Tuple[str, str]]) -> None:
    """Check that no sensitive or forbidden files are in the change list."""
    for _, fname in changes:
        fname_lower = fname.lower()
        for forbidden in FORBIDDEN_PATTERNS:
            if forbidden in fname_lower:
                print(f"[ERROR] Forbidden pattern '{forbidden}' found in file: {fname}")
                print("        Remove or add to .gitignore before syncing.")
                sys.exit(1)


def run_test_suite() -> bool:
    """Execute the entire test suite. Returns True only if all pass."""
    print("=" * 70)
    print("  RUNNING PRE-SYNC VERIFICATION TESTS")
    print("=" * 70)

    for desc, cmd in TEST_COMMANDS:
        print(f"\n>> Running {desc} ({' '.join(cmd)})...")
        proc = subprocess.run(cmd, stdout=subprocess.PIPE, stderr=subprocess.PIPE, text=True)
        if proc.returncode != 0:
            print(f"\n[FAIL] {desc} FAILED (exit code {proc.returncode})!")
            print("--- STDOUT ---")
            print(proc.stdout[-1500:])
            print("--- STDERR ---")
            print(proc.stderr[-1500:])
            return False
        else:
            print(f"   [OK] {desc} passed.")

    print("\n" + "=" * 70)
    print("  ALL VERIFICATION TESTS PASSED SUCCESSFULLY [OK]")
    print("=" * 70)
    return True


def sync(dry_run: bool = False, commit_message: str = "") -> None:
    """Main synchronization flow."""
    print(f"Checking git repository and branch...")
    branch = check_git_branch()
    print(f"[OK] On target branch '{branch}'.")

    check_merge_conflicts()
    changes = get_changed_files()

    if not changes:
        print("[INFO] Working tree is clean. No changes to commit or publish.")
        return

    validate_file_safety(changes)

    print("\nDetected modified / new files:")
    for status, fname in changes:
        print(f"  [{status or '?'}] {fname}")

    # Run full test suite before any staging or committing
    if not run_test_suite():
        print("\n[ABORT] Pre-sync tests failed. Changes were NOT committed or pushed.")
        sys.exit(1)

    if dry_run:
        print("\n[DRY RUN] Verification succeeded. No git commands were executed.")
        return

    # Stage files
    files_to_add = [fname for _, fname in changes]
    print(f"\nStaging {len(files_to_add)} file(s)...")
    run_cmd(["git", "add"] + files_to_add)

    # Commit
    msg = commit_message or "Audit backend fixes, comprehensive testing, and solver verification"
    print(f"Committing with message: {msg!r}...")
    run_cmd(["git", "commit", "-m", msg])

    # Push to origin backend-optimization (safely, no force push)
    print(f"Publishing to remote 'origin/{branch}'...")
    push_proc = subprocess.run(
        ["git", "push", "origin", branch],
        stdout=subprocess.PIPE,
        stderr=subprocess.PIPE,
        text=True,
    )

    if push_proc.returncode != 0:
        print(f"\n[ERROR] git push failed:")
        print(push_proc.stderr)
        sys.exit(1)

    print("\n" + "=" * 70)
    print(f"  SUCCESSFULLY PUBLISHED TO origin/{branch}! [OK]")
    print("=" * 70)


def main():
    parser = argparse.ArgumentParser(description="Safely verify and sync QDO backend changes to GitHub.")
    parser.add_argument("--dry-run", action="store_true", help="Run tests and validation without committing or pushing.")
    parser.add_argument("--message", "-m", type=str, default="", help="Custom git commit message.")
    args = parser.parse_args()

    sync(dry_run=args.dry_run, commit_message=args.message)


if __name__ == "__main__":
    main()

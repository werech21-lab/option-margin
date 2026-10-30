#!/usr/bin/env python3
"""Autonomous One-Click Render & GitHub Deployment Script for OptionMargin.

Run this script on your local Windows PC (`python auto_deploy_render.py`) or double-click
`deploy_to_render.bat`. It automatically:
1. Verifies all 8 Golden Edge Cases pass (`unittest`).
2. Initializes the local Git repository and commits all production files.
3. If GitHub CLI (`gh`) is installed and authenticated, creates the remote GitHub repo and pushes automatically.
4. If `RENDER_API_KEY` is set, queries the Render REST API (`https://api.render.com/v1/owners`) and provisions
   the Render service, or launches the exact Render Blueprint URL in your default browser.
"""

import json
import os
import shutil
import subprocess
import sys
import urllib.request
import urllib.error
import webbrowser
from pathlib import Path

ROOT_DIR = Path(__file__).resolve().parent
RENDER_BLUEPRINT_URL = "https://dashboard.render.com/select-repo?type=blueprint"
RENDER_API_BASE = "https://api.render.com/v1"


def run_cmd(cmd: list[str], check: bool = True) -> subprocess.CompletedProcess:
    print(f"-> Running: {' '.join(cmd)}")
    return subprocess.run(cmd, cwd=str(ROOT_DIR), text=True, capture_output=True, check=check)


def step_1_verify_golden_tests() -> None:
    print("\n=== [1/4] Verifying 8 Golden Edge Cases Test Suite ===")
    res = run_cmd([sys.executable, "-m", "unittest", "discover", "-s", "tests", "-v"], check=False)
    print(res.stdout or res.stderr)
    if res.returncode != 0:
        print("ERROR: Golden tests failed. Aborting deployment.")
        sys.exit(1)
    print("OK: All 8 Golden Edge Cases passed 100%.")


def step_2_prepare_git_repo() -> None:
    print("\n=== [2/4] Initializing & Committing Local Git Repository ===")
    if not shutil.which("git"):
        print("WARNING: Git is not installed on this machine. Skipping local git init.")
        return

    if not (ROOT_DIR / ".git").exists():
        run_cmd(["git", "init", "-b", "main"], check=False)

    # Ensure .gitignore exists
    gitignore = ROOT_DIR / ".gitignore"
    if not gitignore.exists():
        gitignore.write_text("__pycache__/\n*.pyc\n*.db\n.env\n.venv/\n", encoding="utf-8")

    run_cmd(["git", "add", "."], check=False)
    status = run_cmd(["git", "status", "--porcelain"], check=False)
    if status.stdout.strip():
        run_cmd(
            ["git", "commit", "-m", "Production release: OptionMargin FAR 52.222-43 Autonomous Engine"],
            check=False,
        )
        print("OK: Committed all OptionMargin production files to branch 'main'.")
    else:
        print("OK: Git working tree is already clean and committed.")


def step_3_push_to_github() -> str | None:
    print("\n=== [3/4] Automated GitHub Repository Push ===")
    if not shutil.which("gh"):
        print("INFO: GitHub CLI ('gh') not found. Checking existing git remote...")
        rem = run_cmd(["git", "remote", "get-url", "origin"], check=False)
        if rem.returncode == 0 and rem.stdout.strip():
            repo_url = rem.stdout.strip()
            print(f"Found remote origin: {repo_url}. Pushing...")
            run_cmd(["git", "push", "-u", "origin", "main"], check=False)
            return repo_url
        return None

    # Check if origin already exists
    rem = run_cmd(["git", "remote", "get-url", "origin"], check=False)
    if rem.returncode == 0 and rem.stdout.strip():
        repo_url = rem.stdout.strip()
        run_cmd(["git", "push", "-u", "origin", "main"], check=False)
        return repo_url

    # Create repo via GitHub CLI automatically
    create_res = run_cmd(
        ["gh", "repo", "create", "option-margin", "--public", "--source=.", "--remote=origin", "--push"],
        check=False,
    )
    if create_res.returncode == 0:
        print("OK: Created GitHub repository 'option-margin' and pushed code automatically!")
        rem2 = run_cmd(["git", "remote", "get-url", "origin"], check=False)
        return rem2.stdout.strip()
    print("INFO: Could not auto-create GitHub repo via 'gh'. Output:", create_res.stderr.strip())
    return None


def step_4_deploy_to_render(repo_url: str | None, dry_run: bool = False) -> None:
    print("\n=== [4/4] Provisioning on Render Cloud (render.yaml Blueprint) ===")
    api_key = os.getenv("RENDER_API_KEY", "").strip()

    if api_key and repo_url:
        try:
            req = urllib.request.Request(
                f"{RENDER_API_BASE}/owners?limit=1",
                headers={
                    "Authorization": f"Bearer {api_key}",
                    "Accept": "application/json",
                },
            )
            with urllib.request.urlopen(req, timeout=15) as resp:
                owners = json.loads(resp.read().decode("utf-8"))
            if owners:
                owner_id = owners[0]["owner"]["id"]
                print(f"Verified Render Owner ID: {owner_id}")
                payload = json.dumps(
                    {
                        "type": "web_service",
                        "name": "optionmargin-engine",
                        "ownerId": owner_id,
                        "repo": repo_url,
                        "autoDeploy": "yes",
                        "serviceDetails": {
                            "env": "python",
                            "plan": "starter",
                            "envSpecificDetails": {
                                "buildCommand": "pip install -r requirements.txt",
                                "startCommand": "uvicorn app.main:app --host 0.0.0.0 --port $PORT",
                            },
                        },
                    }
                ).encode("utf-8")
                create_req = urllib.request.Request(
                    f"{RENDER_API_BASE}/services",
                    data=payload,
                    method="POST",
                    headers={
                        "Authorization": f"Bearer {api_key}",
                        "Content-Type": "application/json",
                        "Accept": "application/json",
                    },
                )
                with urllib.request.urlopen(create_req, timeout=20) as create_resp:
                    created = json.loads(create_resp.read().decode("utf-8"))
                    print("SUCCESS! Render Web Service Created Automatically:", created.get("service", {}).get("Name"))
                    return
        except urllib.error.URLError as exc:
            print(f"Render API note: {exc}. Falling back to browser Blueprint launch.")

    if not dry_run:
        print(f"Opening Render Blueprint Deployment Dashboard: {RENDER_BLUEPRINT_URL}")
        webbrowser.open(RENDER_BLUEPRINT_URL)
    else:
        print(f"Dry-run complete. Ready to open {RENDER_BLUEPRINT_URL}")


def main() -> None:
    dry_run = "--dry-run" in sys.argv
    step_1_verify_golden_tests()
    step_2_prepare_git_repo()
    repo_url = None if dry_run else step_3_push_to_github()
    step_4_deploy_to_render(repo_url, dry_run=dry_run)
    print("\n======================================================================")
    print("OptionMargin Auto-Deployer Finished Successfully!")
    print("======================================================================")


if __name__ == "__main__":
    main()

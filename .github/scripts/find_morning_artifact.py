"""Find today's morning artifact from a successful run on the same branch."""
import os
import sys
from pathlib import Path

import requests

sys.path.insert(0, str(Path(__file__).resolve().parents[2]))
from settings import target_date_jst


def find_run(session, base, name, branch):
    page = 1
    while True:
        response = session.get(
            f"{base}/actions/artifacts",
            params={"name": name, "per_page": 100, "page": page}, timeout=30,
        )
        response.raise_for_status()
        artifacts = response.json()["artifacts"]
        for artifact in artifacts:
            if artifact["expired"] or artifact["name"] != name:
                continue
            run_id = artifact["workflow_run"]["id"]
            response = session.get(f"{base}/actions/runs/{run_id}", timeout=30)
            response.raise_for_status()
            run = response.json()
            if (
                run["conclusion"] == "success"
                and run["head_branch"] == branch
                and run["path"] == ".github/workflows/market-schedule.yml"
            ):
                return run_id
        if len(artifacts) < 100:
            raise RuntimeError(f"No successful {name} artifact on branch {branch}; run morning first")
        page += 1


def main():
    if not os.environ.get("TARGET_DATE_JST"):
        raise RuntimeError("TARGET_DATE_JST is required")
    today = target_date_jst()
    base = f"{os.environ.get('GITHUB_API_URL', 'https://api.github.com')}/repos/{os.environ['GITHUB_REPOSITORY']}"
    with requests.Session() as session:
        session.headers.update({
            "Authorization": f"Bearer {os.environ['GITHUB_TOKEN']}",
            "Accept": "application/vnd.github+json",
        })
        run_id = find_run(session, base, f"morning-{today}", os.environ["GITHUB_REF_NAME"])
    with open(os.environ["GITHUB_OUTPUT"], "a", encoding="utf-8") as output:
        output.write(f"run_id={run_id}\n")
    print(f"Morning run: {run_id}")


if __name__ == "__main__":
    main()

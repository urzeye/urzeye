#!/usr/bin/env python3
"""
Automatically fetch PRs submitted to other repositories and update README.md.
"""

import os
import re
from datetime import datetime

import requests

# Configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "urzeye")
MAX_PRS = 20
README_PATH = "README.md"

# GraphQL API endpoint
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# GraphQL query: fetch PRs created by the user
QUERY = """
query($username: String!, $cursor: String) {
  user(login: $username) {
    pullRequests(first: 100, after: $cursor, orderBy: {field: CREATED_AT, direction: DESC}) {
      nodes {
        title
        url
        state
        createdAt
        repository {
          nameWithOwner
          owner {
            login
          }
        }
      }
      pageInfo {
        hasNextPage
        endCursor
      }
    }
  }
}
"""


def fetch_prs() -> list[dict]:
    """Fetch all PRs created by the user."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }

    all_prs = []
    cursor = None

    while True:
        variables = {"username": GITHUB_USERNAME, "cursor": cursor}
        response = requests.post(
            GITHUB_GRAPHQL_URL,
            json={"query": QUERY, "variables": variables},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise Exception(f"GraphQL errors: {data['errors']}")

        pr_data = data["data"]["user"]["pullRequests"]
        all_prs.extend(pr_data["nodes"])

        # Check if there are more pages
        if not pr_data["pageInfo"]["hasNextPage"]:
            break
        cursor = pr_data["pageInfo"]["endCursor"]

        # Exit early if enough PRs have been collected
        if len(all_prs) >= MAX_PRS * 2:
            break

    return all_prs


def filter_external_prs(prs: list[dict]) -> list[dict]:
    """Filter: keep only merged PRs submitted to other repositories (excluding own repos and unmerged PRs)."""
    return [
        pr
        for pr in prs
        if pr["repository"]["owner"]["login"].lower() != GITHUB_USERNAME.lower()
        and pr["state"] == "MERGED"
    ]


def format_state(state: str) -> str:
    """Format PR state."""
    state_map = {
        "MERGED": "✅ Merged",
        "OPEN": "🟡 Open",
        "CLOSED": "❌ Closed",
    }
    return state_map.get(state, state)


def format_date(iso_date: str) -> str:
    """Format date."""
    dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d")


def generate_markdown(prs: list[dict]) -> str:
    """Generate Markdown content grouped by repository."""
    if not prs:
        return "No PRs submitted to other open source projects yet.\n"

    # Group by repository
    repos: dict[str, list[dict]] = {}
    for pr in prs[:MAX_PRS]:
        repo_name = pr["repository"]["nameWithOwner"]
        if repo_name not in repos:
            repos[repo_name] = []
        repos[repo_name].append(pr)

    lines = []
    for repo_name, repo_prs in repos.items():
        lines.append(f"#### [{repo_name}](https://github.com/{repo_name})")
        lines.append("")
        lines.append("| Title | Status | Date |")
        lines.append("|-------|--------|------|")

        for pr in repo_prs:
            title = pr["title"]
            # Truncate long titles
            if len(title) > 50:
                title = title[:47] + "..."
            url = pr["url"]
            state = format_state(pr["state"])
            date = format_date(pr["createdAt"])
            lines.append(f"| [{title}]({url}) | {state} | {date} |")

        lines.append("")

    return "\n".join(lines)


def update_readme(markdown_content: str) -> bool:
    """Update the PR section in README.md."""
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()

    # Match the placeholder region
    pattern = r"(<!-- PR_START -->).*?(<!-- PR_END -->)"
    replacement = f"\\1\n{markdown_content}\\2"

    new_readme, count = re.subn(pattern, replacement, readme, flags=re.DOTALL)

    if count == 0:
        print("Warning: PR placeholder region not found (<!-- PR_START --> ... <!-- PR_END -->)")
        return False

    # Check if content has changed
    if new_readme == readme:
        print("README.md unchanged, skipping update.")
        return False

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_readme)

    print("README.md updated.")
    return True


def main():
    if not GITHUB_TOKEN:
        raise Exception("GITHUB_TOKEN environment variable is not set")

    print(f"Fetching PRs for {GITHUB_USERNAME}...")
    all_prs = fetch_prs()
    print(f"Total PRs fetched: {len(all_prs)}")

    external_prs = filter_external_prs(all_prs)
    print(f"External contribution PRs after filtering: {len(external_prs)}")

    markdown = generate_markdown(external_prs)
    update_readme(markdown)


if __name__ == "__main__":
    main()

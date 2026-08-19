#!/usr/bin/env python3
"""
Automatically fetch PRs submitted to other repositories via GitHub GraphQL Search API,
filter by star thresholds and impact, sort by repository stars (high-impact first),
and update README.md with a curated, concise list of notable open-source contributions.
"""

import os
import re
from datetime import datetime

import requests

# Configuration
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "urzeye")
README_PATH = "README.md"
MIN_STARS = 50          # Minimum repository stars to be considered notable
MAX_NOTABLE_REPOS = 4   # Maximum notable repositories to showcase on profile

# GraphQL API endpoint
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

SEARCH_QUERY = """
query($searchQuery: String!, $cursor: String) {
  search(query: $searchQuery, type: ISSUE, first: 100, after: $cursor) {
    issueCount
    nodes {
      ... on PullRequest {
        title
        url
        state
        createdAt
        changedFiles
        repository {
          nameWithOwner
          stargazerCount
          description
          primaryLanguage {
            name
          }
          owner {
            login
          }
        }
      }
    }
    pageInfo {
      hasNextPage
      endCursor
    }
  }
}
"""


def fetch_external_merged_prs() -> tuple[int, list[dict]]:
    """Fetch all merged PRs submitted to external repositories."""
    headers = {
        "Authorization": f"Bearer {GITHUB_TOKEN}",
        "Content-Type": "application/json",
    }

    search_str = f"type:pr author:{GITHUB_USERNAME} -user:{GITHUB_USERNAME} is:merged"
    all_prs = []
    cursor = None
    total_count = 0

    while True:
        variables = {"searchQuery": search_str, "cursor": cursor}
        response = requests.post(
            GITHUB_GRAPHQL_URL,
            json={"query": SEARCH_QUERY, "variables": variables},
            headers=headers,
            timeout=30,
        )
        response.raise_for_status()
        data = response.json()

        if "errors" in data:
            raise Exception(f"GraphQL errors: {data['errors']}")

        search_data = data["data"]["search"]
        total_count = search_data.get("issueCount", 0)
        nodes = search_data.get("nodes", [])

        for node in nodes:
            if node and node.get("repository"):
                if node["repository"]["owner"]["login"].lower() != GITHUB_USERNAME.lower():
                    all_prs.append(node)

        if not search_data["pageInfo"]["hasNextPage"]:
            break
        cursor = search_data["pageInfo"]["endCursor"]

    return total_count, all_prs


def is_curation_or_awesome_pr(pr: dict) -> bool:
    """Filter out awesome-lists, bookmark curations, and trivial index submissions."""
    repo = pr.get("repository", {})
    repo_name = repo.get("nameWithOwner", "").lower()
    repo_desc = (repo.get("description") or "").lower()
    title = pr.get("title", "").strip().lower()
    primary_lang = repo.get("primaryLanguage")

    curation_repo_keywords = [
        "awesome",
        "curated",
        "collection",
        "plugin-list",
        "awesome-plugins",
        "resource",
        "directory",
        "showcase",
        "bookmarks",
        "site-pack",
        "site-packs",
    ]
    if any(kw in repo_name for kw in curation_repo_keywords):
        return True

    curation_desc_keywords = [
        "curated list",
        "a curated",
        "collection of",
        "list of awesome",
        "awesome list",
        "useful resources",
    ]
    if any(kw in repo_desc for kw in curation_desc_keywords):
        return True

    curation_title_pattern = (
        r"^(add|curate:|docs:\s*add|feat:\s*add)\s+.*"
        r"(\bto\b|outline|plugin|list|readme|enhancement|table|collection)"
    )
    if re.search(curation_title_pattern, title, re.I):
        return True

    if (primary_lang is None or primary_lang.get("name") in ["Markdown", "HTML", "Text"]) and (
        "plugin" in repo_name or "harness" in repo_name or "list" in repo_name
    ):
        return True

    return False


def format_stars(star_count: int) -> str:
    """Format star counts nicely (e.g., 80.3k, 1.3k, 593)."""
    if star_count >= 1000:
        return f"⭐ {star_count / 1000:.1f}k"
    return f"⭐ {star_count}"


def generate_markdown(total_prs: int, all_external_prs: list[dict]) -> str:
    """
    Generate a high-impact, concise Markdown table grouped by repository
    and sorted by repository stars (largest projects first).
    """
    unique_repos_count = len(
        set(pr["repository"]["nameWithOwner"] for pr in all_external_prs if pr.get("repository"))
    )

    # 1. Group meaningful PRs by repository
    repo_groups: dict[str, dict] = {}
    for pr in all_external_prs:
        if is_curation_or_awesome_pr(pr):
            continue

        repo = pr.get("repository", {})
        repo_name = repo.get("nameWithOwner")
        if not repo_name:
            continue

        stars = repo.get("stargazerCount", 0)
        if stars < MIN_STARS:
            continue

        if repo_name not in repo_groups:
            repo_groups[repo_name] = {
                "name": repo_name,
                "stars": stars,
                "prs": [],
            }
        repo_groups[repo_name]["prs"].append(pr)

    # 2. Sort repositories by stars descending (Biggest projects first)
    sorted_repos = sorted(
        repo_groups.values(),
        key=lambda r: r["stars"],
        reverse=True,
    )

    lines = []
    lines.append(
        f"> 📊 Contributed to **{total_prs} merged pull requests** across **{unique_repos_count} open-source repositories**."
    )
    lines.append("")

    if not sorted_repos:
        lines.append("No featured high-impact contributions yet.\n")
        return "\n".join(lines)

    lines.append("| Organization / Project | Stars | Key Contribution |")
    lines.append("|:---|:---:|:---|")

    for repo_info in sorted_repos[:MAX_NOTABLE_REPOS]:
        repo_name = repo_info["name"]
        stars_str = format_stars(repo_info["stars"])
        prs = repo_info["prs"]
        latest_pr = prs[0]
        title = latest_pr["title"].strip()
        if len(title) > 58:
            title = title[:55] + "..."
        url = latest_pr["url"]
        
        pr_count = len(prs)
        extra_note = f" *(+{pr_count - 1} more)*" if pr_count > 1 else ""

        lines.append(
            f"| [**{repo_name}**](https://github.com/{repo_name}) | {stars_str} | [{title}]({url}){extra_note} |"
        )

    lines.append("")
    return "\n".join(lines)


def update_readme(markdown_content: str) -> bool:
    """Update the PR section in README.md."""
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()

    pattern = r"(<!-- PR_START -->).*?(<!-- PR_END -->)"
    replacement = f"\\1\n{markdown_content}\\2"

    new_readme, count = re.subn(pattern, replacement, readme, flags=re.DOTALL)

    if count == 0:
        print("Warning: PR placeholder region not found (<!-- PR_START --> ... <!-- PR_END -->)")
        return False

    if new_readme == readme:
        print("README.md unchanged, skipping update.")
        return False

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_readme)

    print("README.md successfully updated.")
    return True


def main():
    if not GITHUB_TOKEN:
        raise Exception("GITHUB_TOKEN environment variable is not set")

    print(f"Fetching external PRs for {GITHUB_USERNAME} via GraphQL Search...")
    total_count, all_prs = fetch_external_merged_prs()
    print(f"Total external merged PRs fetched: {len(all_prs)} (search count: {total_count})")

    markdown = generate_markdown(total_count, all_prs)
    update_readme(markdown)


if __name__ == "__main__":
    main()

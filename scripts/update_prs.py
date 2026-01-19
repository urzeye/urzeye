#!/usr/bin/env python3
"""
自动获取向其他仓库提交的 PR，并更新到 README.md 中。
"""

import os
import re
from datetime import datetime

import requests

# 配置
GITHUB_TOKEN = os.environ.get("GITHUB_TOKEN")
GITHUB_USERNAME = os.environ.get("GITHUB_USERNAME", "urzeye")
MAX_PRS = 20
README_PATH = "README.md"

# GraphQL API 端点
GITHUB_GRAPHQL_URL = "https://api.github.com/graphql"

# GraphQL 查询：获取用户创建的 PR
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
    """获取用户创建的所有 PR"""
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

        # 检查是否还有更多数据
        if not pr_data["pageInfo"]["hasNextPage"]:
            break
        cursor = pr_data["pageInfo"]["endCursor"]

        # 如果已经收集足够多的 PR，提前退出
        if len(all_prs) >= MAX_PRS * 2:
            break

    return all_prs


def filter_external_prs(prs: list[dict]) -> list[dict]:
    """过滤：只保留向其他仓库提交的 PR（排除自己的仓库）"""
    return [
        pr
        for pr in prs
        if pr["repository"]["owner"]["login"].lower() != GITHUB_USERNAME.lower()
    ]


def format_state(state: str) -> str:
    """格式化 PR 状态"""
    state_map = {
        "MERGED": "✅ 已合并",
        "OPEN": "🟡 待审核",
        "CLOSED": "❌ 已关闭",
    }
    return state_map.get(state, state)


def format_date(iso_date: str) -> str:
    """格式化日期"""
    dt = datetime.fromisoformat(iso_date.replace("Z", "+00:00"))
    return dt.strftime("%Y-%m-%d")


def generate_markdown(prs: list[dict]) -> str:
    """生成按仓库分组的 Markdown 内容"""
    if not prs:
        return "暂无向其他开源项目提交的 PR。\n"

    # 按仓库分组
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
        lines.append("| 标题 | 状态 | 创建时间 |")
        lines.append("|------|------|----------|")

        for pr in repo_prs:
            title = pr["title"]
            # 截断过长的标题
            if len(title) > 50:
                title = title[:47] + "..."
            url = pr["url"]
            state = format_state(pr["state"])
            date = format_date(pr["createdAt"])
            lines.append(f"| [{title}]({url}) | {state} | {date} |")

        lines.append("")

    return "\n".join(lines)


def update_readme(markdown_content: str) -> bool:
    """更新 README.md 中的 PR 区域"""
    with open(README_PATH, "r", encoding="utf-8") as f:
        readme = f.read()

    # 匹配占位符区域
    pattern = r"(<!-- PR_START -->).*?(<!-- PR_END -->)"
    replacement = f"\\1\n{markdown_content}\\2"

    new_readme, count = re.subn(pattern, replacement, readme, flags=re.DOTALL)

    if count == 0:
        print("警告：未找到 PR 占位符区域 (<!-- PR_START --> ... <!-- PR_END -->)")
        return False

    # 检查内容是否有变化
    if new_readme == readme:
        print("README.md 内容无变化，跳过更新。")
        return False

    with open(README_PATH, "w", encoding="utf-8") as f:
        f.write(new_readme)

    print("README.md 已更新。")
    return True


def main():
    if not GITHUB_TOKEN:
        raise Exception("GITHUB_TOKEN 环境变量未设置")

    print(f"正在获取 {GITHUB_USERNAME} 的 PR...")
    all_prs = fetch_prs()
    print(f"共获取 {len(all_prs)} 个 PR")

    external_prs = filter_external_prs(all_prs)
    print(f"过滤后保留 {len(external_prs)} 个外部贡献 PR")

    markdown = generate_markdown(external_prs)
    update_readme(markdown)


if __name__ == "__main__":
    main()

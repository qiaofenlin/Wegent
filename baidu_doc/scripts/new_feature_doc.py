#!/usr/bin/env python3
# SPDX-FileCopyrightText: 2026 Weibo, Inc.
#
# SPDX-License-Identifier: Apache-2.0

from __future__ import annotations

import re
import sys
from datetime import datetime, timezone, timedelta
from pathlib import Path


ROOT = Path(__file__).resolve().parents[2]
FEATURES_DIR = ROOT / "baidu_doc" / "features"
README_PATH = ROOT / "baidu_doc" / "README.md"
TEMPLATE_PATH = FEATURES_DIR / "TEMPLATE.md"


def slugify(title: str) -> str:
    slug = title.strip().lower()
    slug = re.sub(r"[^a-z0-9\u4e00-\u9fff]+", "-", slug)
    slug = re.sub(r"-+", "-", slug).strip("-")
    return slug or "untitled-feature"


def next_index() -> int:
    max_index = 0
    for path in FEATURES_DIR.glob("[0-9][0-9]-*.md"):
        match = re.match(r"^(\d{2})-", path.name)
        if match:
            max_index = max(max_index, int(match.group(1)))
    return max_index + 1


def load_template() -> str:
    if not TEMPLATE_PATH.exists():
        raise FileNotFoundError(f"Template not found: {TEMPLATE_PATH}")
    return TEMPLATE_PATH.read_text(encoding="utf-8")


def render_content(index: int, title: str) -> str:
    now = datetime.now(timezone(timedelta(hours=8))).strftime("%Y-%m-%d %H:%M:%S %z")
    content = load_template()
    content = content.replace("NN", f"{index:02d}", 1)
    content = content.replace("功能需求标题", title, 1)
    content = content.replace("YYYY-MM-DD HH:MM:SS +0800", now, 1)
    return content


def update_readme(index: int, filename: str, title: str) -> None:
    if not README_PATH.exists():
        raise FileNotFoundError(f"README not found: {README_PATH}")

    readme = README_PATH.read_text(encoding="utf-8")
    marker = "### Feature 需求记录\n"
    line = f"- [features/{filename}](./features/{filename}) — {title}\n"

    if line in readme:
        return

    position = readme.find(marker)
    if position == -1:
        raise ValueError("Cannot find feature section marker in baidu_doc/README.md")

    insert_after = readme.find("\n", position + len(marker))
    if insert_after == -1:
        insert_after = len(readme)

    readme = readme[: insert_after + 1] + line + readme[insert_after + 1 :]
    README_PATH.write_text(readme, encoding="utf-8")


def main() -> int:
    if len(sys.argv) < 2:
        print("Usage: python baidu_doc/scripts/new_feature_doc.py \"需求标题\"")
        return 1

    title = sys.argv[1].strip()
    if not title:
        print("Error: title cannot be empty")
        return 1

    FEATURES_DIR.mkdir(parents=True, exist_ok=True)
    index = next_index()
    slug = slugify(title)
    filename = f"{index:02d}-{slug}.md"
    target = FEATURES_DIR / filename

    if target.exists():
        print(f"Error: target already exists: {target}")
        return 1

    target.write_text(render_content(index, title), encoding="utf-8")
    update_readme(index, filename, title)

    print(target.relative_to(ROOT))
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

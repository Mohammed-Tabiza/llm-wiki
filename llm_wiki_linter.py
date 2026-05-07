import argparse
import re
from dataclasses import dataclass, field
from pathlib import Path

from langchain.chat_models import init_chat_model
from langchain_core.prompts import ChatPromptTemplate
from pydantic import BaseModel, Field

from wiki_config import INDEX_FILE, REPORT_FILE, WIKI_DIR, get_chat_model_kwargs

LINT_PAGE_PROMPT = """
You are linting a generated Obsidian LLM wiki page.

Goal:
- Keep the wiki clean, grounded, navigable, and low-duplication.
- Do not invent facts beyond the page content.

Check for:
- vague or generic summaries
- duplicated or overlapping concepts
- entities that should be topics, or topics that should be entities
- broken or suspicious wiki links
- missing sources, mentions, related links, or raw source references
- page names that should be more canonical
- content that should be split, merged, renamed, or deleted

Page path:
{wiki_path}

Page content:
{page_content}

Return concise JSON using this schema:
{output_schema}
"""


class LintIssue(BaseModel):
    severity: str = Field(description="One of: low, medium, high.")
    title: str = Field(description="Short issue title.")
    detail: str = Field(description="Concrete explanation grounded in the page.")
    recommendation: str = Field(description="Specific cleanup action.")


class PageLintResult(BaseModel):
    page_quality: int = Field(description="Overall page quality from 1 to 10.")
    issues: list[LintIssue] = Field(description="Lint issues found on the page.")
    suggested_title: str = Field(description="Canonical title suggestion, or the current title.")
    should_merge_with: list[str] = Field(description="Candidate wiki paths to merge with, if any.")
    should_delete: bool = Field(description="True only if the page is empty or useless.")


@dataclass
class StaticIssue:
    wiki_path: str
    severity: str
    title: str
    detail: str
    recommendation: str


@dataclass
class PageLint:
    wiki_path: str
    page_quality: int
    issues: list[LintIssue] = field(default_factory=list)
    suggested_title: str = ""
    should_merge_with: list[str] = field(default_factory=list)
    should_delete: bool = False


llm = init_chat_model(**get_chat_model_kwargs(max_tokens=768))
structured_llm = llm.with_structured_output(PageLintResult, method="json_mode")


def read_text(path: Path) -> str:
    return path.read_text(encoding="utf-8") if path.exists() else ""


def write_text(path: Path, content: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(content.strip() + "\n", encoding="utf-8")


def build_wiki_path(path: Path) -> str:
    return str(path.relative_to(WIKI_DIR).with_suffix("")).replace("\\", "/")


def get_page_path(wiki_path: str) -> Path:
    return WIKI_DIR / f"{wiki_path}.md"


def list_wiki_pages() -> list[Path]:
    return sorted(path for path in WIKI_DIR.rglob("*.md") if path != REPORT_FILE)


def extract_wiki_links(content: str) -> list[str]:
    return re.findall(r"\[\[([^\]|#]+)(?:#[^\]|]+)?(?:\|[^\]]+)?\]\]", content)


def normalize_generated_markdown(content: str) -> str:
    lines = [line.rstrip() for line in content.splitlines()]
    normalized = "\n".join(lines)
    normalized = re.sub(r"\n{3,}", "\n\n", normalized)
    return normalized.strip() + "\n"


def find_static_issues(page_paths: list[Path]) -> list[StaticIssue]:
    existing_paths = {build_wiki_path(path) for path in page_paths}
    issues: list[StaticIssue] = []

    for page_path in page_paths:
        wiki_path = build_wiki_path(page_path)
        content = read_text(page_path)

        if not content.strip():
            issues.append(
                StaticIssue(
                    wiki_path=wiki_path,
                    severity="high",
                    title="Empty page",
                    detail="The page has no content.",
                    recommendation="Delete the page or rebuild the wiki from sources.",
                )
            )

        for link in extract_wiki_links(content):
            if link not in existing_paths:
                issues.append(
                    StaticIssue(
                        wiki_path=wiki_path,
                        severity="high",
                        title="Broken wiki link",
                        detail=f"The link [[{link}]] does not point to an existing page.",
                        recommendation="Rename the link target, recreate the missing page, or rebuild the wiki.",
                    )
                )

        if wiki_path.startswith(("topics/", "entities/")):
            if "## Sources" not in content:
                issues.append(
                    StaticIssue(
                        wiki_path=wiki_path,
                        severity="medium",
                        title="Missing Sources section",
                        detail="Knowledge pages should point back to their source pages.",
                        recommendation="Rebuild the page with source backlinks.",
                    )
                )

            if "## Mentions" not in content:
                issues.append(
                    StaticIssue(
                        wiki_path=wiki_path,
                        severity="medium",
                        title="Missing Mentions section",
                        detail="Knowledge pages should preserve source-specific mentions.",
                        recommendation="Rebuild the page with mention lines.",
                    )
                )

    return issues


def lint_page_with_llm(page_path: Path) -> PageLint:
    wiki_path = build_wiki_path(page_path)
    prompt = ChatPromptTemplate.from_template(LINT_PAGE_PROMPT)
    chain = prompt | structured_llm
    result = chain.invoke(
        {
            "wiki_path": wiki_path,
            "page_content": read_text(page_path),
            "output_schema": PageLintResult.model_json_schema(),
        }
    )

    return PageLint(
        wiki_path=wiki_path,
        page_quality=result.page_quality,
        issues=result.issues,
        suggested_title=result.suggested_title,
        should_merge_with=result.should_merge_with,
        should_delete=result.should_delete,
    )


def apply_safe_cleanup(page_paths: list[Path]) -> int:
    changed_count = 0

    for page_path in page_paths:
        current = read_text(page_path)
        cleaned = normalize_generated_markdown(current)
        if cleaned != current:
            write_text(page_path, cleaned)
            changed_count += 1

    return changed_count


def render_report(
    page_count: int,
    static_issues: list[StaticIssue],
    page_lints: list[PageLint],
) -> str:
    lines = [
        "# Wiki Lint Report",
        "",
        f"- Pages checked: {page_count}",
        f"- Static issues: {len(static_issues)}",
        f"- LLM issues: {sum(len(page.issues) for page in page_lints)}",
        "",
        "## Static Issues",
    ]

    if static_issues:
        for issue in static_issues:
            lines.extend(
                [
                    "",
                    f"### {issue.severity.upper()} - {issue.wiki_path} - {issue.title}",
                    issue.detail,
                    f"Recommendation: {issue.recommendation}",
                ]
            )
    else:
        lines.append("- None.")

    lines.extend(["", "## Page Reviews"])

    if not page_lints:
        lines.append("- Skipped. Run without `--skip-llm` for semantic page reviews.")
        return "\n".join(lines)

    for page in sorted(page_lints, key=lambda item: item.wiki_path):
        lines.extend(
            [
                "",
                f"### {page.wiki_path}",
                f"- Quality: {page.page_quality}/10",
                f"- Suggested title: {page.suggested_title or page.wiki_path}",
                f"- Merge candidates: {', '.join(page.should_merge_with) or 'None'}",
                f"- Should delete: {page.should_delete}",
            ]
        )

        if page.issues:
            for issue in page.issues:
                lines.extend(
                    [
                        f"- {issue.severity.upper()}: {issue.title}",
                        f"  Detail: {issue.detail}",
                        f"  Recommendation: {issue.recommendation}",
                    ]
                )
        else:
            lines.append("- No LLM issues.")

    return "\n".join(lines)


def main() -> None:
    parser = argparse.ArgumentParser(description="Lint the generated LLM wiki.")
    parser.add_argument(
        "--apply",
        action="store_true",
        help="Apply safe mechanical cleanup before writing the lint report.",
    )
    parser.add_argument(
        "--skip-llm",
        action="store_true",
        help="Run static checks only.",
    )
    args = parser.parse_args()

    page_paths = list_wiki_pages()
    if not page_paths:
        raise SystemExit(f"No wiki pages found in {WIKI_DIR}")

    print(f"Found {len(page_paths)} wiki pages in {WIKI_DIR}", flush=True)

    if args.apply:
        print("Applying safe mechanical cleanup ...", flush=True)
    changed_count = apply_safe_cleanup(page_paths) if args.apply else 0

    print("Running static checks ...", flush=True)
    static_issues = find_static_issues(page_paths)

    if args.skip_llm:
        print("Skipping LLM semantic reviews because --skip-llm was provided.", flush=True)
        page_lints = []
    else:
        page_lints = []
        print("Running LLM semantic reviews ...", flush=True)
        for index, page_path in enumerate(page_paths, start=1):
            wiki_path = build_wiki_path(page_path)
            print(f"[{index}/{len(page_paths)}] Reviewing {wiki_path}", flush=True)
            page_lints.append(lint_page_with_llm(page_path))

    report = render_report(len(page_paths), static_issues, page_lints)
    write_text(REPORT_FILE, report)

    print(f"Checked {len(page_paths)} pages.")
    print(f"Static issues: {len(static_issues)}")
    print(f"LLM issues: {sum(len(page.issues) for page in page_lints)}")
    print(f"Safe cleanup changed {changed_count} pages.")
    print(f"Wrote {REPORT_FILE}")


if __name__ == "__main__":
    main()

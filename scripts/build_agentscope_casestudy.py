#!/usr/bin/env python3

from __future__ import annotations

import json
import re
import shutil
import urllib.request
import xml.etree.ElementTree as ET
from collections import defaultdict
from pathlib import Path


ROOT = Path(__file__).resolve().parents[1]
OUT_DIR = ROOT / "AgentScope-casestudy"
RAW_DIR = OUT_DIR / "raw"
PAGES_DIR = OUT_DIR / "pages"
INVENTORY_DIR = OUT_DIR / "inventory"
SUMMARIES_DIR = OUT_DIR / "summaries"

SITEMAP_URL = "https://docs.agentscope.io/sitemap.xml"
LLMS_URL = "https://docs.agentscope.io/llms.txt"
LLMS_FULL_URL = "https://docs.agentscope.io/llms-full.txt"
OPENAPI_URL = "https://docs.agentscope.io/api-reference/openapi.json"

DOCS_HOSTS = (
    "https://docs.agentscope.io",
    "https://agentscope-ai-786677c7.mintlify.app",
)


def fetch_text(url: str) -> str:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read().decode("utf-8", "ignore")


def fetch_bytes(url: str) -> bytes:
    with urllib.request.urlopen(url, timeout=30) as response:
        return response.read()


def normalize_url(url: str) -> str:
    normalized = url.strip()
    for host in DOCS_HOSTS:
        if normalized.startswith(host):
            normalized = normalized.replace(host, "https://docs.agentscope.io", 1)
            break
    normalized = normalized.rstrip("/")
    if normalized.endswith(".md"):
        normalized = normalized[:-3]
    if normalized == "https://docs.agentscope.io":
        return normalized
    return normalized


def path_for_url(url: str) -> str:
    path = normalize_url(url).replace("https://docs.agentscope.io", "")
    return path or "/"


def section_for_path(path: str) -> str:
    stripped = path.strip("/")
    if not stripped:
        return "root"
    return stripped.split("/", 1)[0]


def slug_for_path(path: str) -> str:
    stripped = path.strip("/")
    if not stripped:
        return "index"
    return stripped.split("/")[-1]


def parse_sitemap(xml_text: str) -> list[dict]:
    root = ET.fromstring(xml_text)
    ns = {"sm": "http://www.sitemaps.org/schemas/sitemap/0.9"}
    urls = []
    for url_node in root.findall("sm:url", ns):
        loc = url_node.find("sm:loc", ns)
        lastmod = url_node.find("sm:lastmod", ns)
        if loc is None or not loc.text:
            continue
        url = normalize_url(loc.text)
        path = path_for_url(url)
        urls.append(
            {
                "url": url,
                "path": path,
                "section": section_for_path(path),
                "slug": slug_for_path(path),
                "lastmod": lastmod.text.strip() if lastmod is not None and lastmod.text else None,
            }
        )
    return urls


def parse_llms_index(llms_text: str) -> dict[str, dict]:
    page_map: dict[str, dict] = {}
    pattern = re.compile(r"^- \[(?P<title>.+?)\]\((?P<url>https://[^)]+)\): (?P<desc>.+)$", re.M)
    for match in pattern.finditer(llms_text):
        url = normalize_url(match.group("url"))
        page_map[url] = {
            "title": match.group("title").strip(),
            "description": match.group("desc").strip(),
        }
    return page_map


def parse_llms_full(full_text: str) -> list[dict]:
    matches = list(re.finditer(r"(?m)^# (?P<title>.+)\nSource: (?P<source>https?://\S+)\n", full_text))
    pages = []
    for idx, match in enumerate(matches):
        start = match.start()
        end = matches[idx + 1].start() if idx + 1 < len(matches) else len(full_text)
        block = full_text[start:end].strip() + "\n"
        source = normalize_url(match.group("source"))
        path = path_for_url(source)
        pages.append(
            {
                "title": match.group("title").strip(),
                "url": source,
                "path": path,
                "section": section_for_path(path),
                "slug": slug_for_path(path),
                "content": block,
            }
        )
    return pages


def summarize_page(content: str) -> str:
    lines = [line.strip() for line in content.splitlines()]
    started = False
    buffer: list[str] = []
    for line in lines:
        if line.startswith("# "):
            started = True
            continue
        if not started or line.startswith("Source:") or not line:
            continue
        if line.startswith("<") or line.startswith("|") or line.startswith("* ") or line.startswith("- "):
            continue
        buffer.append(line)
        if len(" ".join(buffer)) >= 320:
            break
    summary = " ".join(buffer).strip()
    return summary[:320].rstrip() if summary else ""


def ensure_clean_output() -> None:
    if OUT_DIR.exists():
        shutil.rmtree(OUT_DIR)
    for directory in (RAW_DIR, PAGES_DIR, INVENTORY_DIR, SUMMARIES_DIR):
        directory.mkdir(parents=True, exist_ok=True)


def write_text(path: Path, text: str) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_text(text, encoding="utf-8")


def write_bytes(path: Path, data: bytes) -> None:
    path.parent.mkdir(parents=True, exist_ok=True)
    path.write_bytes(data)


def build_readme(manifest: list[dict], section_counts: dict[str, int]) -> str:
    lines = [
        "# AgentScope Case Study",
        "",
        "Generated from the live AgentScope docs exports on 2026-04-03.",
        "",
        "## Included Artifacts",
        "",
        "- `raw/`: original crawled exports from the documentation site.",
        "- `inventory/`: sitemap-derived URL inventory and generated manifest.",
        "- `pages/`: one markdown file per documentation page.",
        "- `summaries/`: section-level indexes and curated briefings.",
        "",
        "## Coverage",
        "",
        f"- Pages captured from sitemap: `{len(manifest)}`",
        f"- Top-level sections: `{len(section_counts)}`",
        "",
        "## Section Counts",
        "",
    ]
    for section, count in sorted(section_counts.items()):
        lines.append(f"- `{section}`: {count}")
    lines.extend(
        [
            "",
            "## Source Endpoints",
            "",
            f"- Sitemap: `{SITEMAP_URL}`",
            f"- Index export: `{LLMS_URL}`",
            f"- Full export: `{LLMS_FULL_URL}`",
            f"- OpenAPI: `{OPENAPI_URL}`",
            "",
            "See `summaries/overview.md` for the synthesized briefing.",
            "",
        ]
    )
    return "\n".join(lines)


def build_section_index(section: str, pages: list[dict]) -> str:
    lines = [
        f"# {section}",
        "",
        f"Pages in this section: {len(pages)}",
        "",
    ]
    for page in pages:
        lines.append(f"## {page['title']}")
        lines.append("")
        lines.append(f"- URL: {page['url']}")
        lines.append(f"- Path: `{page['path']}`")
        if page.get("description"):
            lines.append(f"- Index description: {page['description']}")
        if page.get("summary"):
            lines.append(f"- Extracted summary: {page['summary']}")
        lines.append("")
    return "\n".join(lines)


def main() -> None:
    ensure_clean_output()

    sitemap_text = fetch_text(SITEMAP_URL)
    llms_text = fetch_text(LLMS_URL)
    llms_full_text = fetch_text(LLMS_FULL_URL)
    openapi_bytes = fetch_bytes(OPENAPI_URL)

    write_text(RAW_DIR / "sitemap.xml", sitemap_text)
    write_text(RAW_DIR / "llms.txt", llms_text)
    write_text(RAW_DIR / "llms-full.txt", llms_full_text)
    write_bytes(RAW_DIR / "openapi.json", openapi_bytes)

    sitemap_entries = parse_sitemap(sitemap_text)
    index_map = parse_llms_index(llms_text)
    full_pages = parse_llms_full(llms_full_text)

    by_url = {entry["url"]: entry for entry in sitemap_entries}
    manifest = []
    by_section: dict[str, list[dict]] = defaultdict(list)

    for page in full_pages:
        sitemap_meta = by_url.get(page["url"], {})
        index_meta = index_map.get(page["url"], {})
        merged = {
            **page,
            "title": index_meta.get("title", page["title"]),
            "description": index_meta.get("description"),
            "lastmod": sitemap_meta.get("lastmod"),
            "summary": summarize_page(page["content"]),
        }
        relative_file = Path("pages") / merged["section"] / f"{merged['slug']}.md"
        target = OUT_DIR / relative_file
        frontmatter = [
            "---",
            f"title: {json.dumps(merged['title'])}",
            f"url: {json.dumps(merged['url'])}",
            f"path: {json.dumps(merged['path'])}",
            f"section: {json.dumps(merged['section'])}",
            f"lastmod: {json.dumps(merged.get('lastmod'))}",
            "---",
            "",
        ]
        write_text(target, "\n".join(frontmatter) + merged["content"])
        merged["file"] = str(relative_file)
        manifest.append(merged)
        by_section[merged["section"]].append(merged)

    section_counts = {section: len(pages) for section, pages in by_section.items()}
    write_text(OUT_DIR / "README.md", build_readme(manifest, section_counts))
    write_text(INVENTORY_DIR / "urls.json", json.dumps(sitemap_entries, indent=2) + "\n")
    write_text(INVENTORY_DIR / "manifest.json", json.dumps(manifest, indent=2) + "\n")

    for section, pages in sorted(by_section.items()):
        sorted_pages = sorted(pages, key=lambda item: item["path"])
        write_text(SUMMARIES_DIR / f"{section}.md", build_section_index(section, sorted_pages))


if __name__ == "__main__":
    main()

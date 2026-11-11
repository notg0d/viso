"""Check local Markdown links/anchors/assets without network or dependencies."""

import os
import re
import sys
import unicodedata
from pathlib import Path
from urllib.parse import unquote, urlsplit

ROOT = Path(__file__).resolve().parents[1]
IGNORED = {
    ".git", ".venv", ".viso", ".fixtures", ".pytest_cache", "__pycache__",
    "node_modules", "dist", "bin", "test-results", "playwright-report",
}


def markdown_files(root: Path):
    for directory, folders, files in os.walk(root, followlinks=False):
        folders[:] = sorted(folder for folder in folders if folder not in IGNORED)
        for name in sorted(files):
            if name.endswith(".md"):
                yield Path(directory) / name


def prose(text: str):
    """Keep line numbers, but ignore fenced examples rather than validate them."""
    fence = None
    for number, line in enumerate(text.splitlines(), 1):
        marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
        if marker:
            value = marker.group(1)
            if fence is None:
                fence = value
            elif value[0] == fence[0] and len(value) >= len(fence):
                fence = None
            continue
        if fence is None:
            yield number, line


def anchors(text: str) -> set[str]:
    result = set()
    for _, line in prose(text):
        result.update(re.findall(r'<a\s+[^>]*(?:id|name)=["\']([^"\']+)["\']', line))
        heading = re.match(r"^\s{0,3}#{1,6}\s+(.+?)(?:\s+#+)?\s*$", line)
        if not heading:
            continue
        label = re.sub(r"<[^>]+>", "", heading.group(1))
        label = re.sub(r"!?\[([^\]]+)\]\([^)]+\)", r"\1", label).lower()
        slug = "".join(
            char for char in label
            if char in " -_" or unicodedata.category(char)[0] in "LMN"
        ).replace(" ", "-")
        candidate, duplicate = slug, 0
        while candidate in result:
            duplicate += 1
            candidate = f"{slug}-{duplicate}"
        result.add(candidate)
    return result


def links(text: str):
    for number, line in prose(text):
        # Match the target rather than label, including nested linked badges.
        for match in re.finditer(r"\]\((<[^>]+>|[^)\n]+)\)", line):
            target = match.group(1).strip()
            yield number, target[1:-1] if target.startswith("<") else (target.split()[0] if target else "")
        for match in re.finditer(r'(?:href|src)=["\']([^"\']+)["\']', line):
            yield number, match.group(1)


def check(root: Path = ROOT) -> int:
    files = list(markdown_files(root))
    cache, failures, checked = {}, [], 0
    for source in files:
        text = source.read_text(encoding="utf-8-sig")
        for number, link in links(text):
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc:
                continue
            checked += 1
            target = (source.parent / unquote(parsed.path)).resolve() if parsed.path else source
            error = None
            if not target.exists():
                error = "missing file or directory"
            elif parsed.fragment:
                if not target.is_file() or target.suffix.lower() != ".md":
                    error = "anchor target is not Markdown"
                else:
                    if target not in cache:
                        cache[target] = anchors(target.read_text(encoding="utf-8-sig"))
                    if unquote(parsed.fragment) not in cache[target]:
                        error = "missing heading anchor"
            if error:
                failures.append(f"{source.relative_to(root)}:{number}: {error}: {link}")
    if failures:
        print("\n".join(failures), file=sys.stderr)
        print(f"Documentation check failed: {len(failures)} broken local targets.", file=sys.stderr)
        return 1
    print(f"Documentation check passed: {len(files)} Markdown files, {checked} local links/assets.")
    print("External URLs are not fetched; ignored/generated trees are excluded.")
    return 0


if __name__ == "__main__":
    raise SystemExit(check())

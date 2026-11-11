"""Keep bundled guides local; pin source-only references to the build commit."""

from pathlib import Path
import re
import sys
from urllib.parse import quote, unquote, urlsplit


def rewrite_documentation(root: Path, bundle: Path, commit: str) -> int:
    root, bundle = root.resolve(), bundle.resolve()
    if not re.fullmatch(r"[0-9a-f]{40}", commit):
        raise ValueError("A complete Git source commit is required for documentation links.")
    changed = 0
    for document in sorted((bundle / "docs").rglob("*.md")):
        def reference(link: str) -> str:
            nonlocal changed
            parsed = urlsplit(link)
            if parsed.scheme or parsed.netloc or not parsed.path:
                return link
            local = (document.parent / unquote(parsed.path)).resolve()
            if local.is_relative_to(bundle) and local.exists():
                return link
            source = (root / document.relative_to(bundle).parent / unquote(parsed.path)).resolve()
            if not source.is_relative_to(root) or not source.exists():
                raise ValueError(f"Invalid source-only documentation target in {document.name}: {link}")
            kind = "tree" if source.is_dir() else "blob"
            result = f"https://github.com/notg0d/viso/{kind}/{commit}/" + quote(source.relative_to(root).as_posix(), safe="/")
            if parsed.fragment:
                result += "#" + quote(unquote(parsed.fragment), safe="-._~")
            changed += 1
            return result

        def markdown(match: re.Match) -> str:
            raw = match.group(1)
            if raw.startswith("<"):
                close = raw.index(">")
                return "](<" + reference(raw[1:close]) + ">" + raw[close + 1:] + ")"
            parts = raw.split(maxsplit=1)
            if not parts:
                return match.group(0)
            return "](" + reference(parts[0]) + (" " + parts[1] if len(parts) > 1 else "") + ")"

        lines, fence = [], None
        for line in document.read_text(encoding="utf-8-sig").splitlines(keepends=True):
            marker = re.match(r"^\s{0,3}(`{3,}|~{3,})", line)
            if marker:
                value = marker.group(1)
                if fence is None:
                    fence = value
                elif value[0] == fence[0] and len(value) >= len(fence):
                    fence = None
            elif fence is None:
                line = re.sub(r"\]\(([^)\n]+)\)", markdown, line)
                line = re.sub(r"((?:href|src)=)([\"'])([^\"']+)([\"'])", lambda match: match[1] + match[2] + reference(match[3]) + match[4], line)
            lines.append(line)
        document.write_text("".join(lines), encoding="utf-8")
    return changed


if __name__ == "__main__":
    if len(sys.argv) != 4:
        raise SystemExit("Usage: package-installer-docs.py ROOT BUNDLE SOURCE_COMMIT")
    changed = rewrite_documentation(Path(sys.argv[1]), Path(sys.argv[2]), sys.argv[3])
    print(f"Bundled documentation: {changed} source-only references pinned to the source commit.")

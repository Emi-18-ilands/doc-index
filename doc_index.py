#!/usr/bin/env python3
"""doc_index - walk a folder of documents and write an index of what is inside.

Standard library only. No dependencies.

The point is not to list files (your OS does that). It is to answer, without
opening anything: what are these documents, what is each one about, and which
files talk about the same thing.

Outputs Markdown (default) or JSON, and can build a reverse index that maps
each significant term to the files that contain it.
"""
from __future__ import annotations

import argparse
import json
import os
import re
import sys
from collections import Counter
from datetime import datetime, timezone

# ---------------------------------------------------------------------------
# File categories
# ---------------------------------------------------------------------------

TEXT_EXTS = {
    ".txt": "text",
    ".md": "markdown",
    ".markdown": "markdown",
    ".rst": "text",
    ".log": "log",
    ".csv": "csv",
    ".tsv": "csv",
    ".json": "json",
    ".jsonl": "jsonl",
    ".ndjson": "jsonl",
    ".yaml": "yaml",
    ".yml": "yaml",
    ".toml": "toml",
    ".ini": "ini",
    ".cfg": "ini",
    ".html": "html",
    ".htm": "html",
    ".xml": "xml",
    ".py": "code",
    ".js": "code",
    ".ts": "code",
    ".sh": "code",
    ".rb": "code",
    ".go": "code",
    ".rs": "code",
    ".java": "code",
    ".c": "code",
    ".h": "code",
    ".css": "code",
    ".sql": "code",
}

# Binary formats we can *label* but not read. Kept honest: no fake extraction.
BINARY_EXTS = {
    ".pdf": "pdf",
    ".doc": "word",
    ".docx": "word",
    ".xls": "excel",
    ".xlsx": "excel",
    ".ppt": "slides",
    ".pptx": "slides",
    ".png": "image",
    ".jpg": "image",
    ".jpeg": "image",
    ".gif": "image",
    ".webp": "image",
    ".bmp": "image",
    ".tif": "image",
    ".tiff": "image",
    ".svg": "image",
    ".mp3": "audio",
    ".wav": "audio",
    ".flac": "audio",
    ".ogg": "audio",
    ".m4a": "audio",
    ".mp4": "video",
    ".mov": "video",
    ".avi": "video",
    ".mkv": "video",
    ".webm": "video",
    ".zip": "archive",
    ".tar": "archive",
    ".gz": "archive",
    ".7z": "archive",
    ".rar": "archive",
}

SKIP_DIRS = {
    ".git", ".hg", ".svn", "__pycache__", "node_modules", ".venv", "venv",
    ".mypy_cache", ".pytest_cache", ".idea", ".vscode", ".tox", "dist",
    "build", ".cache", ".next", "target", ".DS_Store",
}

STOPWORDS = set("""
a an the and or but if then else for of to in on at by with from as is are was
were be been being this that these those it its it's they them their there here
you your yours we our ours he she his her him i me my mine not no nor so than
too very can could should would may might must will shall do does did done have
has had having about into over under out up down off again once only own same
such more most other some any each few both all any how what when where which
who whom why also just like get got make made use used using one two three
new old first last next previous via per within without across between
""".split())

WORD_RE = re.compile(r"[A-Za-z][A-Za-z0-9_'-]{2,}")


def is_probably_binary(path: str) -> bool:
    try:
        with open(path, "rb") as fh:
            chunk = fh.read(4096)
    except OSError:
        return False
    if b"\x00" in chunk:
        return True
    if not chunk:
        return False
    # A high ratio of non-text control bytes is a strong binary signal.
    text_bytes = bytes(range(0x20, 0x7F)) + b"\n\r\t\f\b\x1b"
    nontext = sum(1 for b in chunk if b not in text_bytes)
    return nontext / len(chunk) > 0.30


def read_text(path: str, limit: int = 2_000_000):
    for enc in ("utf-8", "utf-8-sig", "latin-1"):
        try:
            with open(path, "r", encoding=enc) as fh:
                data = fh.read(limit)
            return data, enc
        except UnicodeDecodeError:
            continue
        except OSError:
            return None, None
    return None, None


def size_str(n: int) -> str:
    if n < 1024:
        return f"{n} B"
    if n < 1024 * 1024:
        return f"{n/1024:.1f} KB"
    return f"{n/(1024*1024):.1f} MB"


def title_from_text(cat: str, text: str) -> str:
    stripped = text.lstrip()
    if cat == "markdown":
        for line in text.splitlines():
            line = line.strip()
            if line.startswith("#"):
                return line.lstrip("#").strip() or "(untitled)"
    if cat == "html":
        m = re.search(r"<title[^>]*>(.*?)</title>", text, re.I | re.S)
        if m and m.group(1).strip():
            return re.sub(r"\s+", " ", m.group(1)).strip()
        m = re.search(r"<h1[^>]*>(.*?)</h1>", text, re.I | re.S)
        if m:
            return re.sub(r"\s+", " ", re.sub(r"<[^>]+>", "", m.group(1))).strip()
    if cat == "json":
        return "(json document)"
    for line in stripped.splitlines():
        line = line.strip()
        if line:
            return re.sub(r"[\t ]+", " ", line)[:100]
    return "(empty)"


def texts_from_json(data: str, max_items: int = 2000):
    """Flatten a JSON value into a list of key names and string leaves."""
    try:
        obj = json.loads(data)
    except (ValueError, TypeError):
        return None
    out = []

    def walk(node, depth=0):
        if len(out) >= max_items:
            return
        if isinstance(node, dict):
            for k, v in node.items():
                if isinstance(k, str):
                    out.append(k)
                walk(v, depth + 1)
        elif isinstance(node, list):
            for v in node[:100]:
                walk(v, depth + 1)
        elif isinstance(node, str):
            out.append(node)
        elif isinstance(node, (int, float, bool)) or node is None:
            pass

    walk(obj)
    return out


def keywords_for(text: str, n: int = 8):
    words = [w.lower() for w in WORD_RE.findall(text)]
    counts = Counter(w for w in words if w not in STOPWORDS and len(w) > 2)
    return [w for w, _ in counts.most_common(n)]


def describe(path: str, root: str):
    rel = os.path.relpath(path, root)
    ext = os.path.splitext(path)[1].lower()
    try:
        st = os.stat(path)
    except OSError:
        return None
    info = {
        "path": rel,
        "ext": ext,
        "size": st.st_size,
        "size_label": size_str(st.st_size),
        "modified": datetime.fromtimestamp(st.st_mtime, tz=timezone.utc)
        .isoformat()
        .replace("+00:00", "Z"),
    }

    cat = TEXT_EXTS.get(ext)
    if cat is None and ext in BINARY_EXTS:
        info.update(kind=BINARY_EXTS[ext], readable=False, title="")
        return info
    if cat is None:
        cat = "binary" if is_probably_binary(path) else "text"

    if cat == "binary" or (ext in BINARY_EXTS):
        info.update(kind=BINARY_EXTS.get(ext, "binary"), readable=False, title="")
        return info
    if is_probably_binary(path):
        info.update(kind="binary", readable=False, title="")
        return info

    text, enc = read_text(path)
    if text is None:
        kind = "binary" if os.access(path, os.R_OK) else "unreadable"
        info.update(kind=kind, readable=False, title="")
        return info

    lines = text.splitlines()
    info.update(
        kind=cat,
        readable=True,
        encoding=enc,
        lines=len(lines),
        words=len(WORD_RE.findall(text)),
        chars=len(text),
        title=title_from_text(cat, text),
    )

    if cat == "csv":
        first = next((l for l in lines if l.strip()), "")
        delim = "\t" if "\t" in first else ";" if ";" in first else "|" if "|" in first else ","
        info["columns"] = [c.strip() for c in first.split(delim)] if first else []

    if cat == "markdown":
        heads = [l.strip().lstrip("#").strip() for l in lines if l.strip().startswith("#")]
        info["headings"] = heads[:20]

    if cat == "json":
        flat = texts_from_json(text)
        if flat is not None:
            info["keys"] = sorted({k for k in flat if isinstance(k, str) and k and " " not in k})[:30]

    kw_source = text
    if cat == "json":
        flat = texts_from_json(text)
        if flat is not None:
            kw_source = " ".join(str(x) for x in flat)
    info["keywords"] = keywords_for(kw_source)
    return info


def discover(root: str, recursive: bool, include, exclude):
    files = []
    for dirpath, dirnames, filenames in os.walk(root):
        dirnames[:] = [d for d in dirnames if d not in SKIP_DIRS and not d.startswith(".")]
        for name in sorted(filenames):
            if name.startswith("."):
                continue
            path = os.path.join(dirpath, name)
            rel = os.path.relpath(path, root)
            # Never open FIFOs, sockets, devices or broken symlinks: opening a
            # FIFO with no writer blocks forever.
            if not os.path.isfile(path):
                continue
            if include and not any(re.match(p, rel) or re.match(p, name) for p in include):
                continue
            if exclude and any(re.match(p, rel) for p in exclude):
                continue
            files.append(path)
        if not recursive:
            break
    return files


def build_index(root: str, infos):
    files = [i for i in infos if i]
    term_files = {}
    for i in files:
        for k in i.get("keywords", []):
            term_files.setdefault(k, []).append(i["path"])
    # Keep terms that appear in 2+ files (shared topics) or that are rare but
    # strong; a term in every file is noise, a term in one file is just local.
    total = max(1, len(files))
    shared = {}
    for term, paths in term_files.items():
        npaths = len(paths)
        if npaths < 2:
            continue
        # A term in every file of a larger folder is the folder's theme, not a
        # distinguishing topic. With two files, the shared term IS the link.
        if npaths == total and total >= 3:
            continue
        shared[term] = sorted(paths)
    shared = dict(
        sorted(shared.items(), key=lambda kv: (-len(kv[1]), kv[0]))[:40]
    )
    return {
        "root": os.path.abspath(root),
        "generated": datetime.now(timezone.utc).isoformat().replace("+00:00", "Z"),
        "count": len(files),
        "files": files,
        "shared_terms": shared,
    }


def render_markdown(index):
    out = []
    out.append("# Document index")
    out.append("")
    out.append(f"- Root: `{index['root']}`")
    out.append(f"- Files: {index['count']}")
    out.append(f"- Generated: {index['generated']}")
    out.append("")
    out.append("## Overview")
    out.append("")
    out.append("| File | Kind | Size | Lines | Title |")
    out.append("| --- | --- | ---: | ---: | --- |")
    for f in index["files"]:
        title = (f.get("title") or "").replace("|", "\\|")[:70]
        lines = f.get("lines", "")
        out.append(
            f"| `{f['path']}` | {f.get('kind','?')} | {f['size_label']} | {lines} | {title} |"
        )
    out.append("")
    if index["shared_terms"]:
        out.append("## Shared terms")
        out.append("")
        out.append("Terms that appear in more than one document, most shared first:")
        out.append("")
        for term, paths in index["shared_terms"].items():
            out.append(f"- **{term}** -> {', '.join('`%s`' % p for p in paths)}")
        out.append("")
    out.append("## Documents")
    out.append("")
    for f in index["files"]:
        out.append(f"### `{f['path']}`")
        out.append("")
        bits = [f"*{f.get('kind','?')}*", f["size_label"]]
        if f.get("words"):
            bits.append(f"{f['words']} words")
        if f.get("lines"):
            bits.append(f"{f['lines']} lines")
        out.append(" — ".join(bits))
        out.append("")
        if f.get("title") and f.get("readable"):
            out.append(f"**Title:** {f['title']}")
            out.append("")
        if f.get("columns"):
            out.append(f"**Columns:** {', '.join('`%s`' % c for c in f['columns'])}")
            out.append("")
        if f.get("headings"):
            out.append("**Headings:** " + " / ".join(f["headings"][:12]))
            out.append("")
        if f.get("keys"):
            out.append(f"**Keys:** {', '.join('`%s`' % k for k in f['keys'][:15])}")
            out.append("")
        if f.get("keywords"):
            out.append("**Keywords:** " + ", ".join(f["keywords"]))
            out.append("")
        if not f.get("readable"):
            out.append("_Not read (binary or unreadable format)._")
            out.append("")
    return "\n".join(out).rstrip() + "\n"


def main(argv=None):
    p = argparse.ArgumentParser(
        description="Index a folder of documents and describe what is inside."
    )
    p.add_argument("folder", help="folder to scan")
    p.add_argument("--out", "-o", help="write output to a file instead of stdout")
    p.add_argument("--json", action="store_true", help="emit JSON instead of Markdown")
    p.add_argument("--no-recursive", action="store_true", help="do not descend into subfolders")
    p.add_argument("--include", action="append", default=[], help="regex; only matching files")
    p.add_argument("--exclude", action="append", default=[], help="regex; skip matching files")
    p.add_argument("--keywords", type=int, default=8, help="keywords per file (default 8)")
    p.add_argument("--no-shared", action="store_true", help="omit the shared-term index")
    args = p.parse_args(argv)

    root = args.folder
    if not os.path.isdir(root):
        sys.stderr.write(f"doc_index: not a folder: {root}\n")
        return 2

    files = discover(root, not args.no_recursive, args.include, args.exclude)
    infos = []
    for path in files:
        try:
            info = describe(path, root)
        except Exception as exc:  # never let one bad file kill the run
            info = {
                "path": os.path.relpath(path, root),
                "kind": "error",
                "size": 0,
                "size_label": "-",
                "modified": "",
                "readable": False,
                "title": "",
                "error": str(exc),
            }
        if info:
            info["keywords"] = info.get("keywords", [])[: args.keywords]
            infos.append(info)

    index = build_index(root, infos)
    if args.no_shared:
        index["shared_terms"] = {}

    output = json.dumps(index, indent=2) if args.json else render_markdown(index)
    if args.out:
        with open(args.out, "w", encoding="utf-8") as fh:
            fh.write(output)
        sys.stderr.write(f"doc_index: wrote {args.out} ({index['count']} files)\n")
    else:
        sys.stdout.write(output)
    return 0


if __name__ == "__main__":
    raise SystemExit(main())

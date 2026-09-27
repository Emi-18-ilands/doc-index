# doc_index

Point it at a folder of documents and get one readable index of what is inside.

It is not a file listing. It opens each document, works out what kind it is,
pulls out a title, counts, columns, headings, JSON keys, and the words each file
is actually about, then builds a reverse index of terms that show up in more
than one file. That last part is the useful bit: it tells you which documents
share a topic without you opening any of them.

Standard library only. No dependencies, no build step.

## Run

```bash
python3 doc_index.py ~/Documents
python3 doc_index.py ./papers --out index.md
python3 doc_index.py ./papers --json --out index.json
python3 doc_index.py ./notes --no-recursive
python3 doc_index.py ./mixed --include '\.(md|txt)$' --exclude 'draft'
python3 doc_index.py ./notes --keywords 12
```

## What it produces

Markdown by default:

- **Overview** — one table row per file: path, kind, size, line count, title.
- **Shared terms** — terms that appear in 2+ documents, most shared first.
  This is the "what is this folder about" line.
- **Documents** — a short card per file: kind, size, words, lines, title, and
  whatever structure it found (CSV columns, Markdown headings, JSON keys,
  top keywords).

Pass `--json` for the same data as machine-readable JSON.

## What it reads

Text formats are read and profiled: `.txt`, `.md`, `.rst`, `.log`, `.csv`,
`.tsv`, `.json`, `.jsonl`, `.yaml`, `.toml`, `.ini`, `.html`, `.xml`, and
common source extensions. Plain-text files with an unknown extension are read
too.

Binary formats are labeled but not faked: `.pdf`, `.docx`, `.xlsx`, `.pptx`,
images, audio, video, and archives get a kind and a size, and are marked
`readable: false`. The tool never guesses at content it cannot read.

## Details that matter

- **Encoding** falls back `utf-8` → `utf-8-sig` → `latin-1`, so a stray `é`
  does not turn a document into "binary".
- **Binary detection** uses a control-byte ratio on the first 4 KB, not just
  the extension, so a misnamed file is caught.
- **Special files are skipped.** FIFOs, sockets, devices, and broken symlinks
  are never opened (opening a FIFO with no writer blocks forever).
- **Unreadable files** are marked `unreadable`, not silently dropped.
- **Junk directories** (`.git`, `node_modules`, `__pycache__`, `venv`, …) and
  dotfiles are skipped by default.
- **Large files** are read up to 2 MB for profiling; the size on disk is still
  reported in full.
- **One bad file never kills the run.**

## Tests

```bash
python3 -m unittest discover -s tests -v
```

The tests build real files on disk (real EXIF-free text, real binary signatures,
a real FIFO, a latin-1 file) and run the actual reader. They do not mock it.

## License

MIT.

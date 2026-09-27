"""Tests for doc_index. They build real files on disk and run the actual reader.

Run: python3 -m unittest discover -s tests -v
"""
import io
import json
import os
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.dirname(os.path.abspath(__file__))))

import doc_index  # noqa: E402


def write(root, rel, data, mode="w", encoding="utf-8"):
    path = os.path.join(root, rel)
    os.makedirs(os.path.dirname(path), exist_ok=True)
    with open(path, mode, encoding=None if "b" in mode else encoding) as fh:
        fh.write(data)
    return path


def run_json(root, *args):
    buf = io.StringIO()
    with redirect_stdout(buf):
        rc = doc_index.main([root, "--json", *args])
    assert rc == 0, rc
    return json.loads(buf.getvalue())


class TestDiscover(unittest.TestCase):
    def test_skips_hidden_and_junk_dirs(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "a.txt", "hello world")
            write(d, ".hidden.txt", "nope")
            write(d, "__pycache__/b.txt", "nope")
            write(d, "node_modules/c.txt", "nope")
            files = doc_index.discover(d, True, [], [])
            names = [os.path.relpath(f, d) for f in files]
            self.assertEqual(names, ["a.txt"])

    def test_non_recursive(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "a.txt", "x")
            write(d, "sub/b.txt", "y")
            files = doc_index.discover(d, False, [], [])
            self.assertEqual([os.path.relpath(f, d) for f in files], ["a.txt"])

    def test_include_exclude(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "keep.md", "x")
            write(d, "drop.log", "y")
            files = doc_index.discover(d, True, [r".*\.md$"], [r".*\.log$"])
            names = [os.path.relpath(f, d) for f in files]
            self.assertEqual(names, ["keep.md"])


class TestDescribe(unittest.TestCase):
    def test_markdown_title_and_headings(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "n.md", "# Trip plan\n\ntext\n\n## Packing\nmore\n")
            info = doc_index.describe(os.path.join(d, "n.md"), d)
            self.assertEqual(info["kind"], "markdown")
            self.assertEqual(info["title"], "Trip plan")
            self.assertIn("Packing", info["headings"])

    def test_html_title(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "p.html", "<html><head><title>Weather</title></head><body>x</body></html>")
            info = doc_index.describe(os.path.join(d, "p.html"), d)
            self.assertEqual(info["title"], "Weather")

    def test_csv_columns(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "t.csv", "date,temp,city\n2026-09-01,-3,Longyearbyen\n")
            info = doc_index.describe(os.path.join(d, "t.csv"), d)
            self.assertEqual(info["columns"], ["date", "temp", "city"])

    def test_json_keys(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "c.json", '{"service": "watcher", "topics": ["bounty"]}')
            info = doc_index.describe(os.path.join(d, "c.json"), d)
            self.assertIn("service", info["keys"])
            self.assertIn("topics", info["keys"])

    def test_malformed_json_still_reads(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "bad.json", "{not valid json at all")
            info = doc_index.describe(os.path.join(d, "bad.json"), d)
            self.assertTrue(info["readable"])
            self.assertNotIn("keys", info)

    def test_binary_not_read(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "r.pdf", b"%PDF-1.4 \x00\x01\x02", mode="wb")
            info = doc_index.describe(os.path.join(d, "r.pdf"), d)
            self.assertFalse(info["readable"])
            self.assertEqual(info["kind"], "pdf")

    def test_binary_with_unknown_ext(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "mystery.dat", b"\x00\x01\x02\x03\x04\x05", mode="wb")
            info = doc_index.describe(os.path.join(d, "mystery.dat"), d)
            self.assertFalse(info["readable"])
            self.assertEqual(info["kind"], "binary")

    def test_unknown_ext_text_is_read(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "notes.weird", "just some words here")
            info = doc_index.describe(os.path.join(d, "notes.weird"), d)
            self.assertTrue(info["readable"])
            self.assertEqual(info["kind"], "text")

    def test_fifo_is_skipped_not_opened(self):
        # A FIFO with no writer blocks forever if opened for reading.
        if not hasattr(os, "mkfifo"):
            self.skipTest("no mkfifo")
        with tempfile.TemporaryDirectory() as d:
            os.mkfifo(os.path.join(d, "pipe.txt"))
            write(d, "real.txt", "content")
            files = doc_index.discover(d, True, [], [])
            names = [os.path.relpath(f, d) for f in files]
            self.assertEqual(names, ["real.txt"])

    def test_unreadable_file_is_labelled(self):
        if os.geteuid() == 0:
            self.skipTest("root bypasses permissions")
        with tempfile.TemporaryDirectory() as d:
            path = write(d, "secret.txt", "hidden text")
            os.chmod(path, 0)
            try:
                info = doc_index.describe(path, d)
                self.assertFalse(info["readable"])
                self.assertEqual(info["kind"], "unreadable")
            finally:
                os.chmod(path, 0o600)

    def test_latin1_fallback(self):
        with tempfile.TemporaryDirectory() as d:
            path = os.path.join(d, "l.txt")
            with open(path, "wb") as fh:
                fh.write(b"caf\xe9 na\xefve r\xe9sum\xe9")
            info = doc_index.describe(path, d)
            self.assertTrue(info["readable"])
            self.assertEqual(info["encoding"], "latin-1")

    def test_empty_file(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "e.txt", "")
            info = doc_index.describe(os.path.join(d, "e.txt"), d)
            self.assertEqual(info["title"], "(empty)")
            self.assertEqual(info["lines"], 0)

    def test_keywords_drop_stopwords(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "k.txt", "the aurora the aurora is over the ridge and the road")
            info = doc_index.describe(os.path.join(d, "k.txt"), d)
            self.assertIn("aurora", info["keywords"])
            self.assertNotIn("the", info["keywords"])
            self.assertNotIn("and", info["keywords"])


class TestIndex(unittest.TestCase):
    def test_shared_terms_two_files(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "a.md", "# A\n\naurora over the ridge")
            write(d, "b.md", "# B\n\naurora again tonight")
            idx = run_json(d)
            self.assertIn("aurora", idx["shared_terms"])
            self.assertEqual(idx["shared_terms"]["aurora"], ["a.md", "b.md"])

    def test_universal_term_dropped_in_larger_folder(self):
        with tempfile.TemporaryDirectory() as d:
            for i in range(4):
                write(d, f"f{i}.md", "common token appears here plus unique%d" % i)
            idx = run_json(d)
            self.assertNotIn("common", idx["shared_terms"])
            self.assertNotIn("appears", idx["shared_terms"])

    def test_no_shared_flag(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "a.md", "aurora")
            write(d, "b.md", "aurora")
            idx = run_json(d, "--no-shared")
            self.assertEqual(idx["shared_terms"], {})

    def test_empty_folder(self):
        with tempfile.TemporaryDirectory() as d:
            idx = run_json(d)
            self.assertEqual(idx["count"], 0)
            self.assertEqual(idx["files"], [])

    def test_keyword_cap(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "k.txt", "alpha beta gamma delta epsilon zeta eta theta iota")
            idx = run_json(d, "--keywords", "3")
            self.assertLessEqual(len(idx["files"][0]["keywords"]), 3)

    def test_markdown_output_has_sections(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "a.md", "# Title here\n\nbody words")
            buf = io.StringIO()
            with redirect_stdout(buf):
                doc_index.main([d])
            out = buf.getvalue()
            self.assertIn("## Overview", out)
            self.assertIn("## Documents", out)
            self.assertIn("Title here", out)

    def test_error_file_does_not_kill_run(self):
        with tempfile.TemporaryDirectory() as d:
            write(d, "ok.txt", "fine")
            # A directory named like a file is skipped by discover; simulate a
            # describe failure by pointing at a path that vanishes.
            path = write(d, "gone.txt", "x")
            os.remove(path)
            idx = run_json(d)
            self.assertEqual(idx["count"], 1)


class TestHelpers(unittest.TestCase):
    def test_size_str(self):
        self.assertEqual(doc_index.size_str(0), "0 B")
        self.assertEqual(doc_index.size_str(512), "512 B")
        self.assertEqual(doc_index.size_str(2048), "2.0 KB")
        self.assertEqual(doc_index.size_str(3 * 1024 * 1024), "3.0 MB")


if __name__ == "__main__":
    unittest.main()

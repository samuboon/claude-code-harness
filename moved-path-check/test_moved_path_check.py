# -*- coding: utf-8 -*-
"""Tests for moved_path_check.py. Each test builds a small git repository in a temporary folder
(removed afterwards, also on failure) and runs the checker on it.

    python test_moved_path_check.py
"""
import contextlib
import io
import json
import os
import shutil
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import moved_path_check as M  # noqa: E402

# the tester's own git settings (a global excludes file, autocrlf) must not change the results
os.environ["GIT_CONFIG_GLOBAL"] = os.devnull
os.environ["GIT_CONFIG_NOSYSTEM"] = "1"
os.environ["XDG_CONFIG_HOME"] = os.path.join(tempfile.gettempdir(), "mpc-test-no-such-dir")
ENV = dict(os.environ, GIT_AUTHOR_NAME="t", GIT_AUTHOR_EMAIL="t@example.com", GIT_COMMITTER_NAME="t",
           GIT_COMMITTER_EMAIL="t@example.com", GIT_CONFIG_NOSYSTEM="1")


class Repo:
    def __init__(self, root):
        self.root = Path(root)
        self.n = 0
        self.git("init", "-q", "-b", "main")
        self.git("config", "core.autocrlf", "false")

    def git(self, *args):
        env = dict(ENV, GIT_AUTHOR_DATE="2024-01-%02dT12:00:00" % (self.n + 1),
                   GIT_COMMITTER_DATE="2024-01-%02dT12:00:00" % (self.n + 1))
        r = subprocess.run(["git", "-C", str(self.root)] + list(args), capture_output=True, text=True,
                           encoding="utf-8", env=env)
        if r.returncode:
            raise RuntimeError(r.stderr)
        return r.stdout

    def write(self, path, text="x\n"):
        f = self.root / path
        f.parent.mkdir(parents=True, exist_ok=True)
        f.write_text(text, encoding="utf-8", newline="\n")

    def rm(self, path):
        self.git("rm", "-r", "-q", path)

    def mv(self, a, b):
        (self.root / b).parent.mkdir(parents=True, exist_ok=True)
        self.git("mv", a, b)

    def commit(self, msg="c"):
        self.git("add", "-A")
        self.git("commit", "-q", "-m", msg)
        self.n += 1
        return self.git("rev-parse", "HEAD").strip()

    def check(self, paths=None, **kw):
        return M.Checker(str(self.root), **kw).run(paths)


def codes(findings):
    return sorted((f.doc, f.line, f.code) for f in findings)


class Base(unittest.TestCase):
    def setUp(self):
        self.tmp = tempfile.mkdtemp(prefix="mpc-test-")
        self.r = Repo(self.tmp)

    def tearDown(self):
        shutil.rmtree(self.tmp, ignore_errors=True)


class History(Base):
    def test_git_mv_is_moved(self):
        self.r.write("scripts/build.sh", "echo build\n")
        self.r.commit()
        self.r.mv("scripts/build.sh", "tools/build.sh")
        self.r.write("README.md", "Run `scripts/build.sh`.\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual(codes(f), [("README.md", 1, "MOVED")])
        self.assertEqual(f[0].target, "tools/build.sh")
        self.assertEqual(f[0].date, "2024-01-02")
        self.assertEqual(f[0].level, "error")

    def test_moved_and_edited_same_name(self):
        self.r.write("src/app.py", "a = 1\n")
        self.r.commit()
        self.r.rm("src/app.py")
        self.r.write("lib/app.py", "a = 2\nb = 3\n")
        self.r.write("README.md", "See `src/app.py`.\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.code, x.target) for x in f], [("MOVED", "lib/app.py")])

    def test_one_out_one_in_same_extension(self):
        self.r.write("src/old_name.py", "a = 1\n")
        self.r.write("src/keep.py", "k\n")
        self.r.commit()
        self.r.rm("src/old_name.py")
        self.r.write("src/new_name.py", "completely different\n")
        self.r.write("README.md", "See `src/old_name.py`.\n")
        self.r.commit()
        self.assertEqual([(x.code, x.target) for x in self.r.check()], [("MOVED", "src/new_name.py")])

    def test_other_extension_same_stem(self):
        self.r.write("clis/ask.test.ts", "a\n")
        self.r.write("clis/b.ts", "b\n")
        self.r.commit()
        self.r.rm("clis/ask.test.ts")
        self.r.rm("clis/b.ts")
        self.r.write("clis/ask.test.js", "rewritten\n")
        self.r.write("clis/c.js", "c\n")
        self.r.write("README.md", "`clis/ask.test.ts`\n")
        self.r.commit()
        self.assertEqual([(x.code, x.target) for x in self.r.check()], [("MOVED", "clis/ask.test.js")])

    def test_one_out_one_in_other_folder_not_paired(self):
        self.r.write(".claude/settings.local.json", "{\"a\": 1}\n")
        self.r.write("k", "k\n")
        self.r.commit()
        self.r.rm(".claude/settings.local.json")
        self.r.write(".mcp.json", "{\"servers\": {}}\n")
        self.r.write("docs/a.md", "[s](../.claude/settings.local.json)\n")
        self.r.commit()
        self.assertEqual([(x.code, x.target) for x in self.r.check()], [("DELETED", None)])

    def test_git_rename_detection_used_for_unpaired(self):
        body = "".join("line %d of a long enough file\n" % i for i in range(40))
        self.r.write("a/one.txt", body)
        self.r.write("a/two.py", "print(1)\n" * 30)
        self.r.commit()
        self.r.rm("a/one.txt")
        self.r.rm("a/two.py")
        self.r.write("b/uno.txt", body + "one more line\n")
        self.r.write("b/dos.py", "print(1)\n" * 30 + "print(2)\n")
        self.r.write("README.md", "See `a/one.txt`.\n")
        self.r.commit()
        self.assertEqual([(x.code, x.target) for x in self.r.check()], [("MOVED", "b/uno.txt")])

    def test_deleted(self):
        self.r.write("setup.py", "x\n")
        self.r.write("keep.txt")
        self.r.commit()
        self.r.rm("setup.py")
        sha = self.r.commit()
        self.r.write("README.md", "Run `python setup.py install`\n\n```\npip install -e .\n```\n"
                                  "Also `setup.py`, which is [here](setup.py).\n")
        self.r.commit()
        f = self.r.check()
        # a bare name in backticks is not judged (usually the reader's file); a link is
        self.assertEqual([(x.line, x.code, x.kind) for x in f], [(6, "DELETED", "link")])
        self.assertEqual(f[0].sha, sha[:12])

    def test_deleted_with_one_file_of_that_name_elsewhere(self):
        self.r.write("tests/unit/test_app.py", "old\n")
        self.r.write("k", "k\n")
        self.r.commit()
        self.r.write("tests/unit/server/test_app.py", "new, written again\n")
        self.r.commit()
        self.r.rm("tests/unit/test_app.py")
        self.r.write("README.md", "`tests/unit/test_app.py`\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.code, x.level, x.target) for x in f],
                         [("DELETED", "error", "tests/unit/server/test_app.py")])
        self.assertIn("the only file of that name now is", M.message(f[0]))

    def test_never_existed_is_not_reported(self):
        self.r.write("README.md", "Create `src/components/Button.js` in your app. See [x](docs/nope.md).\n")
        self.r.commit()
        self.assertEqual(self.r.check(), [])

    def test_existing_path_is_fine(self):
        self.r.write("src/a.py")
        self.r.write("README.md", "`src/a.py` and [a](src/a.py) and `src/` and [dir](src)\n")
        self.r.commit()
        self.assertEqual(self.r.check(), [])

    def test_deleted_then_ignored(self):
        self.r.write("package-lock.json", "{}\n")
        self.r.write("README.md", "hi\n")
        self.r.commit()
        self.r.rm("package-lock.json")
        self.r.write(".gitignore", "package-lock.json\n")
        self.r.write("README.md", "Delete `package-lock.json` and reinstall. See `dist/app.js`.\n")
        self.r.commit()
        self.assertEqual(self.r.check(), [])

    def test_deleted_folder_then_ignored(self):
        self.r.write("evals/a.py", "a\n")
        self.r.write("documentation/b.md", "b\n")
        self.r.write("k", "k\n")
        self.r.commit()
        self.r.rm("evals")
        self.r.rm("documentation")
        self.r.write(".gitignore", "evals/\n/documentation\n")
        self.r.write("README.md", "Clone the evals into `evals/` and see `documentation/b.md`.\n")
        self.r.commit()
        self.assertEqual(self.r.check(), [])

    def test_crlf_gitignore_blank_line_ignores_nothing(self):
        # found on alirezarezvani/claude-skills checked out on Windows: asking git about `dir/`
        # matched the empty line 80 of its CRLF .gitignore, and 569 real findings went silent
        for n in ("a.py", "b.py"):
            self.r.write("scripts/" + n, n + "\n")
        self.r.commit()
        self.r.mv("scripts", "tools")
        self.r.write(".gitignore", ".memory/\r\n\r\nmy-agent/\r\n")
        self.r.write("README.md", "Everything is in `scripts/`.\n")
        self.r.commit()
        self.assertEqual([x.code for x in self.r.check()], ["MOVED_DIR"])

    def test_chain_of_renames(self):
        self.r.write("a/x.md", "x\n")
        self.r.commit()
        self.r.mv("a/x.md", "b/x.md")
        self.r.commit()
        self.r.mv("b/x.md", "c/y.md")
        self.r.write("README.md", "[x](a/x.md)\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.code, x.target) for x in f], [("MOVED", "c/y.md")])

    def test_moved_then_deleted(self):
        self.r.write("a/x.py", "x\n")
        self.r.write("k")
        self.r.commit()
        self.r.mv("a/x.py", "b/x.py")
        self.r.commit()
        self.r.rm("b/x.py")
        self.r.write("README.md", "`a/x.py`\n")
        self.r.commit()
        self.assertEqual([x.code for x in self.r.check()], ["DELETED"])

    def test_deleted_then_readded(self):
        self.r.write("a/x.py", "x\n")
        self.r.write("k")
        self.r.commit()
        self.r.rm("a/x.py")
        self.r.commit()
        self.r.write("a/x.py", "y\n")
        self.r.write("README.md", "`a/x.py`\n")
        self.r.commit()
        self.assertEqual(self.r.check(), [])

    def test_newest_disappearance_wins(self):
        self.r.write("a/x.py", "x\n")
        self.r.write("k")
        self.r.commit()
        self.r.rm("a/x.py")
        self.r.commit()
        self.r.write("a/x.py", "x again\n")
        self.r.commit()
        self.r.mv("a/x.py", "b/x.py")
        self.r.write("README.md", "`a/x.py`\n")
        self.r.commit()
        self.assertEqual([(x.code, x.target) for x in self.r.check()], [("MOVED", "b/x.py")])

    def test_directory_moved(self):
        for n in ("one.py", "two.py", "three.py"):
            self.r.write("scripts/" + n, n + "\n")
        self.r.commit()
        self.r.mv("scripts", "tools")
        self.r.write("README.md", "Everything is in `scripts/`.\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.code, x.target) for x in f], [("MOVED_DIR", "tools")])

    def test_directory_deleted(self):
        self.r.write("old/a.py")
        self.r.write("old/b.py", "b\n")
        self.r.write("k")
        self.r.commit()
        self.r.rm("old")
        self.r.write("README.md", "See `old/`.\n")
        self.r.commit()
        self.assertEqual([x.code for x in self.r.check()], ["DELETED_DIR"])

    def test_directory_split(self):
        for n in ("a", "b", "c", "d"):
            self.r.write("lib/%s.py" % n, n * 3 + "\n")
        self.r.commit()
        for n, dst in (("a", "x"), ("b", "y"), ("c", "z"), ("d", "w")):
            self.r.mv("lib/%s.py" % n, "%s/%s.py" % (dst, n))
        self.r.write("README.md", "Look in `lib/`.\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.code, x.level) for x in f], [("SPLIT_DIR", "warning")])

    def test_since(self):
        self.r.write("a/x.py", "x\n")
        self.r.write("a/y.py", "y\n")
        self.r.commit()
        self.r.mv("a/x.py", "b/x.py")
        self.r.commit()
        self.r.git("tag", "v1")
        self.r.mv("a/y.py", "b/y.py")
        self.r.write("README.md", "`a/x.py` `a/y.py`\n")
        self.r.commit()
        self.assertEqual(len(self.r.check()), 2)
        f = self.r.check(since="v1")
        self.assertEqual([(x.text, x.target) for x in f], [("a/y.py", "b/y.py")])


class Reading(Base):
    def moved_repo(self):
        self.r.write("src/a.py", "a\n")
        self.r.write("scripts/build.sh", "b\n")
        self.r.commit()
        self.r.mv("src/a.py", "lib/a.py")
        self.r.mv("scripts/build.sh", "tools/build.sh")

    def test_relative_link_from_subfolder(self):
        self.moved_repo()
        self.r.write("docs/guide.md", "See [a](../src/a.py#L10) and ![i](<../src/a.py>).\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.line, x.code, x.target, x.kind) for x in f],
                         [(1, "MOVED", "../lib/a.py", "link"), (1, "MOVED", "../lib/a.py", "link")])

    def test_root_relative_link(self):
        self.moved_repo()
        self.r.write("docs/guide.md", "[a](/src/a.py)\n")
        self.r.commit()
        self.assertEqual([x.path for x in self.r.check()], ["src/a.py"])

    def test_percent_encoded_link(self):
        self.r.write("my docs/a b.md", "x\n")
        self.r.commit()
        self.r.mv("my docs/a b.md", "docs/a b.md")
        self.r.write("README.md", "[a](my%20docs/a%20b.md)\n")
        self.r.commit()
        self.assertEqual([x.target for x in self.r.check()], ["docs/a b.md"])

    def test_reference_definition_and_html(self):
        self.moved_repo()
        self.r.write("README.md", "[a][1]\n\n[1]: src/a.py\n\n<img src=\"src/a.py\" alt=x>\n")
        self.r.commit()
        self.assertEqual([x.line for x in self.r.check()], [3, 5])

    def test_inline_code_line_suffix(self):
        self.moved_repo()
        self.r.write("README.md", "Error at `src/a.py:12`, `src/a.py:12:4` and `src/a.py#L3-L9`.\n")
        self.r.commit()
        self.assertEqual(len(self.r.check()), 3)

    def test_inline_code_that_is_not_a_path(self):
        self.moved_repo()
        self.r.write("README.md", "`npm run build` `https://x.org/src/a.py` `/etc/src/a.py` `~/src/a.py` "
                                  "`$HOME/src/a.py` `src/*.py` `{src/a.py}` `@scope/pkg` `1.2.3` `a/b`\n")
        self.r.commit()
        self.assertEqual(self.r.check(), [])

    def test_fenced_code(self):
        self.moved_repo()
        self.r.write("README.md", "```bash\n./scripts/build.sh --fast\npython src/a.py\nbuild.sh\n```\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.line, x.kind, x.target) for x in f],
                         [(2, "fence", "tools/build.sh"), (3, "fence", "lib/a.py")])

    def test_fence_closes(self):
        self.moved_repo()
        self.r.write("README.md", "~~~~\nx\n~~~~\nNot code: src/a.py but `src/a.py` is\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.line, x.kind) for x in f], [(4, "code")])

    def test_html_comment_is_skipped(self):
        self.moved_repo()
        self.r.write("README.md", "<!-- `src/a.py` -->\n<!--\n[a](src/a.py)\n-->\nok `src/a.py`\n"
                                  "<!-- note --> see `src/a.py`\n`src/a.py`\n")
        self.r.commit()
        self.assertEqual([x.line for x in self.r.check()], [5, 6, 7])

    def test_historical_sentence_is_a_warning(self):
        self.moved_repo()
        self.r.write("README.md", "`src/a.py` was renamed to `lib/a.py`.\nUse `src/a.py`.\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.line, x.level, x.code) for x in f],
                         [(1, "warning", "HISTORICAL:MOVED"), (2, "error", "MOVED")])

    def test_github_url_to_this_repo(self):
        self.moved_repo()
        self.r.git("remote", "add", "origin", "https://github.com/Owner/Proj.git")
        self.r.write("README.md",
                     "https://github.com/owner/proj/blob/main/src/a.py\n"
                     "https://github.com/owner/proj/blob/0123abc/src/a.py\n"
                     "https://github.com/other/proj/blob/main/src/a.py\n"
                     "https://raw.githubusercontent.com/Owner/Proj/main/src/a.py\n"
                     "https://github.com/owner/proj/tree/dev/src/a.py\n")  # another branch
        self.r.commit()
        self.assertEqual([(x.line, x.kind) for x in self.r.check()], [(1, "url"), (4, "url")])

    def test_nearest_folder_first(self):
        self.r.write("src/index.ts", "a\n")
        self.r.write("packages/a/src/index.ts", "b\n")
        self.r.commit()
        self.r.rm("src/index.ts")
        self.r.write("packages/a/README.md", "Edit `src/index.ts`.\n")
        self.r.commit()
        self.assertEqual(self.r.check(), [])

    def test_elsewhere_is_a_warning(self):
        self.r.write("src/util.py", "a\n")
        self.r.write("pkg/src/util.py", "totally unrelated content here\n")
        self.r.write("k", "k\n")
        self.r.commit()
        self.r.rm("src/util.py")
        self.r.write("README.md", "Edit `src/util.py`.\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.code, x.level, x.target) for x in f], [("ELSEWHERE", "warning", "pkg/src/util.py")])

    def test_changelog_and_history_folders_skipped(self):
        self.moved_repo()
        for p in ("CHANGELOG.md", "docs/blog/post.md", "versioned_docs/version-1.x/a.md", "docs/v1.2/a.md",
                  "docs/rfcs/0001.md", "HISTORY.rst", "node_modules/x/README.md", "RELEASE_NOTES.md",
                  "docs/UPGRADING.md", "vendor/lib/README.md"):
            self.r.write(p, "`src/a.py`\n")
        self.r.commit()
        self.assertEqual(self.r.check(), [])
        f = self.r.check(all_docs=True)
        # node_modules and vendor are never read; `x` in HISTORY.rst is not a literal in rst
        self.assertEqual(len(f), 7)

    def test_named_changelog_is_read(self):
        self.moved_repo()
        self.r.write("CHANGELOG.md", "`src/a.py`\n")
        self.r.commit()
        self.assertEqual(len(self.r.check(["CHANGELOG.md"])), 1)

    def test_txt_only_when_prose(self):
        self.moved_repo()
        self.r.write("requirements.txt", "src/a.py\n")
        self.r.write("CMakeLists.txt", "`src/a.py`\n")
        self.r.write("README.txt", "`src/a.py`\n")
        self.r.write("docs/notes.txt", "`src/a.py`\n")
        self.r.write("misc/output.txt", "`src/a.py`\n")  # not prose
        self.r.commit()
        self.assertEqual(sorted(x.doc for x in self.r.check()), ["README.txt", "docs/notes.txt"])

    def test_rst(self):
        self.moved_repo()
        self.r.write("docs/index.rst", ".. include:: ../src/a.py\n\nRun ``scripts/build.sh``.\n"
                                       "See `the file <../src/a.py>`_ and :file:`src/a.py`.\n"
                                       ".. code-block:: bash\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual(sorted((x.line, x.kind) for x in f),
                         [(1, "link"), (3, "code"), (4, "code"), (4, "link")])

    def test_asciidoc(self):
        self.moved_repo()
        self.r.write("docs/a.adoc", "include::../src/a.py[]\nimage::../src/a.py[x]\n")
        self.r.commit()
        self.assertEqual(len(self.r.check()), 2)

    def test_fence_languages(self):
        self.moved_repo()
        self.r.write("README.md",
                     "```python\nimport src/a.py\n```\n"          # code: relative to who knows what
                     "```\nsrc/a.py\n```\n"                       # no language: output, trees
                     "```console\n$ python src/a.py\nsrc/a.py: done\n```\n"   # output line skipped
                     "```sh\n# src/a.py is the entry point\nsh scripts/build.sh\n```\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual([(x.line, x.text) for x in f], [(8, "src/a.py"), (13, "scripts/build.sh")])

    def test_dated_and_superseded_docs_skipped(self):
        self.moved_repo()
        self.r.write("docs/2026-03-14-phase1.md", "`src/a.py`\n")
        self.r.write("meetings-2024_01/agenda.md", "`src/a.py`\n")
        self.r.write("docs/design.md", "# Design\n\n> **Status: Superseded** by v2\n\n`src/a.py`\n")
        self.r.write("docs/live.md", "Released 2024. `src/a.py`\n")
        self.r.commit()
        self.assertEqual([x.doc for x in self.r.check()], ["docs/live.md"])
        self.assertEqual(len(self.r.check(all_docs=True)), 4)

    def test_old_folders_and_files_skipped(self):
        self.moved_repo()
        for p in ("old_files/readme.md", "docs/legacy-guide/a.md", "README_OLD.md", "docs/setup.old.md"):
            self.r.write(p, "`src/a.py`\n")
        self.r.write("docs/folder.md", "`src/a.py`\n")  # "folder" is not "old"
        self.r.commit()
        self.assertEqual([x.doc for x in self.r.check()], ["docs/folder.md"])

    def test_fragment_links_skipped(self):
        self.moved_repo()
        # from docs/macros/ this link does lead to src/a.py; the page that includes it is elsewhere
        self.r.write("docs/macros/args.md", "[a](../../src/a.py) and `src/a.py`\n")
        self.r.commit()
        self.assertEqual([x.kind for x in self.r.check()], ["code"])

    def test_shortened_is_a_warning(self):
        self.r.write("packages/core/x.ts", "x\n")
        self.r.write("k", "k\n")
        self.r.commit()
        self.r.mv("packages/core/x.ts", "plugin/packages/core/x.ts")
        self.r.write("README.md", "`packages/core/x.ts` and [x](packages/core/x.ts)\n")
        self.r.commit()
        f = self.r.check()
        self.assertEqual(sorted((x.kind, x.level, x.code) for x in f),
                         [("code", "warning", "SHORTENED:MOVED"), ("link", "error", "MOVED")])

    def test_reader_config_folders_skipped(self):
        self.r.write(".claude/settings.json", "{}\n")
        self.r.write(".github/workflows/ci.yml", "x\n")
        self.r.write(".github/x.yml", "y\n")
        self.r.commit()
        self.r.rm(".claude/settings.json")
        self.r.rm(".github/workflows/ci.yml")
        self.r.write("README.md", "`.claude/settings.json` `.github/workflows/ci.yml`\n")
        self.r.commit()
        self.assertEqual([x.text for x in self.r.check()], [".github/workflows/ci.yml"])

    def test_paths_argument(self):
        self.moved_repo()
        self.r.write("README.md", "`src/a.py`\n")
        self.r.write("docs/a.md", "`src/a.py`\n")
        self.r.commit()
        self.assertEqual([x.doc for x in self.r.check(["docs"])], ["docs/a.md"])


class Modes(Base):
    def test_rev(self):
        self.r.write("src/a.py", "a\n")
        self.r.write("README.md", "`src/a.py`\n")
        self.r.commit()
        self.r.mv("src/a.py", "lib/a.py")
        before = self.r.commit()
        self.r.write("README.md", "`lib/a.py`\n")
        after = self.r.commit()
        self.assertEqual([x.code for x in self.r.check(rev=before)], ["MOVED"])
        self.assertEqual(self.r.check(rev=after), [])

    def run_main(self, args):
        out, err = io.StringIO(), io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = M.main(args)
        return code, out.getvalue(), err.getvalue()

    def test_exit_codes_and_json(self):
        self.r.write("src/a.py", "a\n")
        self.r.write("README.md", "`src/a.py`\n")
        self.r.commit()
        code, out, _ = self.run_main([str(self.r.root)])
        self.assertEqual(code, 0)
        self.r.mv("src/a.py", "lib/a.py")
        self.r.commit()
        code, out, _ = self.run_main([str(self.r.root)])
        self.assertEqual(code, 1)
        self.assertIn("README.md:1: error MOVED", out)
        code, out, _ = self.run_main([str(self.r.root), "--json"])
        d = json.loads(out)
        self.assertEqual(d["findings"][0]["target"], "lib/a.py")

    def test_warnings_only_exit_zero(self):
        self.r.write("src/a.py", "a\n")
        self.r.commit()
        self.r.mv("src/a.py", "lib/a.py")
        self.r.write("README.md", "`src/a.py` was renamed.\n")
        self.r.commit()
        self.assertEqual(self.run_main([str(self.r.root)])[0], 0)

    def test_not_a_repository(self):
        d = tempfile.mkdtemp(prefix="mpc-norepo-")
        try:
            self.assertEqual(self.run_main([d])[0], 2)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_no_docs(self):
        self.r.write("a.py")
        self.r.commit()
        self.assertEqual(self.run_main([str(self.r.root)])[0], 2)

    def test_shallow_clone_cannot_judge(self):
        self.r.write("docs/a.md", "a\n")
        self.r.write("README.md", "hi\n")
        self.r.commit()
        self.r.rm("docs/a.md")
        self.r.commit()
        self.r.write("README.md", "[a](docs/a.md)\n")
        self.r.commit()
        d = tempfile.mkdtemp(prefix="mpc-shallow-")
        try:
            dst = os.path.join(d, "c")
            subprocess.run(["git", "clone", "-q", "--depth", "1", "file://" + str(self.r.root).replace("\\", "/"), dst],
                           check=True, capture_output=True, env=ENV)
            code, _, err = self.run_main([dst])
            self.assertEqual(code, 2)
            self.assertIn("shallow", err)
            self.assertEqual(self.run_main([str(self.r.root)])[0], 1)
        finally:
            shutil.rmtree(d, ignore_errors=True)


class Pairing(unittest.TestCase):
    """The pairing of one commit's deletions and additions, without git's own rename detection
    (which needs file contents; the pairing must work on a clone that has none)."""

    def pair(self, dels, adds):
        h = object.__new__(M.History)
        h.gone, h.ever = {}, set()
        h._commit("abc", "2024-01-01", dels, adds)
        return {p: (e.kind, e.new) for p, e in h.gone.items()}

    def test_same_blob(self):
        self.assertEqual(self.pair({"a/x.md": "1", "a/y.md": "2"}, {"b/p.md": "2", "c/q.md": "1"}),
                         {"a/x.md": ("moved", "c/q.md"), "a/y.md": ("moved", "b/p.md")})

    def test_same_blob_several_places_prefers_the_same_name(self):
        self.assertEqual(self.pair({"a/x.md": "1"}, {"b/y.md": "1", "c/x.md": "1"}),
                         {"a/x.md": ("moved", "c/x.md")})

    def test_same_name_other_content(self):
        self.assertEqual(self.pair({"a/x.md": "1", "a/z.md": "3"}, {"b/x.md": "2", "b/w.md": "4"}),
                         {"a/x.md": ("moved", "b/x.md"), "a/z.md": ("deleted", None)})

    def test_same_name_twice_is_not_guessed(self):
        self.assertEqual(self.pair({"a/x.md": "1", "k/k.md": "9"}, {"b/x.md": "2", "c/x.md": "3"}),
                         {"a/x.md": ("deleted", None), "k/k.md": ("deleted", None)})

    def test_added_only(self):
        self.assertEqual(self.pair({}, {"b/x.md": "2"}), {})


class Units(unittest.TestCase):
    def test_clean_token(self):
        self.assertEqual(M.clean_token("src/a.py,"), "src/a.py")
        self.assertEqual(M.clean_token("'src/a.py'"), "src/a.py")
        self.assertEqual(M.clean_token("docs/"), "docs/")
        self.assertEqual(M.clean_token("setup.py"), "setup.py")
        self.assertIsNone(M.clean_token("README"))
        self.assertIsNone(M.clean_token("a/b c"))
        self.assertIsNone(M.clean_token("10/20"))
        self.assertIsNone(M.clean_token("//cdn.x/a.js"))

    def test_resolve_link(self):
        self.assertEqual(M.resolve_link("../a.md#x", "docs/sub"), "docs/a.md")
        self.assertEqual(M.resolve_link("/a.md?raw=1", "docs"), "a.md")
        self.assertIsNone(M.resolve_link("../../../a.md", "docs"))
        self.assertIsNone(M.resolve_link("mailto:x@y", ""))
        self.assertIsNone(M.resolve_link("#anchor", ""))
        self.assertIsNone(M.resolve_link("{{ site.url }}/a.md", ""))

    def test_unquote_git(self):
        self.assertEqual(M.unquote_git('"a\\tb.md"'), "a\tb.md")
        self.assertEqual(M.unquote_git('"\\346\\227\\245.md"'), "日.md")
        self.assertEqual(M.unquote_git("plain.md"), "plain.md")


if __name__ == "__main__":
    unittest.main(verbosity=1)

# -*- coding: utf-8 -*-
"""Tests for leak_scan.py. Standard library only: `python test_leak_scan.py`.

Every test here was watched failing once, by breaking the line it guards, before it was
kept. The breakages are listed in mutation_check.py, which re-runs them on demand.
"""
import contextlib
import io
import sys
import tempfile
import unittest
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import leak_scan as ls  # noqa: E402

# Nothing in this file is written out in a form another scanner would recognise. The
# tokens are invented, and even the *names* are assembled from pieces, because a plain
# substring scanner pointed at this repository would otherwise report its own test
# corpus. leak_scan.py splits its rule list for the same reason.
PW = "password" + "="
PW_UPPER = PW.upper()
AK = "api_" + "key="
CS = "client_secret" + "="
VALUE = "8Fj2kdlQ93zx"                                            # 12 chars of noise

REAL_GHP = "ghp_" + "A1b2C3d4E5f6G7h8I9j0K1l2M3n4O5p6Q7r8"        # 36 body chars
REAL_PAT = "github_pat_" + "11ABCDEFG0aBcDeFgHiJkL"               # 22 body chars
REAL_AWS = "AKIA" + "IOSFODNN7EXAMPL0"                            # 16 body chars

PEM_HEAD, PEM_TAIL = "-----BEGIN ", " PRIVATE KEY-----"
PEM_BODY = "\nMIIEow" + "IBAAKCAQEAwJ3" + "hQmZ0pT8vLk91nRb4"      # 36 base64 chars


def pem(algorithm, body=PEM_BODY):
    return PEM_HEAD + algorithm + PEM_TAIL + body


def hits(text, words=()):
    data = text.encode("utf-8") if isinstance(text, str) else text
    return ls.scan_bytes(data, ls.build_rules(words))


def kinds(text, words=()):
    return [h[0] for h in hits(text, words)]


def needles(text, words=()):
    return [h[1] for h in hits(text, words)]


class Credentials(unittest.TestCase):
    def test_key_shaped_token_is_caught(self):
        self.assertIn("ghp_", needles("token = " + REAL_GHP))

    def test_bare_prefix_mentioned_in_prose_is_not_a_leak(self):
        # Documentation that names the prefix is not a key. Remove the shape test and
        # this repository reports 33 hits instead of none, all of them prose.
        self.assertEqual([], hits("keys beginning with ghp_ or gho_ are refused"))

    def test_token_one_character_short_is_not_key_shaped(self):
        self.assertEqual([], hits("ghp_" + "A" * 35 + " "))

    def test_fine_grained_pat_is_caught(self):
        self.assertIn("github_pat_", needles(REAL_PAT + "\n"))

    def test_aws_access_key_is_caught(self):
        self.assertIn("AKIA", needles("aws_key " + REAL_AWS + " end"))

    def test_private_key_header_is_caught_for_every_algorithm(self):
        for algorithm in ("RSA", "OPENSSH", "EC"):
            self.assertEqual(["credential"], kinds(pem(algorithm)), algorithm)

    def test_private_key_header_without_a_body_is_not_a_leak(self):
        # Every secret scanner ever written contains these words, this one included. The
        # header counts only when base64 follows it - the same rule as the key prefixes.
        self.assertEqual([], hits(pem("RSA", body="\nsee the manual for how to store it")))


class Assignments(unittest.TestCase):
    def test_the_assembled_rule_list_is_what_it_looks_like(self):
        # leak_scan.py builds these names from pieces; this is the guard on that trick.
        self.assertIn(PW, ls.ASSIGN_NAMES)
        self.assertIn(AK, ls.ASSIGN_NAMES)
        self.assertEqual(10, len(ls.ASSIGN_NAMES))

    def test_long_literal_value_is_caught(self):
        self.assertIn(PW, needles(PW + VALUE))

    def test_uppercase_name_is_caught(self):
        self.assertIn(PW_UPPER, needles(PW_UPPER + VALUE))

    def test_short_value_is_not_caught(self):
        self.assertEqual([], hits(PW + "abc"))

    def test_interpolated_value_is_not_caught(self):
        # Deliberately free of placeholder words, so this exercises the interpolation
        # test and not the placeholder list underneath it.
        for value in ("${DB_CRED_A1B2C3}", "{{.Values.dbCred1}}", "%DB_CRED_A1B2C3%"):
            self.assertEqual([], hits(AK + value), value)

    def test_placeholder_value_is_not_caught(self):
        for value in ("changeme_now", "your-secret-here", "xxxxxxxxxxxx"):
            self.assertEqual([], hits(AK + value), value)

    def test_quoted_value_is_read_through_the_quote(self):
        self.assertIn(CS, needles(CS + '"' + VALUE + '"'))

    def test_empty_value_is_not_caught(self):
        self.assertEqual([], hits(PW + "\n"))


class Identifiers(unittest.TestCase):
    def test_own_word_is_caught(self):
        self.assertEqual(["identifier"], kinds("built by alice on friday", ["alice"]))

    def test_word_inside_a_longer_word_is_not_caught(self):
        # `sample` must not match `sam`; this is what makes a short identifier usable.
        self.assertEqual([], hits("see the sample and the alicepad", ["sam", "alice0"]))

    def test_katakana_word_inside_a_longer_compound_is_not_caught(self):
        # Japanese is written without spaces, so a short katakana name matches inside
        # longer compounds. This produced 38 false positives in one document.
        self.assertEqual([], hits("ハルシネーションの話", ["ハル"]))

    def test_katakana_word_standing_alone_is_still_caught(self):
        self.assertEqual(["identifier"], kinds("担当は ハル です", ["ハル"]))

    def test_utf16_encoded_word_inside_a_binary_is_caught(self):
        # The case this tool exists for: a string compiled into a binary, two bytes per
        # character, invisible to a UTF-8 grep.
        blob = b"\x00\x01\x02" + "alice".encode("utf-16-le") + b"\xff\xfe\x00"
        found = ls.scan_bytes(blob, ls.build_rules(["alice"]))
        self.assertEqual(["identifier"], [h[0] for h in found])

    def test_home_directory_path_is_caught(self):
        for path in ("C:\\Users\\alice\\build", "/home/alice/build", "/Users/alice/build"):
            self.assertEqual(["home path"], kinds(path, ["alice"]), path)

    def test_no_patterns_means_no_identifier_rules(self):
        self.assertEqual([], hits("built by alice on friday"))


class Masking(unittest.TestCase):
    def test_mask_keeps_at_most_two_characters(self):
        self.assertEqual("al" + "*" * 3, ls.mask("alice"))

    def test_mask_of_a_short_word_reveals_nothing(self):
        self.assertEqual("**", ls.mask("ab"))

    def test_report_does_not_print_the_identifier_in_clear_text(self):
        # CI logs on a public repository are public. A scanner that echoes what it found
        # has moved the leak, not caught it.
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "build.log").write_text("compiled by alice", encoding="utf-8")
            (root / "p.txt").write_text("alice\n", encoding="utf-8")
            out = io.StringIO()
            with contextlib.redirect_stdout(out):
                code = ls.main([str(root), "--patterns", str(root / "p.txt")])
            text = out.getvalue()
        self.assertEqual(1, code)
        self.assertNotIn("alice", text)
        self.assertIn("al***", text)


class Walking(unittest.TestCase):
    def _tree(self, d):
        root = Path(d)
        (root / ".git").mkdir()
        (root / ".git" / "config").write_text(PW + VALUE, encoding="utf-8")
        (root / "__pycache__").mkdir()
        (root / "__pycache__" / "m.cpython-313.pyc").write_bytes(
            b"\x00\x0f\r\n" + b"C:\\Users\\alice\\proj\\m.py" + b"\x00")
        (root / "ok.txt").write_text("nothing to see", encoding="utf-8")
        return root

    def test_untracked_binary_is_scanned(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(d)
            files, found = ls.scan_tree(root, ls.build_rules(["alice"]))
        self.assertEqual(2, files)  # .git was skipped
        self.assertEqual([("__pycache__/m.cpython-313.pyc", "home path")],
                         [(f[0], f[1]) for f in found])

    def test_git_directory_is_skipped_by_default(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(d)
            _files, found = ls.scan_tree(root, ls.build_rules())
        self.assertEqual([], found)

    def test_exclusion_can_be_turned_off(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(d)
            _files, found = ls.scan_tree(root, ls.build_rules(), excludes=())
        self.assertEqual([(".git/config", "credential")], [(f[0], f[1]) for f in found])

    def test_allow_list_suppresses_one_path(self):
        with tempfile.TemporaryDirectory() as d:
            root = self._tree(d)
            allow = {("__pycache__/m.cpython-313.pyc", "C:\\Users\\alice")}
            _files, found = ls.scan_tree(root, ls.build_rules(["alice"]), allow=allow)
        self.assertEqual([], found)

    def test_line_numbers_are_reported(self):
        with tempfile.TemporaryDirectory() as d:
            root = Path(d)
            (root / "a.txt").write_text("one\ntwo\n" + PW + VALUE + "\n", encoding="utf-8")
            _files, found = ls.scan_tree(root, ls.build_rules())
        self.assertEqual([("a.txt", "credential", PW, 3)], found)


class ExitCodes(unittest.TestCase):
    def _run(self, argv):
        out = io.StringIO()
        err = io.StringIO()
        with contextlib.redirect_stdout(out), contextlib.redirect_stderr(err):
            code = ls.main(argv)
        return code, out.getvalue() + err.getvalue()

    def test_clean_tree_is_zero(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ok.txt").write_text("nothing", encoding="utf-8")
            code, _ = self._run([d])
        self.assertEqual(0, code)

    def test_empty_directory_is_two_not_zero(self):
        # A scan that read nothing must not report success: that is how a misconfigured
        # path turns into a green check over an unscanned tree.
        with tempfile.TemporaryDirectory() as d:
            code, text = self._run([d])
        self.assertEqual(2, code)
        self.assertIn("not a pass", text)

    def test_missing_target_is_two(self):
        code, _ = self._run(["no/such/place"])
        self.assertEqual(2, code)

    def test_missing_patterns_file_is_two(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ok.txt").write_text("nothing", encoding="utf-8")
            code, _ = self._run([d, "--patterns", str(Path(d) / "absent.txt")])
        self.assertEqual(2, code)

    def test_empty_patterns_file_is_two(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "ok.txt").write_text("nothing", encoding="utf-8")
            (Path(d) / "p.txt").write_text("# only a comment\n", encoding="utf-8")
            code, _ = self._run([d, "--patterns", str(Path(d) / "p.txt")])
        self.assertEqual(2, code)

    def test_fail_on_none_reports_without_failing(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.txt").write_text(PW + VALUE, encoding="utf-8")
            code, text = self._run([d, "--fail-on", "none"])
        self.assertEqual(0, code)
        self.assertIn("1 hit", text)

    def test_github_format_emits_an_annotation(self):
        with tempfile.TemporaryDirectory() as d:
            (Path(d) / "a.txt").write_text(PW + VALUE, encoding="utf-8")
            code, text = self._run([d, "--format", "github"])
        self.assertEqual(1, code)
        self.assertIn("::error file=a.txt,line=1::", text)


if __name__ == "__main__":
    unittest.main(verbosity=2)

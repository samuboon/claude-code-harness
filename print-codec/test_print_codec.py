# -*- coding: utf-8 -*-
"""Tests for print_codec.py.

    python -m unittest discover -s . -v      (or: python test_print_codec.py)

Deliberately written before the numbers in the README: every claim there comes from a
run, and every behaviour here is one this tool is allowed to lose only on purpose.
Run mutation_check.py to see the suite fail on demand.
"""
import io
import json
import subprocess
import sys
import tempfile
import unittest
from pathlib import Path

HERE = Path(__file__).resolve().parent
sys.path.insert(0, str(HERE))

import print_codec as pc  # noqa: E402

GREEN = "\U0001F7E2"   # the character that stopped the checker on 2026-09-16
EMDASH = "—"      # cp932 has U+2015 but not U+2014; this is the 2026-09-14 one


def write(tmp, name, text):
    p = Path(tmp) / name
    p.parent.mkdir(parents=True, exist_ok=True)
    p.write_text(text, encoding="utf-8")
    return p


class TestEncodable(unittest.TestCase):
    def test_ascii_survives_cp932(self):
        self.assertTrue(pc.encodable("a", "cp932"))

    def test_japanese_survives_cp932(self):
        self.assertTrue(pc.encodable("あ", "cp932"))

    def test_green_circle_does_not_survive_cp932(self):
        self.assertFalse(pc.encodable(GREEN, "cp932"))

    def test_em_dash_does_not_survive_cp932(self):
        self.assertFalse(pc.encodable(EMDASH, "cp932"))

    def test_horizontal_bar_does_survive_cp932(self):
        # U+2015 is the one cp932 actually has; the near neighbour is the trap
        self.assertTrue(pc.encodable("―", "cp932"))

    def test_japanese_does_not_survive_ascii(self):
        self.assertFalse(pc.encodable("あ", "ascii"))

    def test_everything_survives_utf8(self):
        self.assertTrue(pc.encodable(GREEN, "utf-8"))

    def test_unknown_codec_raises(self):
        with self.assertRaises(LookupError):
            pc.encodable("a", "no-such-codec-at-all")

    def test_cache_returns_same_answer_twice(self):
        self.assertEqual(pc.encodable(GREEN, "cp932"), pc.encodable(GREEN, "cp932"))


class TestCharName(unittest.TestCase):
    def test_names_the_green_circle(self):
        self.assertEqual(pc.char_name(GREEN), "U+1F7E2 LARGE GREEN CIRCLE")

    def test_names_the_em_dash(self):
        self.assertIn("EM DASH", pc.char_name(EMDASH))

    def test_unnamed_character_still_gets_a_code_point(self):
        self.assertEqual(pc.char_name(""), "U+0007 unnamed")


class TestSafe(unittest.TestCase):
    def test_replaces_what_the_codec_refuses(self):
        self.assertEqual(pc.safe("ok " + GREEN, "cp932"), "ok <U+1F7E2>")

    def test_keeps_what_the_codec_accepts(self):
        self.assertEqual(pc.safe("あok", "cp932"), "あok")

    def test_empty_stays_empty(self):
        self.assertEqual(pc.safe("", "cp932"), "")

    def test_utf8_changes_nothing(self):
        self.assertEqual(pc.safe(GREEN, "utf-8"), GREEN)


class TestProtection(unittest.TestCase):
    def test_reconfigure_counts(self):
        self.assertEqual(pc.detect_protection('sys.stdout.reconfigure(encoding="utf-8")'),
                         "reconfigure")

    def test_stderr_reconfigure_counts(self):
        self.assertEqual(pc.detect_protection('sys.stderr.reconfigure(encoding="utf-8")'),
                         "reconfigure")

    def test_textiowrapper_counts(self):
        self.assertEqual(pc.detect_protection("io.TextIOWrapper(sys.stdout.buffer, 'utf-8')"),
                         "TextIOWrapper")

    def test_pythonioencoding_counts(self):
        self.assertEqual(pc.detect_protection('os.environ["PYTHONIOENCODING"] = "utf-8"'),
                         "PYTHONIOENCODING")

    def test_plain_file_is_unprotected(self):
        self.assertIsNone(pc.detect_protection("print('hello')"))


class TestModuleConstants(unittest.TestCase):
    def parse(self, src):
        import ast
        return pc.module_constants(ast.parse(src))

    def test_picks_up_a_module_level_string(self):
        self.assertEqual(self.parse('OK = "fine"'), {"OK": "fine"})

    def test_ignores_non_strings(self):
        self.assertEqual(self.parse("N = 3"), {})

    def test_ignores_names_assigned_twice(self):
        self.assertEqual(self.parse('A = "x"\nA = "y"'), {})

    def test_ignores_assignments_inside_a_function(self):
        self.assertEqual(self.parse('def f():\n    B = "x"\n'), {})

    def test_handles_multiple_targets(self):
        self.assertEqual(self.parse('A = B = "x"'), {"A": "x", "B": "x"})


class TestClassifyCall(unittest.TestCase):
    def kinds(self, src, include_logging=False):
        import ast
        out = []
        for node in ast.walk(ast.parse(src)):
            if isinstance(node, ast.Call):
                k = pc.classify_call(node, include_logging)
                if k:
                    out.append(k)
        return out

    def test_print_is_a_console_write(self):
        self.assertEqual(self.kinds("print('a')"), ["print"])

    def test_stdout_write_is_a_console_write(self):
        self.assertEqual(self.kinds("sys.stdout.write('a')"), ["sys.stdout.write"])

    def test_stderr_write_is_a_console_write(self):
        self.assertEqual(self.kinds("sys.stderr.write('a')"), ["sys.stderr.write"])

    def test_print_to_stderr_still_counts(self):
        self.assertEqual(self.kinds("print('a', file=sys.stderr)"), ["print"])

    def test_print_to_an_open_file_does_not_count(self):
        self.assertEqual(self.kinds("print('a', file=fh)"), [])

    def test_writing_to_an_open_file_does_not_count(self):
        self.assertEqual(self.kinds("fh.write('a')"), [])

    def test_logging_is_off_by_default(self):
        self.assertEqual(self.kinds("logging.info('a')"), [])

    def test_logging_can_be_switched_on(self):
        self.assertEqual(self.kinds("logging.info('a')", True), ["logging.info"])

    def test_logger_variable_counts_when_switched_on(self):
        self.assertEqual(self.kinds("logger.error('a')", True), ["logging.error"])

    def test_unrelated_method_named_info_does_not_count(self):
        self.assertEqual(self.kinds("response.info('a')", True), [])


class TestLiteralText(unittest.TestCase):
    def text(self, expr, constants=None):
        import ast
        node = ast.parse(expr, mode="eval").body
        return pc.literal_text(node, constants or {})

    def test_plain_string(self):
        self.assertEqual(self.text('"hi"'), "hi")

    def test_number_contributes_nothing(self):
        self.assertEqual(self.text("3"), "")

    def test_fstring_keeps_its_literal_halves(self):
        self.assertEqual(self.text('f"a{x}b"'), "ab")

    def test_fstring_placeholder_contributes_nothing(self):
        self.assertEqual(self.text('f"{x}"'), "")

    def test_name_resolves_through_module_constants(self):
        self.assertEqual(self.text("BANNER", {"BANNER": "hi"}), "hi")

    def test_unknown_name_contributes_nothing(self):
        self.assertEqual(self.text("whatever"), "")

    def test_concatenation_joins_both_sides(self):
        self.assertEqual(self.text('"a" + "b"'), "ab")

    def test_percent_formatting_keeps_the_template(self):
        self.assertEqual(self.text('"a%s" % v'), "a%s")

    def test_format_call_keeps_the_template(self):
        self.assertEqual(self.text('"a{}".format(v)'), "a{}")

    def test_join_keeps_the_separator(self):
        self.assertEqual(self.text('", ".join(v)'), ", ")

    def test_deep_nesting_stops_rather_than_recursing_forever(self):
        # 41 concatenated literals; the walk gives up long before the end
        out = self.text('"a"' + ' + "a"' * 40)
        self.assertTrue(0 < len(out) < 41, "expected a truncated read, got {}".format(len(out)))


class TestScanSource(unittest.TestCase):
    def test_finds_the_green_circle_in_a_print(self):
        rows = pc.scan_source('print("done {}")'.format(GREEN), "cp932")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["chars"], [GREEN])
        self.assertEqual(rows[0]["call"], "print")

    def test_reports_the_line_number(self):
        rows = pc.scan_source('x = 1\n\nprint("{}")\n'.format(GREEN), "cp932")
        self.assertEqual(rows[0]["line"], 3)

    def test_clean_print_is_not_reported(self):
        self.assertEqual(pc.scan_source('print("done")', "cp932"), [])

    def test_japanese_print_is_not_reported_under_cp932(self):
        self.assertEqual(pc.scan_source('print("完了")', "cp932"), [])

    def test_japanese_print_is_reported_under_ascii(self):
        self.assertEqual(len(pc.scan_source('print("完了")', "ascii")), 1)

    def test_nothing_is_reported_under_utf8(self):
        self.assertEqual(pc.scan_source('print("{}")'.format(GREEN), "utf-8"), [])

    def test_a_character_is_listed_once_per_line(self):
        rows = pc.scan_source('print("{0}{0}{0}")'.format(GREEN), "cp932")
        self.assertEqual(rows[0]["chars"], [GREEN])

    def test_two_different_characters_are_both_listed(self):
        rows = pc.scan_source('print("{}{}")'.format(GREEN, EMDASH), "cp932")
        self.assertEqual(rows[0]["chars"], [GREEN, EMDASH])

    def test_the_end_keyword_is_read(self):
        rows = pc.scan_source('print("ok", end="{}")'.format(GREEN), "cp932")
        self.assertEqual(len(rows), 1)

    def test_the_sep_keyword_is_read(self):
        rows = pc.scan_source('print("a", "b", sep="{}")'.format(GREEN), "cp932")
        self.assertEqual(len(rows), 1)

    def test_the_file_keyword_is_not_read_as_text(self):
        rows = pc.scan_source('print("ok", file=sys.stderr)', "cp932")
        self.assertEqual(rows, [])

    def test_a_string_that_is_never_printed_is_ignored(self):
        self.assertEqual(pc.scan_source('X = "{}"'.format(GREEN), "cp932"), [])

    def test_a_comment_is_ignored(self):
        self.assertEqual(pc.scan_source('print("ok")  # {}'.format(GREEN), "cp932"), [])

    def test_a_docstring_is_ignored(self):
        self.assertEqual(pc.scan_source('"""{}"""\nprint("ok")'.format(GREEN), "cp932"), [])

    def test_a_module_constant_reaches_the_print(self):
        rows = pc.scan_source('BANNER = "{}"\nprint(BANNER)'.format(GREEN), "cp932")
        self.assertEqual(len(rows), 1)
        self.assertEqual(rows[0]["line"], 2)

    def test_rows_come_back_in_line_order(self):
        src = 'print("b{}")\nprint("a{}")\n'.format(EMDASH, GREEN)
        rows = pc.scan_source(src, "cp932")
        self.assertEqual([r["line"] for r in rows], [1, 2])

    def test_rows_from_a_nested_scope_still_come_back_in_line_order(self):
        # ast.walk is breadth-first: without the sort, the top-level print at line 3
        # is reported before the one nested in a function at line 2
        src = 'def g():\n    print("b{}")\nprint("a{}")\n'.format(EMDASH, GREEN)
        rows = pc.scan_source(src, "cp932")
        self.assertEqual([r["line"] for r in rows], [2, 3])

    def test_syntax_error_is_reported_not_swallowed(self):
        with self.assertRaises(pc.ScanError):
            pc.scan_source("def (:", "cp932")


class TestEntryPoint(unittest.TestCase):
    def test_sys_exit_makes_it_an_entry_point(self):
        self.assertTrue(pc.is_entry_point("sys.exit(1)"))

    def test_dunder_main_makes_it_an_entry_point(self):
        self.assertTrue(pc.is_entry_point('if __name__ == "__main__":\n    pass'))

    def test_single_quoted_dunder_main_counts_too(self):
        self.assertTrue(pc.is_entry_point("if __name__ == '__main__':\n    pass"))

    def test_a_plain_module_is_not_an_entry_point(self):
        self.assertFalse(pc.is_entry_point("def f():\n    return 1"))


class TestTargets(unittest.TestCase):
    def test_walks_a_directory(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", "print('a')")
            write(tmp, "sub/b.py", "print('b')")
            write(tmp, "notes.txt", "ignored")
            found = pc.iter_targets([tmp], [])
            self.assertEqual(sorted(p.name for p in found), ["a.py", "b.py"])

    def test_a_single_file_is_allowed(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "a.py", "print('a')")
            self.assertEqual(pc.iter_targets([str(p)], []), [p])

    def test_exclude_glob_by_name(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", "print('a')")
            write(tmp, "test_a.py", "print('a')")
            found = pc.iter_targets([tmp], ["test_*.py"])
            self.assertEqual([p.name for p in found], ["a.py"])

    def test_exclude_glob_by_path(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "keep/a.py", "print('a')")
            write(tmp, "skip/b.py", "print('b')")
            found = pc.iter_targets([tmp], ["*/skip/*"])
            self.assertEqual([p.name for p in found], ["a.py"])

    def test_the_same_file_named_twice_is_scanned_once(self):
        with tempfile.TemporaryDirectory() as tmp:
            p = write(tmp, "a.py", "print('a')")
            self.assertEqual(len(pc.iter_targets([str(p), str(p)], [])), 1)

    def test_a_missing_path_is_an_error(self):
        with self.assertRaises(pc.ScanError):
            pc.iter_targets(["no/such/path/here"], [])


class TestScanPaths(unittest.TestCase):
    def test_unprotected_file_is_at_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", 'print("{}")'.format(GREEN))
            files, skipped = pc.scan_paths([tmp], "cp932")
            self.assertEqual(len(files[0]["rows"]), 1)
            self.assertIsNone(files[0]["protected"])
            self.assertEqual(skipped, [])

    def test_protected_file_keeps_its_rows_but_is_labelled(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", 'sys.stdout.reconfigure(encoding="utf-8")\nprint("{}")'.format(GREEN))
            files, _ = pc.scan_paths([tmp], "cp932")
            self.assertEqual(files[0]["protected"], "reconfigure")
            self.assertEqual(len(files[0]["rows"]), 1)

    def test_a_broken_file_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "good.py", 'print("{}")'.format(GREEN))
            write(tmp, "bad.py", "def (:")
            files, skipped = pc.scan_paths([tmp], "cp932")
            self.assertEqual(len(files), 1)
            self.assertEqual(len(skipped), 1)
            self.assertTrue(skipped[0]["path"].endswith("bad.py"))

    def test_a_non_utf8_file_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as tmp:
            (Path(tmp) / "latin.py").write_bytes(b"print('\xff\xfe caf\xe9')")
            files, skipped = pc.scan_paths([tmp], "cp932")
            self.assertEqual(files, [])
            self.assertEqual(len(skipped), 1)

    def test_excludes_are_honoured(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", 'print("{}")'.format(GREEN))
            write(tmp, "test_a.py", 'print("{}")'.format(GREEN))
            files, _ = pc.scan_paths([tmp], "cp932", excludes=["test_*.py"])
            self.assertEqual(len(files), 1)


class TestReport(unittest.TestCase):
    def render(self, src, codec="cp932", **kw):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", src)
            files, skipped = pc.scan_paths([tmp], codec)
            out = io.StringIO()
            pc.report(files, skipped, codec, out=out, **kw)
            return out.getvalue()

    def test_names_the_character(self):
        self.assertIn("U+1F7E2", self.render('print("{}")'.format(GREEN)))

    def test_names_the_call(self):
        self.assertIn("print", self.render('print("{}")'.format(GREEN)))

    def test_says_so_when_there_is_nothing(self):
        self.assertIn("nothing printed here", self.render('print("ok")'))

    def test_marks_a_file_that_decides_an_exit_status(self):
        self.assertIn("decides an exit status",
                      self.render('import sys\nprint("{}")\nsys.exit(1)'.format(GREEN)))

    def test_does_not_mark_a_plain_module(self):
        self.assertNotIn("decides an exit status", self.render('print("{}")'.format(GREEN)))

    def test_the_report_itself_survives_the_codec(self):
        # the whole point: a report about unprintable characters must not print them
        text = self.render('print("{}")  # source line gets quoted back'.format(GREEN))
        text.encode("cp932")
        self.assertIn("<U+1F7E2>", text)

    def test_limit_truncates_and_says_so(self):
        src = "\n".join('print("{}")'.format(GREEN) for _ in range(30))
        self.assertIn("more line(s); pass --all", self.render(src))

    def test_all_shows_everything(self):
        src = "\n".join('print("{}")'.format(GREEN) for _ in range(30))
        self.assertNotIn("more line(s)", self.render(src, show_all=True))

    def test_fix_hint_is_off_by_default(self):
        self.assertNotIn("reconfigure", self.render('print("{}")'.format(GREEN)))

    def test_fix_hint_can_be_asked_for(self):
        self.assertIn("reconfigure", self.render('print("{}")'.format(GREEN), fix_hint=True))

    def test_protected_files_are_listed_separately(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "risk.py", 'print("{}")'.format(GREEN))
            write(tmp, "safe.py",
                  'sys.stdout.reconfigure(encoding="utf-8")\nprint("{}")'.format(GREEN))
            files, skipped = pc.scan_paths([tmp], "cp932")
            out = io.StringIO()
            pc.report(files, skipped, "cp932", out=out)
            text = out.getvalue()
            self.assertIn("pin their own encoding first", text)
            self.assertIn("at risk        1 file(s)", text)
            self.assertIn("protected      1", text)

    def test_skipped_files_are_counted(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "bad.py", "def (:")
            write(tmp, "risk.py", 'print("{}")'.format(GREEN))
            files, skipped = pc.scan_paths([tmp], "cp932")
            out = io.StringIO()
            pc.report(files, skipped, "cp932", out=out)
            self.assertIn("not scanned    1", out.getvalue())


class TestMain(unittest.TestCase):
    def run_main(self, argv):
        out, err = io.StringIO(), io.StringIO()
        old = sys.stdout, sys.stderr
        sys.stdout, sys.stderr = out, err
        try:
            code = pc.main(argv)
        finally:
            sys.stdout, sys.stderr = old
        return code, out.getvalue(), err.getvalue()

    def test_exit_1_when_something_is_at_risk(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", 'print("{}")'.format(GREEN))
            code, _, _ = self.run_main([tmp])
            self.assertEqual(code, 1)

    def test_exit_0_when_nothing_is(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", 'print("ok")')
            code, _, _ = self.run_main([tmp])
            self.assertEqual(code, 0)

    def test_exit_0_when_the_only_hit_is_protected(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py",
                  'sys.stdout.reconfigure(encoding="utf-8")\nprint("{}")'.format(GREEN))
            code, _, _ = self.run_main([tmp])
            self.assertEqual(code, 0)

    def test_exit_2_on_an_unknown_codec(self):
        code, _, err = self.run_main(["--codec", "no-such-codec"])
        self.assertEqual(code, 2)
        self.assertIn("unknown codec", err)

    def test_exit_2_on_a_missing_path(self):
        code, _, err = self.run_main(["no/such/path"])
        self.assertEqual(code, 2)
        self.assertIn("not found", err)

    def test_codec_flag_changes_the_verdict(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", 'print("完了")')
            self.assertEqual(self.run_main([tmp])[0], 0)
            self.assertEqual(self.run_main([tmp, "--codec", "ascii"])[0], 1)

    def test_json_is_ascii_only_and_parses(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", 'print("{}")'.format(GREEN))
            code, out, _ = self.run_main([tmp, "--json"])
            self.assertEqual(code, 1)
            out.encode("ascii")
            data = json.loads(out)
            self.assertEqual(data["codec"], "cp932")
            self.assertEqual(len(data["files"][0]["rows"]), 1)

    def test_json_does_not_carry_the_file_body(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", 'print("{}")'.format(GREEN))
            _, out, _ = self.run_main([tmp, "--json"])
            self.assertNotIn("text", json.loads(out)["files"][0])

    def test_include_logging_flag_reaches_the_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "a.py", 'logging.info("{}")'.format(GREEN))
            self.assertEqual(self.run_main([tmp])[0], 0)
            self.assertEqual(self.run_main([tmp, "--include-logging"])[0], 1)

    def test_exclude_flag_reaches_the_scan(self):
        with tempfile.TemporaryDirectory() as tmp:
            write(tmp, "test_a.py", 'print("{}")'.format(GREEN))
            self.assertEqual(self.run_main([tmp])[0], 1)
            self.assertEqual(self.run_main([tmp, "--exclude", "test_*.py"])[0], 0)


class TestOnItself(unittest.TestCase):
    """The tool has to survive its own rule."""

    def test_the_tool_prints_nothing_cp932_cannot_encode(self):
        files, skipped = pc.scan_paths([str(HERE / "print_codec.py")], "cp932")
        self.assertEqual(skipped, [])
        self.assertEqual(files[0]["rows"], [])

    def test_the_tool_prints_nothing_ascii_cannot_encode(self):
        files, _ = pc.scan_paths([str(HERE / "print_codec.py")], "ascii")
        self.assertEqual(files[0]["rows"], [])

    def test_running_it_on_itself_exits_0(self):
        proc = subprocess.run([sys.executable, str(HERE / "print_codec.py"),
                               str(HERE / "print_codec.py")],
                              capture_output=True)
        self.assertEqual(proc.returncode, 0)

    def test_its_own_output_encodes_as_cp932(self):
        proc = subprocess.run([sys.executable, str(HERE / "print_codec.py"),
                               str(HERE), "--all"], capture_output=True)
        proc.stdout.decode("utf-8").encode("cp932")  # would raise if it printed one


if __name__ == "__main__":
    unittest.main(verbosity=2)

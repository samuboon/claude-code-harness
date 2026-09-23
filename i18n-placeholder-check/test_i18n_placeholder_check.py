# -*- coding: utf-8 -*-
"""Tests for i18n_placeholder_check.py.   python -m unittest test_i18n_placeholder_check -v

The MessageFormat cases follow java.text.MessageFormat.applyPattern and ChoiceFormat.applyPattern
as written in the JDK; each expectation says what Java does with the same pattern.
"""
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout
from pathlib import Path

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import i18n_placeholder_check as t  # noqa: E402


def args_of(p):
    return {k: sorted(v) for k, v in t.arg_types(t.parse_pattern(p)).items()}


class MessageFormatTest(unittest.TestCase):
    def test_plain_and_typed(self):
        self.assertEqual(args_of("{0} of {1,number,integer} on {2,date,short}"),
                         {0: [""], 1: ["number"], 2: ["date"]})

    def test_doubled_apostrophe_is_one_apostrophe(self):
        p = t.parse_pattern("l''utilisateur {0}")
        self.assertEqual(p.render, "l'utilisateur <0>")
        self.assertEqual(p.sections, [])

    def test_lone_apostrophe_swallows_placeholder(self):
        p = t.parse_pattern("l'utilisateur {0} n'existe pas")
        self.assertEqual(p.args, {})
        self.assertEqual(p.render, "lutilisateur {0} nexiste pas")
        # the second apostrophe closes the section the first one opened
        self.assertEqual(p.sections, ["utilisateur {0} n"])

    def test_quoted_brace_is_intentional(self):
        p = t.parse_pattern("'{'0'}' is literal, {0} is not")
        self.assertEqual(sorted(p.args), [0])
        self.assertEqual(p.render, "{0} is literal, <0> is not")

    def test_empty_braces_throw(self):
        with self.assertRaises(t.PatternError):
            t.parse_pattern("value {}")

    def test_name_instead_of_number_throws(self):
        with self.assertRaises(t.PatternError):
            t.parse_pattern("${project.version}")

    def test_space_before_index_throws(self):
        # Integer.parseInt(" 0") fails; MessageFormat does not trim the index
        with self.assertRaises(t.PatternError):
            t.parse_pattern("{ 0}")

    def test_plus_sign_index_is_accepted(self):
        self.assertEqual(args_of("{+1}"), {1: [""]})

    def test_unknown_type_throws(self):
        with self.assertRaises(t.PatternError):
            t.parse_pattern("{0,nombre}")

    def test_type_keyword_is_trimmed_and_case_insensitive(self):
        self.assertEqual(args_of("{0, NUMBER ,integer}"), {0: ["number"]})

    def test_unmatched_open_brace_throws(self):
        with self.assertRaises(t.PatternError):
            t.parse_pattern("Build {0")

    def test_stray_close_brace_is_text(self):
        self.assertEqual(t.parse_pattern("a } b").render, "a } b")

    def test_double_braces_throw(self):
        # "{{0}}": the index segment becomes "{0}", which is not a number
        with self.assertRaises(t.PatternError):
            t.parse_pattern("kataloog {{0}} on")

    def test_jdk_drops_unfinished_argument_with_open_inner_brace(self):
        # applyPattern only throws when braceStack == 0; with an inner brace still open it says nothing
        self.assertEqual(args_of("x {0,choice,0#{1"), {})

    def test_choice_branches_are_parsed_as_messages(self):
        p = "{0,choice,0#no files|1#one file|1<{0,number,integer} files in {1}}"
        self.assertEqual(args_of(p), {0: ["choice", "number"], 1: [""]})

    def test_choice_branch_that_would_throw(self):
        p = t.parse_pattern("{0,choice,0#none|1<{} items}")
        self.assertEqual(len(p.branch_errors), 1)

    def test_choice_bad_limit_throws(self):
        with self.assertRaises(t.PatternError):
            t.parse_pattern("{0,choice,one#a|two#b}")

    def test_choice_limits_out_of_order_throw(self):
        with self.assertRaises(t.PatternError):
            t.parse_pattern("{0,choice,2#a|1#b}")

    def test_choice_accepts_java_double_forms(self):
        self.assertEqual(args_of("{0,choice,0d#a|1.0#b|1e1<c}"), {0: ["choice"]})

    def test_argument_index_limit(self):
        self.assertEqual(args_of("{9999}"), {9999: [""]})
        with self.assertRaises(t.PatternError):
            t.parse_pattern("{10000}")

    def test_infinity_limit_is_compared_before_trimming(self):
        self.assertEqual(args_of("{0,choice,0#none|∞#all}"), {0: ["choice"]})
        with self.assertRaises(t.PatternError):
            t.parse_pattern("{0,choice,0#none| ∞#all}")


class JavaVersionTest(unittest.TestCase):
    def tearDown(self):
        t.JAVA["version"] = 21

    def test_java_25_types_throw_on_21(self):
        with self.assertRaises(t.PatternError):
            t.parse_pattern("{0,dtf_date,full}")
        t.JAVA["version"] = 25
        self.assertEqual(args_of("{0,dtf_date,full} {1,list}"), {0: ["dtf_date"], 1: ["list"]})

    def test_hash_inside_a_choice_branch(self):
        p = "{0,choice,1#build #{1}|1<builds}"
        with self.assertRaises(t.PatternError):     # Java 21: '#' ends a limit that is empty
            t.parse_pattern(p)
        t.JAVA["version"] = 25
        self.assertEqual(args_of(p), {0: ["choice"], 1: [""]})

    def test_cli_flag(self):
        d = Path(tempfile.mkdtemp())
        try:
            (d / "M.properties").write_text("a=On {0,date}\n", encoding="utf-8")
            (d / "M_fr.properties").write_text("a=Le {0,dtf_date}\n", encoding="utf-8")
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(t.main([str(d)]), 1)
                self.assertEqual(t.main([str(d), "--java", "25"]), 0)
        finally:
            shutil.rmtree(d, ignore_errors=True)

    def test_apostrophe_inside_choice_breaks_the_pattern(self):
        # the quote in the style runs to the end, so the closing brace is swallowed
        with self.assertRaises(t.PatternError):
            t.parse_pattern("{0,choice,1#l'element|1<les elements}")


class PropertiesTest(unittest.TestCase):
    def parse(self, text):
        return {k: v for k, (_l, v) in t.parse_properties(text)[0].items()}

    def test_separators(self):
        self.assertEqual(self.parse("a=1\nb:2\nc 3\nd = 4\ne\t:  5\n"),
                         {"a": "1", "b": "2", "c": "3", "d": "4", "e": "5"})

    def test_escaped_separator_in_key(self):
        self.assertEqual(self.parse("Other\\ Jenkins=Autre\nx\\=y=z\n"), {"Other Jenkins": "Autre", "x=y": "z"})

    def test_continuation_strips_leading_space(self):
        self.assertEqual(self.parse("k=one \\\n    two\\\n three\n"), {"k": "one twothree"})

    def test_blank_line_ends_a_continuation(self):
        self.assertEqual(self.parse("k=a\\\n\nm=b\n"), {"k": "a", "m": "b"})

    def test_backslash_at_end_of_file_is_dropped(self):
        self.assertEqual(self.parse("k=a\\"), {"k": "a"})

    def test_even_backslashes_do_not_continue(self):
        self.assertEqual(self.parse("k=a\\\\\nm=b\n"), {"k": "a\\", "m": "b"})

    def test_comments(self):
        self.assertEqual(self.parse("# c\n  ! c2\nk=v # not a comment\n"), {"k": "v # not a comment"})

    def test_unicode_escape(self):
        self.assertEqual(self.parse("k=caf\\u00e9\n"), {"k": "caf\u00e9"})

    def test_malformed_unicode_escape(self):
        with self.assertRaises(t.PropertiesError):
            t.parse_properties("k=\\u00g1\n")

    def test_line_numbers_and_duplicates(self):
        entries, dups = t.parse_properties("a=1\n\nb=long \\\n  value\nc=3\na=4\n")
        self.assertEqual(entries["c"][0], 5)
        self.assertEqual(entries["a"], (6, "4"))
        self.assertEqual(dups, [(6, "a", 1)])


class TreeTest(unittest.TestCase):
    def setUp(self):
        self.dir = Path(tempfile.mkdtemp())

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)

    def write(self, name, text, bom=False):
        p = self.dir / name
        p.parent.mkdir(parents=True, exist_ok=True)
        p.write_bytes((b"\xef\xbb\xbf" if bom else b"") + text.encode("utf-8"))
        return p

    def run_tool(self, *extra):
        out, err = io.StringIO(), io.StringIO()
        with redirect_stdout(out), redirect_stderr(err):
            code = t.main([str(self.dir), "--tsv"] + list(extra))
        rows = [line.split("\t") for line in out.getvalue().splitlines()[1:]]
        return code, [(r[1], Path(r[2]).name, r[4]) for r in rows], err.getvalue()

    def test_clean_bundle_passes(self):
        self.write("Messages.properties", "a=Agent {0} is {1}\nb=Don''t\n")
        self.write("Messages_fr.properties", "a=L''agent {0} est {1}\nb=Ne pas\n")
        code, rows, _ = self.run_tool()
        self.assertEqual((code, rows), (0, []))

    def test_quoted_placeholder_is_an_error(self):
        self.write("Messages.properties", "a=Agent called {0} already exists\n")
        self.write("Messages_pt_BR.properties", "a=O agente chamado '{0}' j\u00e1 existe\n")
        code, rows, _ = self.run_tool()
        self.assertEqual(code, 1)
        self.assertEqual(rows, [("QUOTED", "Messages_pt_BR.properties", "a")])

    def test_apostrophe_without_placeholder_in_arg_message(self):
        self.write("Messages.properties", "a={0} does not exist\n")
        self.write("Messages_fr.properties", "a={0} n'existe pas\n")
        code, rows, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(rows, [("APOS", "Messages_fr.properties", "a")])
        self.assertEqual(self.run_tool("--strict")[0], 1)

    def test_no_arg_message_apostrophe_only_with_always(self):
        self.write("Messages.properties", "a=Password did not match\n")
        self.write("Messages_it.properties", "a=Password dell'utente errata\n")
        self.assertEqual(self.run_tool()[1], [])
        self.assertEqual(self.run_tool("--always-messageformat")[1], [("APOS", "Messages_it.properties", "a")])

    def test_missing_extra_broken(self):
        self.write("Messages.properties", "a={0} of {1}\nb=Ready\nc=Run {0}\n")
        self.write("Messages_de.properties", "a={0}\nb=Bereit {0}\nc=Lauf {0\n")
        code, rows, _ = self.run_tool()
        self.assertEqual(code, 1)
        self.assertEqual(sorted(rows), [("BROKEN", "Messages_de.properties", "c"),
                                        ("EXTRA", "Messages_de.properties", "b"),
                                        ("MISSING", "Messages_de.properties", "a")])

    def test_extra_index_beyond_base(self):
        self.write("Messages.properties", "a=Version {1}\n")
        self.write("Messages_bg.properties", "a={0} {1}\n")
        self.assertEqual(self.run_tool()[1], [("EXTRA", "Messages_bg.properties", "a")])

    def test_plural_added_is_a_note(self):
        self.write("Messages.properties", "a={0} yr\n")
        self.write("Messages_ru.properties", "a={0,choice,1#{0} \u0433\u043e\u0434|2#{0} \u0433\u043e\u0434\u0430}\n")
        code, rows, _ = self.run_tool()
        self.assertEqual((code, rows), (0, [("TYPE", "Messages_ru.properties", "a")]))

    def test_dropping_a_type_is_not_reported(self):
        self.write("Messages.properties", "a={0,number,integer} builds\n")
        self.write("Messages_ja.properties", "a={0} \u4ef6\n")
        self.assertEqual(self.run_tool()[1], [])

    def test_orphan_and_duplicate_are_notes(self):
        self.write("Messages.properties", "a=A\n")
        self.write("Messages_fr.properties", "a=A1\na=A2\nold=Vieux\n")
        code, rows, _ = self.run_tool()
        self.assertEqual(code, 0)
        self.assertEqual(sorted(rows), [("DUP", "Messages_fr.properties", "a"),
                                        ("ORPHAN", "Messages_fr.properties", "old")])
        self.assertEqual(self.run_tool("--no-notes")[1], [])

    def test_orphan_value_is_still_checked(self):
        self.write("index.properties", "a=A\n")
        self.write("index_fr.properties", "Other\\ Jenkins=L'autre instance\n")
        rows = self.run_tool("--always-messageformat")[1]
        self.assertIn(("APOS", "index_fr.properties", "Other Jenkins"), rows)

    def test_bad_unicode_escape_fails_the_file(self):
        self.write("Messages.properties", "a=A {0}\n")
        self.write("Messages_fr.properties", "a=\\u00e {0}\n")
        code, rows, _ = self.run_tool()
        self.assertEqual((code, rows), (1, [("BADFILE", "Messages_fr.properties", "")]))

    def test_bom_is_reported_on_the_first_key(self):
        self.write("Messages.properties", "a=A {0}\nb=B\n")
        self.write("Messages_fr.properties", "a=A {0}\nb=B\n", bom=True)
        rows = self.run_tool()[1]
        self.assertIn(("BOM", "Messages_fr.properties", "a"), rows)

    def test_bom_before_a_comment_is_harmless(self):
        self.write("Messages.properties", "a=A {0}\n")
        self.write("Messages_fr.properties", "# comment\na=A {0}\n", bom=True)
        self.assertEqual(self.run_tool()[1], [])

    def test_locale_forms_and_underscored_stem(self):
        self.write("config_sample.properties", "a=A {0}\n")
        self.write("config_sample_pt_BR.properties", "a=A\n")
        self.write("config_sample_zh_Hant_TW.properties", "a=A\n")
        rows = self.run_tool()[1]
        self.assertEqual(sorted(r[1] for r in rows),
                         ["config_sample_pt_BR.properties", "config_sample_zh_Hant_TW.properties"])

    def test_longest_existing_stem_wins(self):
        # help_ant_de could be help + "ant_de" or help_ant + "de"; help_ant.properties exists, so the latter
        self.write("help.properties", "a=A\n")
        self.write("help_ant.properties", "a=Ant {0}\n")
        self.write("help_ant_de.properties", "a=Ameise\n")
        rows = sorted(self.run_tool()[1])
        self.assertEqual(rows, [("EXTRA", "help_ant.properties", "a"), ("MISSING", "help_ant_de.properties", "a")])

    def test_no_base_file_is_exit_3(self):
        self.write("view/index_fr.properties", "Build\\ {0}=Construire\n")
        code, rows, err = self.run_tool()
        self.assertEqual((code, rows), (3, []))
        self.assertIn("no base file", err)

    def test_key_as_base_for_text_keys_only(self):
        self.write("view/index_fr.properties", "Build\\ {0}=Construire\nblurb=Texte {0}\n")
        code, rows, _ = self.run_tool("--key-as-base")
        self.assertEqual((code, rows), (0, [("MISSING", "index_fr.properties", "Build {0}")]))

    def test_base_locale(self):
        self.write("Messages_en.properties", "a=A {0}\n")
        self.write("Messages_fr.properties", "a=A\n")
        self.assertEqual(self.run_tool()[0], 3)
        code, rows, _ = self.run_tool("--base-locale", "en")
        self.assertEqual(rows, [("MISSING", "Messages_fr.properties", "a")])

    def test_standalone_file_is_configuration_by_default(self):
        self.write("version.properties", "version=${project.version}\n")
        self.assertEqual(self.run_tool()[:2], (0, []))
        self.assertEqual(self.run_tool("--always-messageformat")[1], [("BROKEN", "version.properties", "version")])

    def test_nothing_to_check_is_exit_2(self):
        self.write("readme.txt", "x")
        self.assertEqual(self.run_tool()[0], 2)


if __name__ == "__main__":
    unittest.main()

# -*- coding: utf-8 -*-
"""Tests for permission_gap.py.

    python -m unittest test_permission_gap -v

Every case here was written against a real record shape taken from a transcript on
disk, not from an idea of what one looks like. The four denial strings in
DENIALS are verbatim (paths and names replaced).
"""
import json
import sys
import tempfile
import unittest
from datetime import datetime, timezone
from pathlib import Path

sys.path.insert(0, str(Path(__file__).resolve().parent))
import permission_gap as pg  # noqa: E402

CLASSIFIER_TAGGED = ("Permission for this action was denied by the Claude Code auto mode classifier. "
                     "Reason: [Create Public Surface]. If you have other tasks that don't depend on "
                     "this action, continue working on those.")
CLASSIFIER_BARE = ("Permission for this action was denied by the Claude Code auto mode classifier. "
                   "Reason: Blocked by classifier. If you have other tasks that don't depend on this action, "
                   "continue working on those.")
ALLOWLIST = 'Permission to use Bash with command rm -rf "/tmp/x" && echo done has been denied.'
HUMAN = ("The user doesn't want to proceed with this tool use. The tool use was rejected "
         "(eg. if it was a file edit, the new_string was NOT written to the file).")
OWN_HOOK = ('PreToolUse:Bash hook error: [python "${CLAUDE_PROJECT_DIR:-.}/.claude/hooks/guard.py"]: '
            "BLOCKED(outside the project: /c/Program)\nonly this project and the scratchpad.")


class TestClassifyDenial(unittest.TestCase):
    def test_classifier_tag_is_taken_out_of_the_brackets(self):
        self.assertEqual(pg.classify_denial(CLASSIFIER_TAGGED)[:2], ("classifier", "Create Public Surface"))

    def test_classifier_without_brackets_keeps_the_bare_reason(self):
        layer, reason, _, _ = pg.classify_denial(CLASSIFIER_BARE)
        self.assertEqual(layer, "classifier")
        self.assertEqual(reason, "Blocked by classifier")

    def test_classifier_with_no_reason_at_all_is_still_a_denial(self):
        layer, reason, _, _ = pg.classify_denial(
            "Permission for this action was denied by the Claude Code auto mode classifier.")
        self.assertEqual(layer, "classifier")
        self.assertEqual(reason, "(no reason given)")

    def test_allowlist_denial_carries_its_own_tool_and_command(self):
        layer, reason, tool, cmd = pg.classify_denial(ALLOWLIST)
        self.assertEqual((layer, reason, tool), ("allowlist", "not granted", "Bash"))
        self.assertIn("rm -rf", cmd)

    def test_allowlist_denial_phrased_as_not_granted(self):
        layer, _, tool, _ = pg.classify_denial("Permission to use Write with command x has not been granted")
        self.assertEqual((layer, tool), ("allowlist", "Write"))

    def test_human_rejection(self):
        self.assertEqual(pg.classify_denial(HUMAN)[0], "human")

    def test_own_hook_keeps_only_the_first_line_of_its_message(self):
        layer, reason, tool, _ = pg.classify_denial(OWN_HOOK)
        self.assertEqual((layer, tool), ("own-hook", "Bash"))
        self.assertEqual(reason, "BLOCKED(outside the project: /c/Program)")

    def test_an_ordinary_error_is_not_a_denial(self):
        self.assertIsNone(pg.classify_denial("Exit code 1\nTraceback (most recent call last):"))

    def test_the_agent_quoting_the_denial_in_its_own_notes_is_not_a_denial(self):
        # the trap this tool exists to avoid: grep counts these, the tool must not
        prose = ("| IMP-61 | the classifier refused again. Verbatim: `Permission for this action was "
                 "denied by the Claude Code auto mode classifier. Reason: [Create Public Surface].`")
        self.assertIsNone(pg.classify_denial(prose))

    def test_empty_and_non_string(self):
        self.assertIsNone(pg.classify_denial(""))
        self.assertIsNone(pg.classify_denial(None))


class TestRedact(unittest.TestCase):
    def test_token_shaped_strings_are_masked(self):
        out = pg.redact("git push https://ghp_AbCdEf123456789@github.com/x/y")
        self.assertNotIn("ghp_AbCdEf123456789", out)
        self.assertIn("<redacted>", out)

    def test_long_hex_is_masked(self):
        self.assertIn("<redacted>", pg.redact("key=" + "a1b2c3d4" * 4))

    def test_ordinary_text_survives(self):
        self.assertEqual(pg.redact("python tools/gh_api.py post"), "python tools/gh_api.py post")


class TestCommandShape(unittest.TestCase):
    def test_cd_prefix_is_dropped_and_the_real_stage_kept(self):
        self.assertEqual(
            pg.command_shape('cd "C:/p r/OTK" && python tools/gh_api.py post /repos/a/b/releases body.json'),
            "python gh_api.py post <path>")

    def test_leading_variable_assignment_with_slashes_is_dropped(self):
        self.assertEqual(pg.command_shape('SP="C:/tmp/a/scratchpad"; python tools/x.py sync'),
                         "python x.py sync")

    def test_a_stage_that_only_sets_variables_is_not_the_command(self):
        self.assertEqual(pg.command_shape('SP="C:/tmp/scratchpad";'), "")

    def test_heredoc_body_is_not_part_of_the_shape(self):
        self.assertEqual(pg.command_shape("cd /x && python - <<'EOF'\nimport json\nprint(1)\nEOF"),
                         "python - <heredoc>")

    def test_redirect_ends_the_shape(self):
        self.assertEqual(pg.command_shape('echo "hello" > notes.md'), "echo <arg> <redirect>")

    def test_inline_code_is_not_mistaken_for_a_script_name(self):
        a = pg.command_shape('python -c "import json; print(json.dumps({}))"')
        b = pg.command_shape('python -c "import os; os.listdir()"')
        self.assertEqual(a, "python -c <code>")
        self.assertEqual(a, b)

    def test_env_prefix_and_interpreter_flags_are_kept_separately(self):
        self.assertEqual(pg.command_shape("PYTHONUTF8=1 python -m unittest test_x"),
                         "python -m unittest test_x")

    def test_url_becomes_a_placeholder_so_two_urls_share_a_shape(self):
        a = pg.command_shape("curl -s https://example.com/a")
        b = pg.command_shape("curl -s https://other.example/b")
        self.assertEqual(a, b)
        self.assertEqual(a, "curl -s <url>")

    def test_an_id_shaped_argument_is_not_mistaken_for_a_subcommand(self):
        self.assertEqual(pg.command_shape("rm -rf ORD-20260905-34"), "rm -rf <arg>")

    def test_shape_is_capped_so_long_commands_still_group(self):
        self.assertEqual(len(pg.command_shape("git commit -m msg extra tail more").split()),
                         pg.MAX_SHAPE_TOKENS)

    def test_quoted_run_with_spaces_stays_one_token(self):
        self.assertEqual(pg.command_shape('git commit -m "two words"'), "git commit -m <arg>")

    def test_empty_command(self):
        self.assertEqual(pg.command_shape(""), "")
        self.assertEqual(pg.command_shape(None), "")

    def test_pipe_takes_the_first_working_stage_and_a_filename_is_not_identity(self):
        # two `cat` calls on different files are the same action, so they share a shape
        self.assertEqual(pg.command_shape("cat notes.md | head -5"), "cat <arg>")
        self.assertEqual(pg.command_shape("cat other.md | wc -l"), "cat <arg>")


class TestRequestShape(unittest.TestCase):
    def test_bash_uses_the_command(self):
        self.assertEqual(pg.request_shape("Bash", {"command": "python tools/gh_push.py sync"}),
                         "python gh_push.py sync")

    def test_a_write_is_grouped_by_extension(self):
        self.assertEqual(pg.request_shape("Write", {"file_path": "/a/b/STATUS.md"}), "Write .md")

    def test_a_fetch_is_grouped_by_host(self):
        self.assertEqual(pg.request_shape("WebFetch", {"url": "https://booth.pm/ja/items/1?x=2"}),
                         "WebFetch booth.pm")

    def test_an_mcp_tool_with_no_useful_input_is_its_own_shape(self):
        self.assertEqual(pg.request_shape("mcp__x__evaluate", {"fn": "() => 1"}), "mcp__x__evaluate")

    def test_command_embedded_in_the_denial_is_used_when_the_request_is_missing(self):
        self.assertEqual(pg.request_shape(None, None, "rm -rf /tmp/x"), "rm -rf <path>")

    def test_a_bash_call_with_no_command_falls_back_to_the_tool_name(self):
        self.assertEqual(pg.request_shape("Bash", {}), "Bash")


class TestAllowMatch(unittest.TestCase):
    RULES = [("Bash(python tools/gh_api.py post:*)", "s.json"),
             ("Bash(cd *)", "s.json"),
             ("Read(//c/Users/x/**)", "s.json"),
             ("Write", "s.json")]

    def test_prefix_rule_covers_the_matching_command(self):
        hit = pg.allow_match(self.RULES, "Bash", "python tools/gh_api.py post /repos/a/b/releases b.json")
        self.assertEqual(hit[0], "Bash(python tools/gh_api.py post:*)")

    def test_cd_rule_does_not_cover_what_was_chained_after_the_cd(self):
        self.assertIsNone(pg.allow_match(self.RULES, "Bash", 'cd "/x" && rm -rf /y'))

    def test_a_rule_for_one_tool_never_covers_another(self):
        self.assertIsNone(pg.allow_match(self.RULES, "Bash", "cat /c/Users/x/a.md"))
        # and it stays None when the pattern would otherwise match the command exactly
        same_text = [("Read(python tools/x.py:*)", "s.json")]
        self.assertIsNone(pg.allow_match(same_text, "Bash", "python tools/x.py go"))
        self.assertIsNotNone(pg.allow_match(same_text, "Read", "python tools/x.py go"))

    def test_a_bare_tool_rule_covers_that_tool(self):
        self.assertEqual(pg.allow_match(self.RULES, "Write", None)[0], "Write")

    def test_no_rules_means_no_match(self):
        self.assertIsNone(pg.allow_match([], "Bash", "python x.py"))

    def test_star_rule_covers_a_call_with_no_command(self):
        self.assertIsNotNone(pg.allow_match([("Bash(*)", "s")], "Bash", None))

    def test_parse_allow_rules_reads_only_what_is_there(self):
        with tempfile.TemporaryDirectory() as d:
            good = Path(d) / "settings.json"
            good.write_text(json.dumps({"permissions": {"allow": ["Bash(git status:*)", ""]}}), encoding="utf-8")
            rules = pg.parse_allow_rules([good, Path(d) / "missing.json"])
        self.assertEqual([r[0] for r in rules], ["Bash(git status:*)"])

    def test_broken_settings_file_is_skipped_not_fatal(self):
        with tempfile.TemporaryDirectory() as d:
            bad = Path(d) / "settings.json"
            bad.write_text("{not json", encoding="utf-8")
            self.assertEqual(pg.parse_allow_rules([bad]), [])


def _line(rec):
    return json.dumps(rec, ensure_ascii=False)


def _use(tid, tool, inp, ts="2026-09-17T01:00:00.000Z", sidechain=False):
    return _line({"type": "assistant", "timestamp": ts, "sessionId": "s1", "isSidechain": sidechain,
                  "message": {"role": "assistant", "content": [
                      {"type": "tool_use", "id": tid, "name": tool, "input": inp}]}})


def _result(tid, text, is_error=True, ts="2026-09-17T01:00:05.000Z", session="s1", sidechain=False):
    return _line({"type": "user", "timestamp": ts, "sessionId": session, "isSidechain": sidechain,
                  "message": {"role": "user", "content": [
                      {"type": "tool_result", "tool_use_id": tid, "is_error": is_error, "content": text}]}})


class TestReadEvents(unittest.TestCase):
    def test_a_use_and_its_result_are_paired_by_id(self):
        requests, results = pg.read_events([_use("t1", "Bash", {"command": "ls"}), _result("t1", "ok", False)])
        self.assertEqual(requests["t1"]["tool"], "Bash")
        self.assertEqual(results[0]["id"], "t1")

    def test_lines_that_are_neither_are_skipped(self):
        requests, results = pg.read_events([_line({"type": "summary", "summary": "x"}), "not json at all"])
        self.assertEqual((requests, results), ({}, []))

    def test_result_content_given_as_blocks_is_joined(self):
        _, results = pg.read_events([_line({"type": "user", "timestamp": "2026-09-17T01:00:00Z",
                                            "message": {"content": [
                                                {"type": "tool_result", "tool_use_id": "t", "is_error": True,
                                                 "content": [{"type": "text", "text": HUMAN}]}]}})])
        self.assertTrue(results[0]["text"].startswith("The user doesn't"))

    def test_a_giant_result_is_truncated_not_read_whole(self):
        _, results = pg.read_events([_result("t", "x" * (pg.MAX_TEXT * 3))])
        self.assertEqual(len(results[0]["text"]), pg.MAX_TEXT)

    def test_subagent_flag_is_carried(self):
        requests, _ = pg.read_events([_use("t1", "Bash", {"command": "ls"}, sidechain=True)])
        self.assertTrue(requests["t1"]["sidechain"])


class TestCollectAndAnalyze(unittest.TestCase):
    def _scan(self, lines, rules=(), window=120, **kw):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.jsonl"
            f.write_text("\n".join(lines), encoding="utf-8")
            collected = pg.collect([f], **kw)
        return collected, pg.analyze(collected, allow_rules=rules, window=window)

    def test_each_layer_is_counted_in_its_own_column(self):
        lines = [_use("a", "Bash", {"command": "rm -rf /x"}), _result("a", ALLOWLIST),
                 _use("b", "Bash", {"command": "python tools/gh_api.py post /r b.json"}),
                 _result("b", CLASSIFIER_TAGGED),
                 _use("c", "Bash", {"command": "cat /c/Program/x"}), _result("c", OWN_HOOK),
                 _use("d", "Write", {"file_path": "/x/a.md"}), _result("d", HUMAN)]
        _, rep = self._scan(lines)
        self.assertEqual(rep["by_layer"], {"own-hook": 1, "allowlist": 1, "classifier": 1, "human": 1})
        self.assertEqual(rep["totals"]["denials"], 4)

    def test_a_call_that_ran_is_counted_as_ran_not_denied(self):
        lines = [_use("a", "Bash", {"command": "python tools/x.py sync"}), _result("a", "done", False)]
        _, rep = self._scan(lines)
        self.assertEqual((rep["totals"]["denials"], rep["totals"]["calls_that_ran"]), (0, 1))

    def test_an_error_that_is_not_a_denial_counts_as_having_run(self):
        lines = [_use("a", "Bash", {"command": "python tools/x.py sync"}),
                 _result("a", "Exit code 1\nTraceback", True)]
        _, rep = self._scan(lines)
        self.assertEqual((rep["totals"]["denials"], rep["totals"]["calls_that_ran"]), (0, 1))

    def test_flapping_needs_the_same_shape_on_both_sides(self):
        lines = [_use("a", "Bash", {"command": "python tools/x.py sync"}), _result("a", CLASSIFIER_TAGGED),
                 _use("b", "Bash", {"command": "python tools/x.py sync"}), _result("b", "ok", False),
                 _use("c", "Bash", {"command": "python tools/y.py sync"}), _result("c", CLASSIFIER_TAGGED)]
        _, rep = self._scan(lines)
        self.assertEqual([f["shape"] for f in rep["flapping"]], ["python x.py sync"])
        self.assertEqual((rep["flapping"][0]["denied"], rep["flapping"][0]["ran"]), (1, 1))

    def test_a_wall_is_three_denials_with_no_success_at_all(self):
        lines = []
        for i in range(3):
            lines += [_use("w%d" % i, "Bash", {"command": "python tools/gh_api.py post /r b.json"}),
                      _result("w%d" % i, CLASSIFIER_TAGGED)]
        _, rep = self._scan(lines)
        self.assertEqual([w["shape"] for w in rep["walls"]], ["python gh_api.py post <path>"])
        self.assertEqual(rep["walls"][0]["denied"], 3)

    def test_two_denials_are_not_a_wall_yet(self):
        lines = []
        for i in range(2):
            lines += [_use("w%d" % i, "Bash", {"command": "python tools/gh_api.py post /r b.json"}),
                      _result("w%d" % i, CLASSIFIER_TAGGED)]
        _, rep = self._scan(lines)
        self.assertEqual(rep["walls"], [])

    def test_a_shape_that_ever_ran_is_not_a_wall(self):
        lines = [_use("x", "Bash", {"command": "python tools/a.py go"}), _result("x", "ok", False)]
        for i in range(3):
            lines += [_use("w%d" % i, "Bash", {"command": "python tools/a.py go"}),
                      _result("w%d" % i, CLASSIFIER_TAGGED)]
        _, rep = self._scan(lines)
        self.assertEqual(rep["walls"], [])

    def test_collateral_only_counts_a_different_shape_inside_the_window(self):
        lines = [_use("a", "Bash", {"command": "python tools/a.py go"}),
                 _result("a", CLASSIFIER_TAGGED, ts="2026-09-17T01:00:00.000Z"),
                 _use("b", "Bash", {"command": "grep -n x notes.md"}),
                 _result("b", CLASSIFIER_BARE, ts="2026-09-17T01:00:30.000Z")]
        _, rep = self._scan(lines)
        self.assertEqual(len(rep["collateral"]), 1)
        self.assertEqual(rep["collateral"][0]["seconds"], 30.0)

    def test_outside_the_window_it_is_not_collateral(self):
        lines = [_use("a", "Bash", {"command": "python tools/a.py go"}),
                 _result("a", CLASSIFIER_TAGGED, ts="2026-09-17T01:00:00.000Z"),
                 _use("b", "Bash", {"command": "grep -n x notes.md"}),
                 _result("b", CLASSIFIER_BARE, ts="2026-09-17T01:10:00.000Z")]
        _, rep = self._scan(lines)
        self.assertEqual(rep["collateral"], [])

    def test_a_denial_in_another_session_is_not_collateral(self):
        lines = [_use("a", "Bash", {"command": "python tools/a.py go"}),
                 _result("a", CLASSIFIER_TAGGED, ts="2026-09-17T01:00:00.000Z", session="s1"),
                 _use("b", "Bash", {"command": "grep -n x notes.md"}),
                 _result("b", CLASSIFIER_BARE, ts="2026-09-17T01:00:10.000Z", session="s2")]
        _, rep = self._scan(lines)
        self.assertEqual(rep["collateral"], [])

    def test_self_denied_is_the_headline_and_excludes_your_own_hook(self):
        rules = [("Bash(python tools/gh_api.py post:*)", "s.json")]
        lines = [_use("a", "Bash", {"command": "python tools/gh_api.py post /r b.json"}),
                 _result("a", CLASSIFIER_TAGGED),
                 _use("b", "Bash", {"command": "python tools/gh_api.py post /r c.json"}),
                 _result("b", OWN_HOOK)]
        _, rep = self._scan(lines, rules=rules)
        self.assertEqual(len(rep["self_denied"]), 1)
        self.assertEqual(rep["self_denied"][0]["layer"], "classifier")

    def test_since_and_until_cut_the_window(self):
        lines = [_use("a", "Bash", {"command": "rm -rf /x"}),
                 _result("a", ALLOWLIST, ts="2026-09-01T01:00:00.000Z"),
                 _use("b", "Bash", {"command": "rm -rf /y"}),
                 _result("b", ALLOWLIST, ts="2026-09-16T01:00:00.000Z")]
        _, rep = self._scan(lines, since=datetime(2026, 9, 10, tzinfo=timezone.utc))
        self.assertEqual(rep["totals"]["denials"], 1)
        _, rep2 = self._scan(lines, until=datetime(2026, 9, 10, tzinfo=timezone.utc))
        self.assertEqual(rep2["totals"]["denials"], 1)

    def test_denials_inside_subagents_are_counted_separately(self):
        lines = [_use("a", "Bash", {"command": "rm -rf /x"}, sidechain=True),
                 _result("a", ALLOWLIST, sidechain=True)]
        _, rep = self._scan(lines)
        self.assertEqual(rep["totals"]["in_subagents"], 1)

    def test_by_day_groups_by_the_date_of_the_result(self):
        lines = [_use("a", "Bash", {"command": "rm -rf /x"}),
                 _result("a", ALLOWLIST, ts="2026-09-15T23:00:00.000Z"),
                 _use("b", "Bash", {"command": "rm -rf /y"}),
                 _result("b", ALLOWLIST, ts="2026-09-16T01:00:00.000Z")]
        _, rep = self._scan(lines)
        self.assertEqual([r["day"] for r in rep["by_day"]], ["2026-09-15", "2026-09-16"])


class TestRecovery(unittest.TestCase):
    """What happened after the refusal. Every case here turns on the direction of the clock."""

    def _scan(self, lines, **kw):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.jsonl"
            f.write_text("\n".join(lines), encoding="utf-8")
            collected = pg.collect([f], **kw)
        return collected, pg.analyze(collected)

    def _denied_then(self, second_ok, gap_minutes=7):
        """One classifier refusal at 01:00, then the same shape again `gap_minutes` later."""
        t1, t2 = "2026-09-17T01:00:00.000Z", "2026-09-17T01:%02d:00.000Z" % gap_minutes
        return [_use("a", "Bash", {"command": "python tools/gh_push.py sync public/x"}, ts=t1),
                _result("a", CLASSIFIER_TAGGED, ts=t1),
                _use("b", "Bash", {"command": "python tools/gh_push.py sync public/x"}, ts=t2),
                _result("b", "done" if second_ok else CLASSIFIER_TAGGED, is_error=not second_ok, ts=t2)]

    def test_a_refusal_the_retry_cleared_is_counted_as_recovered_with_its_wait(self):
        _, rep = self._scan(self._denied_then(True, gap_minutes=7))
        row = rep["recovery"]["classifier"]
        self.assertEqual((row["denials"], row["recovered"], row["never"]), (1, 1, 0))
        self.assertEqual(row["median_wait_min"], 7.0)

    def test_a_refusal_the_retry_did_not_clear_is_not_recovered(self):
        _, rep = self._scan(self._denied_then(False))
        row = rep["recovery"]["classifier"]
        self.assertEqual((row["recovered"], row["never"]), (0, 2))
        self.assertIsNone(row["median_wait_min"])

    def test_a_success_before_the_refusal_does_not_count_as_recovery(self):
        """The bug this column exists to avoid: reading a clean run from the past as a retry."""
        lines = [_use("a", "Bash", {"command": "python tools/gh_api.py post /r a.json"},
                      ts="2026-09-17T00:30:00.000Z"),
                 _result("a", "created", is_error=False, ts="2026-09-17T00:30:00.000Z"),
                 _use("b", "Bash", {"command": "python tools/gh_api.py post /r b.json"},
                      ts="2026-09-17T01:00:00.000Z"),
                 _result("b", CLASSIFIER_TAGGED, ts="2026-09-17T01:00:00.000Z")]
        _, rep = self._scan(lines)
        row = rep["recovery"]["classifier"]
        self.assertEqual((row["recovered"], row["never"]), (0, 1))
        self.assertEqual(row["ran_before"], 1)

    def test_a_shape_never_attempted_again_is_named_separately_from_one_that_was(self):
        _, rep = self._scan(self._denied_then(False))
        row = rep["recovery"]["classifier"]
        # two refusals: the first was tried again, the second never was
        self.assertEqual(row["not_tried_again"], 1)

    def test_an_errored_result_is_not_a_recovery(self):
        t1, t2 = "2026-09-17T01:00:00.000Z", "2026-09-17T01:05:00.000Z"
        lines = [_use("a", "Bash", {"command": "python tools/gh_push.py sync public/x"}, ts=t1),
                 _result("a", CLASSIFIER_TAGGED, ts=t1),
                 _use("b", "Bash", {"command": "python tools/gh_push.py sync public/x"}, ts=t2),
                 _result("b", "fatal: could not read from remote", is_error=True, ts=t2)]
        _, rep = self._scan(lines)
        self.assertEqual(rep["recovery"]["classifier"]["recovered"], 0)

    def test_the_buckets_are_cumulative_and_use_the_real_wait(self):
        _, rep = self._scan(self._denied_then(True, gap_minutes=3))
        within = rep["recovery"]["classifier"]["within"]
        self.assertEqual((within["1"], within["5"], within["1440"]), (0, 1, 1))

    def test_recovery_is_reported_per_layer_not_pooled(self):
        lines = self._denied_then(True) + [
            _use("c", "Bash", {"command": "cat /c/Program/x"}, ts="2026-09-17T02:00:00.000Z"),
            _result("c", OWN_HOOK, ts="2026-09-17T02:00:00.000Z")]
        _, rep = self._scan(lines)
        self.assertEqual(rep["recovery"]["classifier"]["recovered"], 1)
        self.assertEqual(rep["recovery"]["own-hook"]["recovered"], 0)

    def test_the_wait_is_to_the_first_success_even_when_the_file_is_out_of_order(self):
        """Transcripts are not always written in clock order; the wait must still be the first one."""
        lines = [_use("a", "Bash", {"command": "python tools/gh_push.py sync public/x"},
                      ts="2026-09-17T01:00:00.000Z"),
                 _result("a", CLASSIFIER_TAGGED, ts="2026-09-17T01:00:00.000Z"),
                 _use("c", "Bash", {"command": "python tools/gh_push.py sync public/x"},
                      ts="2026-09-17T01:40:00.000Z"),
                 _result("c", "done", is_error=False, ts="2026-09-17T01:40:00.000Z"),
                 _use("b", "Bash", {"command": "python tools/gh_push.py sync public/x"},
                      ts="2026-09-17T01:04:00.000Z"),
                 _result("b", "done", is_error=False, ts="2026-09-17T01:04:00.000Z")]
        _, rep = self._scan(lines)
        self.assertEqual(rep["recovery"]["classifier"]["median_wait_min"], 4.0)

    def test_the_recovery_block_reaches_the_screen(self):
        collected, rep = self._scan(self._denied_then(True))
        text = pg.render(rep)
        self.assertIn("AFTER THE REFUSAL", text)
        self.assertIn("1 (100%)", text)


class TestRenderAndCli(unittest.TestCase):
    def test_render_says_so_when_nothing_was_denied(self):
        rep = pg.analyze({"denials": [], "ran": {}, "files": 1, "results": 3})
        self.assertIn("no denials", pg.render(rep))

    def test_render_does_not_leak_a_token_shaped_string(self):
        collected = {"denials": [{"layer": "classifier", "reason": "Create Public Surface", "tool": "Bash",
                                  "shape": "git push <url>", "command": "git push https://ghp_SECRETSECRET1@x/y",
                                  "when": None, "day": "2026-09-17", "session": "s", "sidechain": False,
                                  "source": "t"}],
                     "ran": {}, "files": 1, "results": 1}
        out = pg.render(pg.analyze(collected), show_raw=True, denials=collected["denials"])
        self.assertNotIn("ghp_SECRETSECRET1", out)

    def test_cli_on_a_real_file_exits_zero_and_prints_the_layers(self):
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.jsonl"
            f.write_text("\n".join([_use("a", "Bash", {"command": "rm -rf /x"}), _result("a", ALLOWLIST)]),
                         encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                code = pg.main(["scan", "--file", str(f)])
        self.assertEqual(code, 0)
        self.assertIn("allowlist (needs a human)", buf.getvalue())

    def test_cli_json_is_parseable_and_carries_the_denials(self):
        import io
        import contextlib
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.jsonl"
            f.write_text("\n".join([_use("a", "Bash", {"command": "rm -rf /x"}), _result("a", ALLOWLIST)]),
                         encoding="utf-8")
            buf = io.StringIO()
            with contextlib.redirect_stdout(buf):
                pg.main(["scan", "--file", str(f), "--json"])
        payload = json.loads(buf.getvalue())
        self.assertEqual(payload["by_layer"]["allowlist"], 1)
        self.assertEqual(payload["denials"][0]["shape"], "rm -rf <path>")

    def test_cli_returns_two_when_there_is_nothing_to_read(self):
        with tempfile.TemporaryDirectory() as d:
            self.assertEqual(pg.main(["scan", "--dir", str(Path(d) / "nope")]), 2)

    def test_cli_returns_two_when_a_file_has_no_tool_results(self):
        with tempfile.TemporaryDirectory() as d:
            f = Path(d) / "t.jsonl"
            f.write_text(_line({"type": "summary", "summary": "x"}), encoding="utf-8")
            self.assertEqual(pg.main(["scan", "--file", str(f)]), 2)

    def test_cli_rejects_a_bad_date(self):
        self.assertEqual(pg.main(["scan", "--since", "last tuesday"]), 1)


if __name__ == "__main__":
    unittest.main(verbosity=2)

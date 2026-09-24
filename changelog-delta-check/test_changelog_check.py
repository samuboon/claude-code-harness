# -*- coding: utf-8 -*-
"""Tests for changelog_check.py (python -m unittest test_changelog_check)."""
import datetime as dt
import io
import os
import shutil
import tempfile
import unittest
from contextlib import redirect_stdout

import changelog_check as t

TODAY = dt.date(2024, 6, 1)


def run(text, as_of=TODAY):
    f, st, entries = t.check_text("CHANGELOG.md", text, as_of)
    return sorted(x.code for x in f if x.level == "error"), sorted(x.code for x in f if x.level == "warning"), f, st, entries


def kac(*entries, links=""):
    """A Keep a Changelog file: entries are (version, date) pairs, newest first."""
    body = "# Changelog\n\n## [Unreleased]\n\n"
    for v, d in entries:
        body += "## [%s] - %s\n### Fixed\n- something\n\n" % (v, d)
    return body + links


class Reading(unittest.TestCase):
    def test_keep_a_changelog(self):
        e, w, f, st, entries = run(kac(("1.2.0", "2024-03-01"), ("1.1.0", "2024-02-01")))
        self.assertEqual([x.raw for x in entries], ["1.2.0", "1.1.0"])
        self.assertEqual(entries[0].date, dt.date(2024, 3, 1))
        self.assertEqual(e, [])

    def test_unreleased_is_not_an_entry(self):
        e, w, f, st, entries = run(kac(("1.0.0", "2024-01-01")))
        self.assertEqual(len(entries), 1)

    def test_conventional_changelog_heading(self):
        text = ("# Changelog\n\n## [1.3.0](https://github.com/o/r/compare/v1.2.0...v1.3.0) (2024-03-02)\n\n"
                "### Features\n\n* x\n\n## [1.2.0](https://github.com/o/r/compare/v1.1.0...v1.2.0) (2024-02-02)\n")
        e, w, f, st, entries = run(text)
        self.assertEqual([(x.raw, x.date) for x in entries],
                         [("1.3.0", dt.date(2024, 3, 2)), ("1.2.0", dt.date(2024, 2, 2))])
        self.assertEqual(e, [])

    def test_month_names(self):
        for s, d in (("January 5, 2024", dt.date(2024, 1, 5)), ("5 January 2024", dt.date(2024, 1, 5)),
                     ("Sept. 3rd, 2023", dt.date(2023, 9, 3)), ("Feb 29, 2024", dt.date(2024, 2, 29))):
            self.assertEqual(t.find_date(s)[0], d, s)

    def test_day_first_and_ambiguous(self):
        self.assertEqual(t.find_date("25/12/2023")[0], dt.date(2023, 12, 25))
        self.assertEqual(t.find_date("12/25/2023")[0], dt.date(2023, 12, 25))
        self.assertEqual(t.find_date("03/04/2024")[2], "ambiguous")
        self.assertEqual(t.find_date("03.04.2024")[0], dt.date(2024, 4, 3))
        self.assertEqual(t.find_date("03/04/2024", {"/": "mdy"})[0], dt.date(2024, 3, 4))

    def test_ambiguous_dates_are_counted_not_guessed(self):
        text = "# Changes\n\n## 1.1.0 - 03/04/2024\n\n## 1.0.0 - 05/06/2024\n"
        e, w, f, st, entries = run(text)
        self.assertEqual(e, [])
        self.assertEqual(st["unreadable"], 2)

    def test_file_hint_resolves_ambiguous(self):
        text = "# Changes\n\n## 1.2.0 - 03/04/2024\n\n## 1.1.0 - 25/03/2024\n"
        e, w, f, st, entries = run(text)
        self.assertEqual(entries[0].date, dt.date(2024, 4, 3))

    def test_date_on_the_next_line(self):
        text = "# History\n\n## 2.0.0\n\n_Released 2024-05-01_\n\n## 1.9.0\n\nReleased on April 2, 2024\n"
        e, w, f, st, entries = run(text)
        self.assertEqual([x.date for x in entries], [dt.date(2024, 5, 1), dt.date(2024, 4, 2)])

    def test_setext_and_rst(self):
        text = "Changelog\n=========\n\n1.2.0 (2024-03-01)\n------------------\n\n- x\n\n1.1.0 (2024-02-01)\n------------------\n"
        e, w, f, st, entries = run(text)
        self.assertEqual([x.raw for x in entries], ["1.2.0", "1.1.0"])

    def test_plain_news_lines(self):
        text = "1.2.0 (2024-03-01)\n  * x\n\n1.1.0 (2024-02-01)\n  * y\n"
        e, w, f, st, entries = run(text)
        self.assertEqual([x.raw for x in entries], ["1.2.0", "1.1.0"])

    def test_code_fences_and_comments_skipped(self):
        text = ("# Changelog\n\n<!--\n## [9.9.9] - 2001-01-01\n-->\n\n```\n## 8.8.8 - 2001-01-01\n```\n\n"
                "## 1.0.0 - 2024-01-01\n")
        e, w, f, st, entries = run(text)
        self.assertEqual([x.raw for x in entries], ["1.0.0"])

    def test_upgrade_sections_are_not_releases(self):
        text = "# Changelog\n\n## 2.0.0 - 2024-02-01\n\n## Upgrading from 1.9 to 2.0\n\n## 1.9.0 - 2024-01-01\n"
        e, w, f, st, entries = run(text)
        self.assertEqual([x.raw for x in entries], ["2.0.0", "1.9.0"])
        text = "# Changelog\n\n## 2.0.0 - 2024-02-01\n\n## Migrating from 1.8.4 (2023-12-01)\n\n## 1.9.0 - 2024-01-01\n"
        e, w, f, st, entries = run(text)
        self.assertEqual([x.raw for x in entries], ["2.0.0", "1.9.0"])

    def test_prerelease_order(self):
        self.assertLess(t.parse_version("2.0.0-rc.1"), t.parse_version("2.0.0"))
        self.assertLess(t.parse_version("2.0.0-rc.2"), t.parse_version("2.0.0-rc.10"))
        self.assertLess(t.parse_version("2.0.0-alpha"), t.parse_version("2.0.0-beta"))
        self.assertEqual(t.parse_version("1.2"), t.parse_version("1.2.0"))

    def test_package_prefixes_are_separate(self):
        text = ("# Changelog\n\n## pkg-a@2.0.0 - 2024-03-01\n\n## pkg-b@1.0.5 - 2024-02-01\n\n"
                "## pkg-a@1.9.0 - 2024-01-01\n\n## pkg-b@1.0.4 - 2024-02-15\n")
        e, w, f, st, entries = run(text)
        self.assertEqual({x.key for x in entries}, {"pkg-a", "pkg-b"})
        self.assertEqual(e, ["DATE"])       # pkg-b 1.0.5 dated before 1.0.4
        self.assertIn("1.0.5", [x for x in f if x.code == "DATE"][0].msg)

    def test_oldest_first_file(self):
        text = "# News\n\n## 1.0.0 - 2024-01-01\n\n## 1.1.0 - 2024-02-01\n\n## 1.2.0 - 2024-03-01\n"
        e, w, f, st, entries = run(text)
        self.assertEqual(e, [])
        text = "# News\n\n## 1.0.0 - 2024-01-01\n\n## 1.1.0 - 2023-02-01\n\n## 1.2.0 - 2024-03-01\n"
        e, w, f, st, entries = run(text)
        self.assertEqual(e, ["DATE"])


class DateRules(unittest.TestCase):
    def test_year_typo_in_january(self):
        e, w, f, st, _ = run(kac(("1.3.0", "2023-01-10"), ("1.2.5", "2023-12-20"), ("1.2.4", "2023-11-02")))
        self.assertEqual(e, ["DATE"])
        self.assertIn("2024 would put it between", f[0].msg)

    def test_year_typo_on_the_top_entry_uses_today(self):
        e, w, f, st, _ = run(kac(("1.3.0", "2023-01-10"), ("1.2.5", "2023-12-20")), as_of=dt.date(2024, 1, 20))
        self.assertEqual(e, ["DATE"])

    def test_top_entry_without_today_is_not_judged(self):
        e, w, f, st, _ = run(kac(("1.3.0", "2023-01-10"), ("1.2.5", "2023-12-20")), as_of=None)
        self.assertEqual(e + w, [])

    def test_same_line_newer_dated_before_older(self):
        e, w, f, st, _ = run(kac(("1.2.4", "2023-11-02"), ("1.2.3", "2023-11-05")))
        self.assertEqual(e, ["DATE"])
        self.assertEqual(len(f), 1)

    def test_backports_across_lines_are_not_reported(self):
        text = kac(("2.0.1", "2024-03-15"), ("2.0.0", "2024-03-01"), ("1.9.5", "2024-04-01"), ("1.9.4", "2024-02-01"))
        e, w, f, st, _ = run(text)
        self.assertEqual(e, [])
        self.assertEqual(st["not_reported"], 1)

    def test_same_day_is_fine(self):
        e, w, f, st, _ = run(kac(("1.2.1", "2024-01-05"), ("1.2.0", "2024-01-05")))
        self.assertEqual(e, [])

    def test_bad_date(self):
        e, w, f, st, _ = run(kac(("1.0.1", "2024-02-30"), ("1.0.0", "2024-01-01")))
        self.assertEqual(e, ["BADDATE"])
        e, w, f, st, _ = run(kac(("1.0.1", "2024-13-01"), ("1.0.0", "2024-01-01")))
        self.assertEqual(e, ["BADDATE"])

    def test_future(self):
        e, w, f, st, _ = run(kac(("1.0.1", "2024-02-01"), ("1.0.0", "2025-01-01")), as_of=dt.date(2024, 6, 1))
        self.assertIn("FUTURE", e)

    def test_top_entry_planned_soon_is_a_warning(self):
        e, w, f, st, _ = run(kac(("1.1.0", "2024-06-20"), ("1.0.0", "2024-05-01")), as_of=dt.date(2024, 6, 1))
        self.assertEqual(e, [])
        self.assertEqual(w, ["FUTURE?"])

    def test_top_entry_far_future_is_an_error(self):
        e, w, f, st, _ = run(kac(("1.1.0", "2025-06-20"), ("1.0.0", "2024-05-01")), as_of=dt.date(2024, 6, 1))
        self.assertEqual(e, ["FUTURE"])

    def test_two_days_of_slack(self):
        e, w, f, st, _ = run(kac(("1.0.1", "2024-06-03"), ("1.0.0", "2024-05-01")), as_of=dt.date(2024, 6, 1))
        self.assertEqual(e + w, [])

    def test_month_precision_not_compared_by_day(self):
        text = "# Changelog\n\n## 1.2.0 (March 2024)\n\n## 1.1.9 - 2024-03-20\n"
        e, w, f, st, _ = run(text)
        self.assertEqual(e, [])
        text = "# Changelog\n\n## 1.2.1 (March 2024)\n\n## 1.2.0 - 2024-03-20\n\n## 1.1.0 - 2024-01-20\n"
        e, w, f, st, _ = run(text)
        self.assertEqual(e + w, [])

    def test_sub_sub_headings_do_not_count(self):
        # "#### Fixed in 1.2.1" two levels under the release headings is prose, not an entry
        text = ("# Changelog\n\n## 1.3.0 - 2024-03-01\n\n#### Backported from 1.2.1\n\n#### 1.2.1 notes\n\n"
                "## 1.2.0 - 2024-02-01\n\n## 1.1.0 - 2024-01-01\n")
        e, w, f, st, entries = run(text)
        self.assertEqual([x.raw for x in entries], ["1.3.0", "1.2.0", "1.1.0"])

    def test_placeholder_below_a_dated_release(self):
        e, w, f, st, _ = run(kac(("1.1.0", "2024-03-01"), ("1.0.0", "YYYY-MM-DD")))
        self.assertEqual(w, ["PLACEHOLDER"])
        e, w, f, st, _ = run(kac(("1.1.0", "YYYY-MM-DD"), ("1.0.0", "2024-01-01")))
        self.assertEqual(w, [])


class VersionRules(unittest.TestCase):
    def test_duplicate_version(self):
        e, w, f, st, _ = run(kac(("1.0.1", "2024-02-01"), ("1.0.1", "2024-01-01")))
        self.assertIn("DUPVER", e)

    def test_order_in_one_line(self):
        e, w, f, st, _ = run(kac(("1.2.3", ""), ("1.2.4", ""), ("1.2.2", "")))
        self.assertEqual(e, ["ORDER"])

    def test_date_ordered_file_is_not_order(self):
        # listed by date: the 1.9.6 backport is above 2.0.0, which is fine
        e, w, f, st, _ = run(kac(("1.9.6", "2024-04-01"), ("2.0.0", "2024-03-01"), ("1.9.5", "2024-02-01")))
        self.assertEqual(e, [])


class LinkRules(unittest.TestCase):
    LINKS = ("[Unreleased]: https://github.com/o/r/compare/v1.2.0...HEAD\n"
             "[1.2.0]: https://github.com/o/r/compare/v1.1.0...v1.2.0\n"
             "[1.1.0]: https://github.com/o/r/compare/v1.0.0...v1.1.0\n"
             "[1.0.0]: https://github.com/o/r/releases/tag/v1.0.0\n")
    E = (("1.2.0", "2024-03-01"), ("1.1.0", "2024-02-01"), ("1.0.0", "2024-01-01"))

    def test_clean(self):
        e, w, f, st, _ = run(kac(*self.E, links=self.LINKS))
        self.assertEqual(e + w, [])

    def test_head_side_wrong(self):
        links = self.LINKS.replace("v1.1.0...v1.2.0", "v1.1.0...v1.1.1")
        e, w, f, st, _ = run(kac(*self.E, links=links))
        self.assertEqual(e, ["LINK"])
        self.assertIn("compares up to v1.1.1", f[0].msg)

    def test_base_not_older(self):
        links = self.LINKS.replace("v1.1.0...v1.2.0", "v1.2.1...v1.2.0")
        e, w, f, st, _ = run(kac(*self.E, links=links))
        self.assertEqual(e, ["LINK"])
        self.assertIn("not older", f[0].msg)

    def test_base_side_wrong(self):
        links = self.LINKS.replace("v1.1.0...v1.2.0", "v1.0.0...v1.2.0")
        e, w, f, st, _ = run(kac(*self.E, links=links))
        self.assertEqual(e, ["LINK"])

    def test_stale_unreleased(self):
        links = self.LINKS.replace("v1.2.0...HEAD", "v1.1.0...HEAD")
        e, w, f, st, _ = run(kac(*self.E, links=links))
        self.assertEqual(e, ["LINK"])
        self.assertIn("newest release is 1.2.0", f[0].msg)

    def test_tag_link_wrong(self):
        links = self.LINKS.replace("releases/tag/v1.0.0", "releases/tag/v0.9.0")
        e, w, f, st, _ = run(kac(*self.E, links=links))
        self.assertEqual(e, ["LINK"])

    def test_missing_definition(self):
        links = "\n".join(l for l in self.LINKS.splitlines() if not l.startswith("[1.1.0]")) + "\n"
        e, w, f, st, _ = run(kac(*self.E, links=links))
        self.assertEqual(w, ["LINKDEF"])

    def test_no_definitions_at_all_is_plain_text(self):
        e, w, f, st, _ = run(kac(*self.E))
        self.assertEqual(e + w, [])

    def test_duplicate_definition(self):
        links = self.LINKS + "[1.1.0]: https://github.com/o/r/compare/v0.1...v0.2\n"
        e, w, f, st, _ = run(kac(*self.E, links=links))
        self.assertIn("DUPLINK", w)

    def test_compare_from_last_final_skipping_prereleases(self):
        text = kac(("2.0.0", "2024-03-01"), ("2.0.0-rc.1", "2024-02-20"), ("1.9.0", "2024-01-01"),
                   links="[2.0.0]: https://github.com/o/r/compare/v1.9.0...v2.0.0\n"
                         "[2.0.0-rc.1]: https://github.com/o/r/compare/v1.9.0...v2.0.0-rc.1\n"
                         "[1.9.0]: https://github.com/o/r/releases/tag/v1.9.0\n")
        e, w, f, st, _ = run(text)
        self.assertEqual(e, [])

    def test_inline_heading_link(self):
        text = ("# Changelog\n\n## [1.3.0](https://github.com/o/r/compare/v1.2.0...v1.2.9) (2024-03-02)\n\n"
                "## [1.2.0](https://github.com/o/r/compare/v1.1.0...v1.2.0) (2024-02-02)\n")
        e, w, f, st, _ = run(text)
        self.assertEqual(e, ["LINK"])

    def test_package_tag_names(self):
        text = kac(("1.2.0", "2024-03-01"), ("1.1.0", "2024-02-01"),
                   links="[1.2.0]: https://github.com/o/r/compare/pkg@1.1.0...pkg@1.2.0\n"
                         "[1.1.0]: https://github.com/o/r/releases/tag/pkg%401.1.0\n")
        e, w, f, st, _ = run(text)
        self.assertEqual(e, [])


class WhatIsNotARelease(unittest.TestCase):
    """Each of these was a false finding on a real changelog, found while tuning."""

    def test_security_rereleases_are_not_duplicates_or_neighbours(self):
        # grafana: 13.0.1+security-01 and 13.0.1; 11.2.1+security-01 dated after 11.2.2
        text = ("# Changelog\n\n# 11.2.2 (2024-10-01)\n\n# 11.2.1+security-01 (2024-10-17)\n\n"
                "# 11.2.1 (2024-09-26)\n\n# 11.2.0 (2024-08-27)\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2024, 12, 1))
        self.assertEqual(e + w, [])
        self.assertEqual(len(entries), 4)

    def test_enterprise_edition_is_not_a_duplicate(self):
        # consul: "## 2.0.2 (July 8, 2026)" and "## 2.0.2 Enterprise (July 7, 2026)"
        text = "## 2.0.2 (July 8, 2026)\n\n## 2.0.2 Enterprise (July 7, 2026)\n\n## 2.0.1 (June 2, 2026)\n"
        e, w, f, st, entries = run(text, as_of=dt.date(2026, 9, 1))
        self.assertEqual(e, [])

    def test_prerelease_written_with_a_space(self):
        # gson: "## Version 1.3" and "## Version 1.3 beta3"; PHPMailer "2.0.0 rc2" / "rc1"
        text = ("# Change Log\n\n## Version 1.3\n\n_2009-04-01_\n\n## Version 1.3 beta3\n\n_2009-03-17_\n\n"
                "## Version 2.0.0 rc2 (Fri, Nov 16 2007)\n\n## Version 2.0.0 rc1 (Thu, Nov 08 2007)\n")
        e, w, f, st, entries = run(text)
        self.assertNotIn("DUPVER", e)
        self.assertEqual(entries[1].raw, "1.3-beta.3")
        self.assertEqual(entries[0].date, dt.date(2009, 4, 1))      # the line that is only a date

    def test_subheading_repeating_the_version(self):
        # pydantic: "## v1.9.0 (2021-12-31)" then "### v1.9.0 (2021-12-31) Changes"
        text = "## v1.9.0 (2021-12-31)\n\nthanks\n\n### v1.9.0 (2021-12-31) Changes\n\n* x\n\n## v1.8.2 (2021-05-11)\n"
        e, w, f, st, entries = run(text)
        self.assertEqual(e, [])
        self.assertEqual(len(entries), 2)

    def test_two_part_heading_over_its_line(self):
        # jupyterlab: "## 4.4" (the line's section) above "## 4.4.1" ... "## 4.4.0"
        text = "# Changelog\n\n## 4.4\n\nhighlights\n\n## 4.4.1\n\n## 4.4.0\n\n## 4.3\n\n## 4.3.0\n"
        e, w, f, st, entries = run(text)
        self.assertEqual(e, [])
        self.assertEqual([x.raw for x in entries], ["4.4.1", "4.4.0", "4.3.0"])

    def test_date_written_like_a_version(self):
        # node's old ChangeLog: "## 2013.08.21, Version 0.11.7 (Unstable)"
        text = ("## 2013.08.21, Version 0.11.7 (Unstable)\n\n## 2013.08.21, Version 0.11.6 (Unstable)\n\n"
                "## 2013.08.06, Version 0.11.5 (Unstable)\n")
        e, w, f, st, entries = run(text)
        self.assertEqual([(x.raw, x.date) for x in entries][0], ("0.11.7", dt.date(2013, 8, 21)))
        self.assertEqual(e, [])

    def test_prereleases_are_not_ordered_against_finals(self):
        # gradio (by date): "## 3.45.0-beta.12" listed above "## 3.45.2"; fzf "0.17.0-2" above "0.17.0"
        text = "# Changelog\n\n## 3.45.0-beta.12\n\n## 3.45.2\n\n## 3.45.1\n"
        e, w, f, st, entries = run(text)
        self.assertEqual(e, [])

    def test_backport_listed_by_version_is_a_warning(self):
        # sinatra: 4.0.1 (2025-05-24) listed below 4.1.0 (2024-11-18); rubygems has 4.0.1 on 2025-05-23
        text = ("## 4.2.0 / 2025-10-08\n\n## 4.1.0 / 2024-11-18\n\n## 4.0.1 / 2025-05-24\n\n"
                "## 4.0.0 / 2024-01-19\n\n## 3.2.0 / 2023-12-29\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2025, 12, 1))
        self.assertEqual(e, [])
        self.assertEqual(w, ["DATE?"])

    def test_backport_below_a_newer_line_is_not_reported(self):
        # grafana: 11.6.0 (2025-03-25) above 11.5.10 (2025-10-21), and 11.6.1 above it is 2025-04-23
        text = "# 11.6.1 (2025-04-23)\n\n# 11.6.0 (2025-03-25)\n\n# 11.5.10 (2025-10-21)\n\n# 11.5.9 (2025-09-23)\n"
        e, w, f, st, entries = run(text, as_of=dt.date(2025, 12, 1))
        self.assertEqual(e + w, [])

    def test_link_from_the_branch_point(self):
        # composer: [2.10.0-RC1] compares from 2.9.5; 2.9.6..2.9.8 came out after the RC
        text = kac(("2.10.0-RC1", "2026-04-01"), ("2.9.8", "2026-05-13"), ("2.9.6", "2026-04-14"),
                   ("2.9.5", "2026-01-29"),
                   links="[2.10.0-RC1]: https://github.com/composer/composer/compare/2.9.5...2.10.0-RC1\n"
                         "[2.9.8]: https://github.com/composer/composer/compare/2.9.6...2.9.8\n"
                         "[2.9.6]: https://github.com/composer/composer/compare/2.9.5...2.9.6\n"
                         "[2.9.5]: https://github.com/composer/composer/compare/2.9.4...2.9.5\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2026, 9, 1))
        self.assertEqual(e, [])

    def test_link_skipping_a_release_that_came_out_first(self):
        # textual: [7.0.0] compares from v6.11.0; PyPI has 6.12.0 on 2026-01-02, 7.0.0 on 2026-01-03
        text = kac(("7.0.0", "2026-01-03"), ("6.12.0", "2026-01-02"), ("6.11.0", "2025-12-18"),
                   links="[7.0.0]: https://github.com/Textualize/textual/compare/v6.11.0...v7.0.0\n"
                         "[6.12.0]: https://github.com/Textualize/textual/compare/v6.11.0...v6.12.0\n"
                         "[6.11.0]: https://github.com/Textualize/textual/compare/v6.10.0...v6.11.0\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2026, 9, 1))
        self.assertEqual(e, ["LINK"])
        self.assertIn("6.12.0", f[0].msg)

    def test_link_from_a_later_line_after_a_backport(self):
        # yargs: [18.1.0] compares from v18.0.0; 17.7.3 (a backport) is the entry below it
        text = ("## [18.1.0](https://github.com/yargs/yargs/compare/v18.0.0...v18.1.0) (2026-07-26)\n\n"
                "## [17.7.3](https://github.com/yargs/yargs/compare/v17.7.2...v17.7.3) (2026-06-19)\n\n"
                "## [18.0.0](https://github.com/yargs/yargs/compare/v17.7.2...v18.0.0) (2025-05-26)\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2026, 9, 1))
        self.assertEqual(e, [])

    def test_prerelease_links_from_the_last_stable(self):
        # vue: "## [3.5.0-beta.1](.../compare/v3.4.37...v3.5.0-beta.1)" with 3.5.0-alpha.5 before it
        text = ("## [3.5.0-beta.1](https://github.com/vuejs/core/compare/v3.4.37...v3.5.0-beta.1) (2024-08-08)\n\n"
                "## [3.5.0-alpha.5](https://github.com/vuejs/core/compare/v3.4.35...v3.5.0-alpha.5) (2024-07-31)\n\n"
                "## [3.4.37](https://github.com/vuejs/core/compare/v3.4.36...v3.4.37) (2024-08-08)\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2024, 9, 1))
        self.assertEqual(e, [])

    def test_prerelease_numbers_sort_as_numbers(self):
        # composer: 1.0.0-alpha10 and 1.0.0-alpha11 come after 1.0.0-alpha9
        self.assertLess(t.parse_version("1.0.0-alpha9"), t.parse_version("1.0.0-alpha10"))
        text = kac(("1.0.0-alpha10", "2015-04-14"), ("1.0.0-alpha9", "2014-12-07"),
                   links="[1.0.0-alpha10]: https://github.com/composer/composer/compare/1.0.0-alpha9...1.0.0-alpha10\n"
                         "[1.0.0-alpha9]: https://github.com/composer/composer/compare/1.0.0-alpha8...1.0.0-alpha9\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2016, 1, 1))
        self.assertEqual(e, [])

    def test_link_compare_reversed(self):
        # commander: [15.0.0]: .../compare/v15.0.0...v14.0.3
        text = kac(("15.0.0", "2026-01-01"), ("14.0.3", "2025-12-01"),
                   links="[15.0.0]: https://github.com/tj/commander.js/compare/v15.0.0...v14.0.3\n"
                         "[14.0.3]: https://github.com/tj/commander.js/compare/v14.0.2...v14.0.3\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2026, 9, 1))
        self.assertEqual(e, ["LINK"])

    def test_unreleased_link_ignores_a_tbd_entry(self):
        # clap: "## 5.0.0 - TBD" above "## [4.6.7] - 2026-09-14", [Unreleased] compares from v4.6.7
        text = ("# Changelog\n\n## 5.0.0 - TBD\n\n## [4.6.7] - 2026-09-14\n\n## [4.6.6] - 2026-08-06\n\n"
                "[Unreleased]: https://github.com/clap-rs/clap/compare/v4.6.7...HEAD\n"
                "[4.6.7]: https://github.com/clap-rs/clap/compare/v4.6.6...v4.6.7\n"
                "[4.6.6]: https://github.com/clap-rs/clap/compare/v4.6.5...v4.6.6\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2026, 9, 20))
        self.assertEqual(e, [])

    def test_plain_bracket_style_without_version_links(self):
        # rack: every "## [3.2.4] - date" is plain text; the only definitions are for other labels
        text = kac(("3.2.4", "2025-01-01"), ("3.2.3", "2024-12-01"), links="[#123]: https://github.com/o/r/pull/123\n")
        e, w, f, st, entries = run(text, as_of=dt.date(2025, 6, 1))
        self.assertEqual(e + w, [])

    def test_duplicate_author_link_is_not_ours(self):
        # highlight.js: "[eisenwave]:" defined twice
        text = kac(("1.1.0", "2024-02-01"), links="[eisenwave]: https://github.com/a\n[eisenwave]: https://github.com/b\n")
        e, w, f, st, entries = run(text)
        self.assertEqual(e + w, [])


class Cli(unittest.TestCase):
    def setUp(self):
        self.d = tempfile.mkdtemp()

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def main(self, *args):
        buf = io.StringIO()
        with redirect_stdout(buf):
            code = t.main(list(args))
        return code, buf.getvalue()

    def write(self, rel, text):
        p = os.path.join(self.d, rel)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as fh:
            fh.write(text)

    def test_nothing_found_exits_2(self):
        self.write("README.md", "# hi\n")
        code, out = self.main(self.d)
        self.assertEqual(code, 2)
        self.assertIn("no changelog", out)

    def test_clean_exits_0(self):
        self.write("CHANGELOG.md", kac(("1.0.1", "2024-02-01"), ("1.0.0", "2024-01-01")))
        code, out = self.main(self.d, "--as-of", "2024-06-01")
        self.assertEqual(code, 0)
        self.assertIn("1 changelogs, 2 release entries read (2 dated, 0 undated); 0 errors", out)

    def test_error_exits_1_and_names_the_file(self):
        self.write("packages/a/CHANGELOG.md", kac(("1.0.1", "2023-01-01"), ("1.0.0", "2024-01-01")))
        code, out = self.main(self.d, "--as-of", "2024-06-01")
        self.assertEqual(code, 1)
        self.assertIn("packages/a/CHANGELOG.md:", out)

    def test_node_modules_skipped(self):
        self.write("node_modules/x/CHANGELOG.md", kac(("1.0.1", "2023-01-01"), ("1.0.0", "2024-01-01")))
        code, out = self.main(self.d)
        self.assertEqual(code, 2)

    def test_warning_fails_only_with_strict(self):
        self.write("CHANGELOG.md", kac(("1.1.0", "2024-06-20"), ("1.0.0", "2024-05-01")))
        self.assertEqual(self.main(self.d, "--as-of", "2024-06-01")[0], 0)
        self.assertEqual(self.main(self.d, "--as-of", "2024-06-01", "--strict")[0], 1)


if __name__ == "__main__":
    unittest.main()

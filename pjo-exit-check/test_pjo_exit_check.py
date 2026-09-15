#!/usr/bin/env python3
# -*- coding: utf-8 -*-
"""Checks for pjo_exit_check.py. Standard library only.

    python test_pjo_exit_check.py

Every check below was first run against a deliberately broken version of the
thing it checks, and seen to fail, before it was kept.
"""
import datetime
import io
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import pjo_exit_check as P  # noqa: E402

UTC = datetime.timezone.utc


def write(path, text=""):
    with open(path, "w", encoding="utf-8") as f:
        f.write(text)


def full_export(root, projects=("Project1", "Site Rollout")):
    """Build a directory holding every documented file, using the Step 5 spellings."""
    for name in P.PROJECT_LIST_FILES:
        rows = "".join("<Project><SiteId>s</SiteId><Proj_UID>u</Proj_UID>"
                       "<Proj_Name>%s</Proj_Name></Project>" % p for p in projects)
        write(os.path.join(root, name), "<Projects>%s</Projects>" % rows)
    for proj in projects:
        for _label, suffixes in P.PER_PROJECT:
            # suffixes[0] is the Step 5 spelling; add .json where the doc omits it
            suffix = suffixes[0]
            if "." not in suffix:
                suffix += ".json"
            write(os.path.join(root, proj + suffix), "x")
    for canon, _accepted, _paged in P.FEATURE_FILES:
        write(os.path.join(root, canon + ".json"), "[]")
    return root


class TmpCase(unittest.TestCase):
    def setUp(self):
        self.dir = tempfile.mkdtemp(prefix="pjo_test_")

    def tearDown(self):
        shutil.rmtree(self.dir, ignore_errors=True)


class TestDeadline(TmpCase):
    def test_pacific_offset_is_applied(self):
        # 8:00 AM Pacific on 2026-09-30 is 15:00 UTC (PDT, UTC-7). If this reads
        # 08:00 UTC, every countdown in the tool is 7 hours generous.
        self.assertEqual(P.RETIREMENT_UTC,
                         datetime.datetime(2026, 9, 30, 15, 0, tzinfo=UTC))

    def test_days_left(self):
        _d, days, hours = P.time_left(datetime.datetime(2026, 9, 15, 15, 0, tzinfo=UTC))
        self.assertEqual(days, 15)
        self.assertAlmostEqual(hours, 360.0, places=3)

    def test_partial_day_rounds_down(self):
        # 23 hours before the cutoff is 0 days left, not 1.
        _d, days, _h = P.time_left(datetime.datetime(2026, 9, 29, 16, 0, tzinfo=UTC))
        self.assertEqual(days, 0)

    def test_after_the_date_is_negative_and_exit_1(self):
        delta, _days, _h = P.time_left(datetime.datetime(2026, 10, 1, 0, 0, tzinfo=UTC))
        self.assertLess(delta.total_seconds(), 0)
        with redirect_stdout(io.StringIO()) as out:
            code = P.main(["deadline", "--now", "2026-10-01"])
        self.assertEqual(code, 1)
        self.assertIn("PASSED", out.getvalue())

    def test_deadline_prints_the_time_of_day_warning(self):
        with redirect_stdout(io.StringIO()) as out:
            P.main(["deadline", "--now", "2026-09-15"])
        self.assertIn("08:00 Pacific, not midnight local", out.getvalue())


class TestProjectList(TmpCase):
    def test_elements(self):
        p = os.path.join(self.dir, "DraftProjectList.xml")
        write(p, "<r><P><Proj_Name>Alpha</Proj_Name></P><P><Proj_Name>Beta</Proj_Name></P></r>")
        names, err = P.project_names_from_list(p)
        self.assertIsNone(err)
        self.assertEqual(names, ["Alpha", "Beta"])

    def test_attributes_and_namespaces(self):
        # The nesting is not documented, so both shapes have to work.
        p = os.path.join(self.dir, "l.xml")
        write(p, '<r xmlns="urn:x"><P Proj_Name="Gamma"/><P Proj_Name="Gamma"/></r>')
        names, err = P.project_names_from_list(p)
        self.assertIsNone(err)
        self.assertEqual(names, ["Gamma"])  # de-duplicated

    def test_no_proj_name_is_not_an_error(self):
        p = os.path.join(self.dir, "l.xml")
        write(p, "<r><P><Other>x</Other></P></r>")
        names, err = P.project_names_from_list(p)
        self.assertIsNone(err)
        self.assertEqual(names, [])

    def test_malformed_xml_reports_an_error(self):
        p = os.path.join(self.dir, "l.xml")
        write(p, "<r><P>")
        names, err = P.project_names_from_list(p)
        self.assertIsNotNone(err)
        self.assertEqual(names, [])


class TestCheck(TmpCase):
    def test_complete_export_has_nothing_missing(self):
        full_export(self.dir)
        res = P.check_dir(self.dir)
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["empty"], [])
        self.assertEqual(res["unaccounted"], [])
        self.assertEqual(len(res["projects"]), 2)
        # 3 lists + 27 feature files + 15 per project x 2 projects
        self.assertEqual(res["expected"], 3 + 27 + 15 * 2)
        self.assertEqual(res["found"], res["expected"])

    def test_one_deleted_file_is_one_missing(self):
        full_export(self.dir)
        os.remove(os.path.join(self.dir, "Project1_published.mpp"))
        res = P.check_dir(self.dir)
        self.assertEqual(len(res["missing"]), 1)
        self.assertIn("Project1 : published .mpp", res["missing"][0])

    def test_missing_project_list_is_reported(self):
        full_export(self.dir)
        os.remove(os.path.join(self.dir, "ReportingProjectList.xml"))
        res = P.check_dir(self.dir)
        self.assertIn("ReportingProjectList.xml", res["missing"])

    def test_zero_byte_project_file_is_flagged(self):
        full_export(self.dir)
        write(os.path.join(self.dir, "Project1_draft.xml"), "")
        res = P.check_dir(self.dir)
        self.assertEqual(res["missing"], [])
        self.assertEqual(len(res["empty"]), 1)
        self.assertIn("Project1_draft.xml", res["empty"][0])

    def test_zero_byte_feature_file_is_a_note_not_a_failure(self):
        # The docs say an empty feature file is what you get when the user has no
        # data for that feature. Reporting it as a failure would bury the real ones.
        full_export(self.dir)
        write(os.path.join(self.dir, "Workflow.json"), "")
        res = P.check_dir(self.dir)
        self.assertEqual(res["empty"], [])
        self.assertTrue(any("Workflow is empty" in n for n in res["notes"]))

    def test_options_table_spellings_are_accepted(self):
        # Same export written the way the -Options table spells it: a literal
        # `Project_` prefix, no .json on the reporting files, and "Baselines"
        # instead of "ProjectBaseline".
        write(os.path.join(self.dir, "DraftProjectList.xml"),
              "<r><P><Proj_Name>P1</Proj_Name></P></r>")
        write(os.path.join(self.dir, "PublishedProjectList.xml"), "<r/>")
        write(os.path.join(self.dir, "ReportingProjectList.xml"), "<r/>")
        for suffix in ("_draft.xml", "_published.xml", "_draft.mpp", "_published.mpp",
                       "_draft.json", "_published.json", "_reporting.json",
                       "_reporting_Tasks", "_reporting_Assignments", "_reporting_Resources",
                       "_reporting_Baselines", "_reporting_TaskTimephased",
                       "_reporting_AssignmentTimephased", "_reporting_TaskBaselineTimephased",
                       "_reporting_AssignmentBaselineTimephased"):
            write(os.path.join(self.dir, "Project_P1" + suffix), "x")
        for canon, _a, _p in P.FEATURE_FILES:
            write(os.path.join(self.dir, canon + ".json"), "[]")
        res = P.check_dir(self.dir)
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["unaccounted"], [])

    def test_feature_aliases_and_paging(self):
        full_export(self.dir, projects=())
        for name in ("BusinessDrivers.json", "PortfolioAnalysis.json", "Timesheets.json",
                     "TaskStatus_AssignmentsHistory.json"):
            os.remove(os.path.join(self.dir, name))
        write(os.path.join(self.dir, "Drivers.json"), "[]")                 # prose spelling
        write(os.path.join(self.dir, "PortfolioAnalyses.json"), "[]")       # -Options spelling
        write(os.path.join(self.dir, "Timesheets_page1.json"), "[]")        # split across pages
        write(os.path.join(self.dir, "Timesheets_page2.json"), "[]")
        write(os.path.join(self.dir, "TaskStatus_AssignmentHistory.json"), "[]")  # doc drops "s"
        res = P.check_dir(self.dir)
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["unaccounted"], [])

    def test_similar_feature_names_are_not_confused(self):
        # Resource / ResourcePlans / ReportingResource / ReportingResourcePlans all
        # share a prefix. A prefix match would tick the wrong boxes.
        full_export(self.dir, projects=())
        os.remove(os.path.join(self.dir, "Resource.json"))
        res = P.check_dir(self.dir)
        self.assertEqual(res["missing"], ["Resource.json  (feature file)"])

    def test_undocumented_extra_file_is_listed_not_counted(self):
        full_export(self.dir, projects=("Project1",))
        write(os.path.join(self.dir, "ExportLog.txt"), "x")
        res = P.check_dir(self.dir)
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["unaccounted"], ["ExportLog.txt"])

    def test_optional_file_from_the_options_table_is_absorbed(self):
        full_export(self.dir, projects=())
        write(os.path.join(self.dir, "ReportingResourcePlans.json"), "[]")
        res = P.check_dir(self.dir)
        self.assertEqual(res["missing"], [])
        self.assertEqual(res["unaccounted"], [])

    def test_names_are_inferred_when_the_lists_are_gone(self):
        full_export(self.dir, projects=("Project1",))
        for name in P.PROJECT_LIST_FILES:
            os.remove(os.path.join(self.dir, name))
        res = P.check_dir(self.dir)
        self.assertEqual([p["name"] for p in res["projects"]], ["Project1"])
        self.assertEqual(sorted(res["missing"]), sorted(P.PROJECT_LIST_FILES))
        self.assertTrue(any("inferred" in n for n in res["notes"]))

    def test_unmappable_project_name_is_called_not_confirmed(self):
        write(os.path.join(self.dir, "DraftProjectList.xml"),
              "<r><P><Proj_Name>A/B: rollout</Proj_Name></P></r>")
        res = P.check_dir(self.dir)
        note = res["projects"][0].get("note", "")
        self.assertIn("NOT CONFIRMED", note)

    def test_missing_directory_is_reported_not_crashed(self):
        res = P.check_dir(os.path.join(self.dir, "nope"))
        self.assertIn("not a directory", res["notes"])
        self.assertEqual(res["missing"], ["(the whole directory)"])

    def test_the_directory_is_not_modified(self):
        full_export(self.dir, projects=("Project1",))
        before = sorted(os.listdir(self.dir))
        P.check_dir(self.dir)
        self.assertEqual(before, sorted(os.listdir(self.dir)))


class TestExitCodes(TmpCase):
    def test_check_exits_0_when_complete(self):
        full_export(self.dir, projects=("Project1",))
        with redirect_stdout(io.StringIO()):
            self.assertEqual(P.main(["check", self.dir, "--now", "2026-09-15"]), 0)

    def test_check_exits_1_when_something_is_missing(self):
        full_export(self.dir, projects=("Project1",))
        os.remove(os.path.join(self.dir, "Security.json"))
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(P.main(["check", self.dir, "--now", "2026-09-15"]), 1)
        self.assertIn("Security.json", out.getvalue())
        self.assertIn("15 days left", out.getvalue())

    def test_checklist_names_what_no_file_check_can_see(self):
        with redirect_stdout(io.StringIO()) as out:
            self.assertEqual(P.main(["checklist", "--now", "2026-09-15"]), 0)
        text = out.getvalue()
        self.assertIn("Project Home", text)
        self.assertIn("macros", text)
        self.assertIn("not supported", text)

    def test_json_output_parses(self):
        import json
        full_export(self.dir, projects=("Project1",))
        with redirect_stdout(io.StringIO()) as out:
            P.main(["check", self.dir, "--json"])
        data = json.loads(out.getvalue())
        self.assertEqual(len(data), 1)
        self.assertEqual(data[0]["missing"], [])


if __name__ == "__main__":
    unittest.main(verbosity=2)

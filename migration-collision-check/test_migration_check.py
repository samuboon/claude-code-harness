# -*- coding: utf-8 -*-
"""Tests for migration_check.py (python -m unittest test_migration_check)."""
import os
import shutil
import subprocess
import sys
import tempfile
import unittest

import migration_check as t

NEW_PY = sys.version_info >= (3, 14)      # parses `except A, B:` itself; no text fallback needed


def tree(files, origin=None):
    return t.Tree(list(files), lambda p: files.get(p), origin)


def codes(files, order=False, origin=None):
    fs, st = t.check_tree(tree(files, origin), order=order)
    return sorted(f.code for f in fs), fs, st


def django(num, deps=(), replaces=(), run_before=()):
    return ("from django.db import migrations\n\n\nclass Migration(migrations.Migration):\n"
            "    dependencies = %r\n    replaces = %r\n    run_before = %r\n    operations = []\n"
            % (list(deps), list(replaces), list(run_before)))


def alembic(rev, down, labels=None, annotated=False):
    if annotated:
        return ('revision: str = %r\ndown_revision: Union[str, None] = %r\n'
                'branch_labels = %r\n' % (rev, down, labels))
    return 'revision = %r\ndown_revision = %r\nbranch_labels = %r\n' % (rev, down, labels)


class FlywayTests(unittest.TestCase):
    D = "src/main/resources/db/migration/"

    def test_duplicate_version(self):
        c, fs, _ = codes({self.D + "V1__init.sql": "", self.D + "V2__a.sql": "", self.D + "V2__b.sql": ""})
        self.assertEqual(c, ["DUP"])
        self.assertIn("V2__a.sql", fs[0].path + fs[0].msg)
        self.assertIn("V2__b.sql", fs[0].path + fs[0].msg)

    def test_flyway_reads_versions_as_numbers(self):
        self.assertEqual(codes({self.D + "V1_1__a.sql": "", self.D + "V1.1__b.sql": ""})[0], ["DUP"])
        self.assertEqual(codes({self.D + "V1.01__a.sql": "", self.D + "V1.1__b.sql": ""})[0], ["DUP"])
        self.assertEqual(codes({self.D + "V2.0__a.sql": "", self.D + "V2__b.sql": ""})[0], ["DUP"])
        self.assertEqual(codes({self.D + "V1.1__a.sql": "", self.D + "V1.10__b.sql": ""})[0], [])
        self.assertEqual(codes({self.D + "V010__a.sql": "", self.D + "V10__b.sql": ""})[0], ["DUP"])

    def test_distinct_versions_pass(self):
        self.assertEqual(codes({self.D + "V1__a.sql": "", self.D + "V2__b.sql": "",
                                self.D + "U2__undo.sql": "", self.D + "R__view.sql": ""})[0], [])

    def test_java_class_and_sql_share_the_location(self):
        c, _, _ = codes({self.D + "V3__a.sql": "", "src/main/java/db/migration/V3__Backfill.java": ""})
        self.assertEqual(c, ["DUP"])

    def test_java_class_off_a_source_path_is_not_a_migration(self):
        self.assertEqual(codes({"db/migration/V3__a.sql": "", "db/migration/V3__Notes.java": ""})[0], [])

    def test_modules_and_test_resources_are_apart(self):
        c, _, st = codes({"a/" + self.D + "V1__x.sql": "", "b/" + self.D + "V1__x.sql": "",
                          "src/test/resources/db/migration/V1__x.sql": "", self.D + "V1__x.sql": ""})
        self.assertEqual(c, [])
        self.assertEqual(st["sets"]["flyway"], 4)

    def test_vendor_folders_are_apart(self):
        c, _, _ = codes({"db/migration/mysql/V1__x.sql": "", "db/migration/postgresql/V1__x.sql": ""})
        self.assertEqual(c, [])

    def test_sibling_folders_under_one_root_warn(self):
        c, _, _ = codes({"db/migration/2025/V7__x.sql": "", "db/migration/2026/V7__y.sql": ""})
        self.assertEqual(c, ["DUP?"])

    def test_sibling_folders_warn_once_per_root(self):
        f = {}
        for v in range(1, 13):
            f["db/migration/control/V%03d__c.sql" % v] = ""
            f["db/migration/tenant/V%03d__t.sql" % v] = ""
        f["db/migration/tenant/V013__only_here.sql"] = ""
        c, fs, _ = codes(f)
        self.assertEqual(c, ["DUP?"])
        self.assertIn("12 Flyway version(s) (1, 2, 3, 4, 5, ...)", fs[0].msg)
        self.assertIn("control/, tenant/", fs[0].msg)
        self.assertNotIn("db/migration/tenant/V013__only_here.sql", fs[0].involved)

    def test_order_across_a_merge(self):
        files = {self.D + "V1__a.sql": "", self.D + "V6__main.sql": "", self.D + "V5__mine.sql": ""}
        origin = {self.D + "V1__a.sql": "shared", self.D + "V6__main.sql": "base",
                  self.D + "V5__mine.sql": "branch"}
        c, fs, _ = codes(files, order=True, origin=origin)
        self.assertEqual(c, ["ORDER"])
        self.assertTrue(fs[0].path.endswith("V5__mine.sql"))
        self.assertIn("V6__main.sql", fs[0].msg)

    def test_order_is_not_checked_without_base(self):
        files = {self.D + "V6__main.sql": "", self.D + "V5__mine.sql": ""}
        self.assertEqual(codes(files)[0], [])

    def test_order_higher_version_passes(self):
        files = {self.D + "V6__main.sql": "", self.D + "V7__mine.sql": ""}
        origin = {self.D + "V6__main.sql": "base", self.D + "V7__mine.sql": "branch"}
        self.assertEqual(codes(files, order=True, origin=origin)[0], [])

    def test_out_of_order_setting_turns_order_off(self):
        files = {self.D + "V6__main.sql": "", self.D + "V5__mine.sql": "",
                 "src/main/resources/application.yml": "spring:\n  flyway:\n    out-of-order: true\n"}
        origin = {self.D + "V6__main.sql": "base", self.D + "V5__mine.sql": "branch"}
        c, _, st = codes(files, order=True, origin=origin)
        self.assertEqual(c, [])
        self.assertEqual(st["ooo"], "src/main/resources/application.yml")

    def test_out_of_order_false_keeps_order(self):
        files = {self.D + "V6__main.sql": "", self.D + "V5__mine.sql": "",
                 "flyway.conf": "flyway.outOfOrder=false\n"}
        origin = {self.D + "V6__main.sql": "base", self.D + "V5__mine.sql": "branch"}
        self.assertEqual(codes(files, order=True, origin=origin)[0], ["ORDER"])


class GoMigrateTests(unittest.TestCase):
    def test_duplicate_up(self):
        c, fs, _ = codes({"migrations/000011_a.up.sql": "", "migrations/000011_a.down.sql": "",
                          "migrations/000011_b.up.sql": "", "migrations/000011_b.down.sql": ""})
        self.assertEqual(c, ["DUP", "DUP"])

    def test_leading_zeros_are_one_version(self):
        self.assertEqual(codes({"m/011_a.up.sql": "", "m/11_b.up.sql": ""})[0], ["DUP"])

    def test_up_and_down_of_one_version_pass(self):
        self.assertEqual(codes({"m/1_a.up.sql": "", "m/1_a.down.sql": "", "m/2_b.up.sql": ""})[0], [])

    def test_folders_are_apart(self):
        self.assertEqual(codes({"m1/1_a.up.sql": "", "m2/1_b.up.sql": ""})[0], [])

    def test_pop_dialects_are_apart(self):
        self.assertEqual(codes({"m/20190100_ids.postgres.up.sql": "", "m/20190100_ids.mysql.up.sql": "",
                                "m/20190100_ids.sqlite3.up.sql": ""})[0], [])

    def test_pop_autocommit_and_all_dialects(self):
        self.assertEqual(codes({"m/20250708_ids.autocommit.up.sql": "",
                                "m/20250708_ids.cockroach.autocommit.up.sql": "",
                                "m/20250709_x.up.sql": "", "m/20250709_x.postgres.up.sql": ""})[0], [])
        self.assertEqual(codes({"m/20250708_a.cockroach.autocommit.up.sql": "",
                                "m/20250708_b.cockroach.up.sql": ""})[0], ["DUP"])

    def test_go_module_with_golang_migrate_keeps_the_error(self):
        f = {"go.mod": "module x\n\nrequire github.com/golang-migrate/migrate/v4 v4.17.1\n",
             "m/1_a.up.sql": "", "m/1_b.up.sql": ""}
        self.assertEqual(codes(f)[0], ["DUP"])

    def test_go_module_without_golang_migrate_keeps_the_error(self):
        # the CLI needs no go.mod entry; 7 of the replayed fixes were in such repositories
        f = {"go.mod": "module x\n\nrequire github.com/lib/pq v1.10.9\n",
             "m/1_a.up.sql": "", "m/1_b.up.sql": ""}
        self.assertEqual(codes(f)[0], ["DUP"])

    def test_maragudk_migrate_warns_even_next_to_golang_migrate(self):
        f = {"go.mod": "require (\n\tgithub.com/golang-migrate/migrate/v4 v4.17.1\n"
                       "\tgithub.com/maragudk/migrate v0.4.3\n)\n",
             "m/0001_create_table_a.up.sql": "", "m/0001_create_table_b.up.sql": ""}
        c, fs, _ = codes(f)
        self.assertEqual(c, ["DUP?"])
        self.assertIn("maragudk/migrate", fs[0].msg)

    def test_order_across_a_merge(self):
        files = {"m/5_main.up.sql": "", "m/4_mine.up.sql": "", "m/4_mine.down.sql": ""}
        origin = {"m/5_main.up.sql": "base", "m/4_mine.up.sql": "branch", "m/4_mine.down.sql": "branch"}
        c, fs, _ = codes(files, order=True, origin=origin)
        self.assertEqual(c, ["ORDER"])
        self.assertIn("never applies", fs[0].msg)


class RailsTests(unittest.TestCase):
    def test_duplicate_version(self):
        c, _, _ = codes({"db/migrate/20260101000000_add_a.rb": "", "db/migrate/20260101000000_add_b.rb": ""})
        self.assertEqual(c, ["DUP"])

    def test_duplicate_name(self):
        c, _, _ = codes({"db/migrate/20260101000000_add_a.rb": "", "db/migrate/20260102000000_add_a.rb": ""})
        self.assertEqual(c, ["DUPNAME"])

    def test_subfolders_are_one_set(self):
        c, _, st = codes({"db/migrate/20260101000000_a.rb": "", "db/migrate/old/20260101000000_b.rb": ""})
        self.assertEqual(c, ["DUP"])
        self.assertEqual(st["sets"]["rails"], 1)

    def test_multi_database_folders_are_apart(self):
        c, _, st = codes({"db/migrate/20260101000000_a.rb": "", "db/animals_migrate/20260101000000_b.rb": ""})
        self.assertEqual(c, [])
        self.assertEqual(st["sets"]["rails"], 2)

    def test_engine_duplicate_version_warns(self):
        files = {"engine/engine.gemspec": "", "engine/db/migrate/20260101000000_a.rb": "",
                 "engine/db/migrate/20260101000000_b.rb": ""}
        c, fs, _ = codes(files)
        self.assertEqual(c, ["DUP?"])
        self.assertIn("engine", fs[0].msg)

    def test_engine_duplicate_name_stays_an_error(self):
        files = {"engine/engine.gemspec": "", "engine/db/migrate/20260101000000_a.rb": "",
                 "engine/db/migrate/20260102000000_a.rb": ""}
        self.assertEqual(codes(files)[0], ["DUPNAME"])

    def test_app_next_to_a_gemspec_elsewhere_is_not_an_engine(self):
        files = {"gems/x/x.gemspec": "", "db/migrate/20260101000000_a.rb": "",
                 "db/migrate/20260101000000_b.rb": ""}
        self.assertEqual(codes(files)[0], ["DUP"])

    def test_fixture_folders_are_left_out(self):
        files = {"spec/fixtures/db/migrate/a/20260101000000_x.rb": "",
                 "spec/fixtures/db/migrate/b/20260101000000_y.rb": "",
                 "source/testdata/duplicates/1_a.up.sql": "", "source/testdata/duplicates/1_b.up.sql": ""}
        c, _, st = codes(files)
        self.assertEqual(c, [])
        self.assertEqual(st["fixtures"], 4)

    def test_schema_older_than_newest_migration(self):
        files = {"db/migrate/20260101000000_a.rb": "", "db/migrate/20260301000000_b.rb": "",
                 "db/schema.rb": "ActiveRecord::Schema[7.1].define(version: 2026_01_01_000000) do\nend\n"}
        c, fs, _ = codes(files)
        self.assertEqual(c, ["SCHEMA"])
        self.assertEqual(t.LEVEL["SCHEMA"], "warning")

    def test_schema_up_to_date(self):
        files = {"db/migrate/20260101000000_a.rb": "",
                 "db/schema.rb": "ActiveRecord::Schema.define(version: 20260101000000) do\nend\n"}
        self.assertEqual(codes(files)[0], [])

    def test_schema_of_a_second_database(self):
        files = {"db/animals_migrate/20260301000000_b.rb": "",
                 "db/animals_schema.rb": "ActiveRecord::Schema[8.0].define(version: 2026_01_01_000000) do\nend\n"}
        self.assertEqual(codes(files)[0], ["SCHEMA"])


class DjangoTests(unittest.TestCase):
    M = "shop/migrations/"

    def base(self):
        return {self.M + "__init__.py": "", self.M + "0001_initial.py": django(1),
                self.M + "0002_a.py": django(2, [("shop", "0001_initial")])}

    def test_linear_passes(self):
        self.assertEqual(codes(self.base())[0], [])

    def test_two_leaves(self):
        f = self.base()
        f[self.M + "0002_b.py"] = django(2, [("shop", "0001_initial")])
        c, fs, _ = codes(f)
        self.assertEqual(c, ["CONFLICT"])
        self.assertIn("0002_a, 0002_b", fs[0].msg)

    def test_same_number_in_a_chain_passes(self):
        f = self.base()
        f[self.M + "0002_b.py"] = django(2, [("shop", "0002_a")])
        self.assertEqual(codes(f)[0], [])

    def test_merge_migration_joins_leaves(self):
        f = self.base()
        f[self.M + "0002_b.py"] = django(2, [("shop", "0001_initial")])
        f[self.M + "0003_merge.py"] = django(3, [("shop", "0002_a"), ("shop", "0002_b")])
        self.assertEqual(codes(f)[0], [])

    def test_not_a_package_is_skipped(self):
        f = self.base()
        del f[self.M + "__init__.py"]
        f[self.M + "0002_b.py"] = django(2, [("shop", "0001_initial")])
        c, _, st = codes(f)
        self.assertEqual(c, [])
        self.assertEqual(st["sets"]["django"], 0)

    def test_private_and_backup_files_are_skipped(self):
        f = self.base()
        f[self.M + "_0002_b.py"] = django(2, [("shop", "0001_initial")])
        f[self.M + "~0002_c.py"] = django(2, [("shop", "0001_initial")])
        self.assertEqual(codes(f)[0], [])

    def test_dotted_file_name_is_not_a_migration(self):
        f = self.base()
        f[self.M + "0002_a.py 18-30-32.py"] = django(2, [("shop", "0001_initial")])
        self.assertEqual(codes(f)[0], [])

    def test_missing_dependency(self):
        f = self.base()
        f[self.M + "0003_c.py"] = django(3, [("shop", "0002_gone")])
        c, _, _ = codes(f)
        self.assertIn("MISSING", c)

    def test_missing_dependency_in_another_app_of_the_repo(self):
        f = self.base()
        f["blog/migrations/__init__.py"] = ""
        f["blog/migrations/0001_initial.py"] = django(1, [("shop", "0009_nope")])
        c, fs, _ = codes(f)
        self.assertEqual(c, ["MISSING"])

    def test_third_party_dependency_is_not_checked(self):
        f = self.base()
        f[self.M + "0003_c.py"] = django(3, [("shop", "0002_a"), ("auth", "0012_alter_user")])
        self.assertEqual(codes(f)[0], [])

    def test_cross_app_dependency_is_not_an_edge(self):
        f = self.base()
        f["blog/migrations/__init__.py"] = ""
        f["blog/migrations/0001_initial.py"] = django(1, [("shop", "0001_initial")])
        self.assertEqual(codes(f)[0], [])

    def test_first_and_latest(self):
        f = self.base()
        f["blog/migrations/__init__.py"] = ""
        f["blog/migrations/0001_initial.py"] = django(1, [("shop", "__first__"), ("blog", "__first__")])
        self.assertEqual(codes(f)[0], [])

    def test_label_from_apps_py(self):
        f = {"apps/shop/migrations/__init__.py": "",
             "apps/shop/apps.py": "class ShopConfig(AppConfig):\n    name = 'apps.shop'\n    label = 'store'\n",
             "apps/shop/migrations/0001_initial.py": django(1),
             "apps/shop/migrations/0002_a.py": django(2, [("store", "0001_initial")])}
        self.assertEqual(codes(f)[0], [])

    def test_squashed_migration_stands_in(self):
        f = self.base()
        f[self.M + "0001_squashed_0002_a.py"] = django(1, [], [("shop", "0001_initial"), ("shop", "0002_a")])
        f[self.M + "0003_b.py"] = django(3, [("shop", "0002_a")])
        self.assertEqual(codes(f)[0], [])

    def test_squashed_migration_and_a_real_fork(self):
        f = self.base()
        f[self.M + "0001_squashed_0002_a.py"] = django(1, [], [("shop", "0001_initial"), ("shop", "0002_a")])
        f[self.M + "0003_b.py"] = django(3, [("shop", "0002_a")])
        f[self.M + "0003_c.py"] = django(3, [("shop", "0001_squashed_0002_a")])
        self.assertEqual(codes(f)[0], ["CONFLICT"])

    def squashed_and_deleted(self):
        """0001..0003 squashed, the replaced files deleted, later ones still name 0003."""
        return {self.M + "__init__.py": "",
                self.M + "0001_squashed_0003_c.py": django(1, [], [("shop", "0001_initial"),
                                                                    ("shop", "0002_a"), ("shop", "0003_c")]),
                self.M + "0004_d.py": django(4, [("shop", "0003_c")]),
                self.M + "0005_e.py": django(5, [("shop", "0004_d")])}

    def test_dependency_on_a_deleted_replaced_migration(self):
        self.assertEqual(codes(self.squashed_and_deleted())[0], [])

    def test_other_app_depends_on_a_deleted_replaced_migration(self):
        f = self.squashed_and_deleted()
        f["blog/migrations/__init__.py"] = ""
        f["blog/migrations/0001_initial.py"] = django(1, [("shop", "0002_a")])
        self.assertEqual(codes(f)[0], [])

    def test_squash_of_a_squash(self):
        f = {self.M + "__init__.py": "",
             self.M + "0001_squashed_0009_z.py": django(1, [], [("shop", "0001_squashed_0003_c"),
                                                                 ("shop", "0004_d")]),
             self.M + "0010_y.py": django(10, [("shop", "0001_squashed_0003_c")])}
        self.assertEqual(codes(f)[0], [])

    def test_run_before_a_deleted_replaced_migration(self):
        f = self.squashed_and_deleted()
        f[self.M + "0000_pre.py"] = django(0, [], run_before=[("shop", "0002_a")])
        self.assertEqual(codes(f)[0], [])

    PY314 = ("from django.db import migrations, settings\n\ndef f(apps, se):\n    try:\n        pass\n"
             "    except KeyError, ValueError:\n        pass\n\n\nclass Migration(migrations.Migration):\n"
             "    dependencies = [\n        migrations.swappable_dependency(settings.AUTH_USER_MODEL),\n"
             "        (\"shop\", \"%s\"),\n    ]\n    operations = [migrations.RunPython(f)]\n")

    def test_migration_class_that_is_not_djangos(self):
        f = {"jobs/migrations/__init__.py": ""}
        for i in (1, 2, 3):
            f["jobs/migrations/000%d_x.py" % i] = ("from jobs.definition import AsyncMigrationDefinition\n\n"
                                                   "class Migration(AsyncMigrationDefinition):\n"
                                                   "    depends_on = '000%d_x'\n" % (i - 1))
        c, _, st = codes(f)
        self.assertEqual(c, [])
        self.assertEqual(st["sets"]["django"], 0)
        self.assertEqual(st["unread"], 0)

    def test_custom_base_ending_in_migration(self):
        f = self.base()
        f[self.M + "0002_b.py"] = django(2, [("shop", "0001_initial")]).replace(
            "(migrations.Migration)", "(SafeMigration)")
        self.assertEqual(codes(f)[0], ["CONFLICT"])

    def test_dependencies_built_with_plus(self):
        f = self.base()
        f[self.M + "0003_c.py"] = ("from django.db import migrations\nfrom x import settings\n\n\n"
                                   "class Migration(migrations.Migration):\n"
                                   "    dependencies = [\n        (\"shop\", \"0002_a\"),\n"
                                   "    ] + settings.EXTRA_DEPENDENCIES\n    operations = []\n")
        f[self.M + "0004_d.py"] = django(4, [("shop", "0003_c")])
        self.assertEqual(codes(f)[0], [])

    def test_newer_python_syntax_read_as_text(self):
        f = self.base()
        f[self.M + "0003_c.py"] = self.PY314 % "0002_a"
        f[self.M + "0004_d.py"] = django(4, [("shop", "0003_c")])
        c, _, st = codes(f)
        self.assertEqual(c, [])
        self.assertEqual(st["by_text"], 0 if NEW_PY else 1)
        self.assertEqual(st["unread"], 0)

    def test_newer_python_syntax_fork_still_found(self):
        f = self.base()
        f[self.M + "0003_c.py"] = self.PY314 % "0002_a"
        f[self.M + "0003_d.py"] = django(3, [("shop", "0002_a")])
        self.assertEqual(codes(f)[0], ["CONFLICT"])

    def test_run_before_is_an_edge(self):
        f = self.base()
        f[self.M + "0002_b.py"] = django(2, [("shop", "0001_initial")], run_before=[("shop", "0002_a")])
        self.assertEqual(codes(f)[0], [])

    def test_file_without_migration_class_is_counted(self):
        f = self.base()
        f[self.M + "helpers.py"] = "def f():\n    pass\n"
        c, _, st = codes(f)
        self.assertEqual(c, [])
        self.assertEqual(st["unread"], 1)

    def test_conflict_brought_in_by_the_branch(self):
        f = self.base()
        f[self.M + "0003_main.py"] = django(3, [("shop", "0002_a")])
        f[self.M + "0003_mine.py"] = django(3, [("shop", "0002_a")])
        origin = {p: "shared" for p in f}
        origin[self.M + "0003_main.py"] = "base"
        origin[self.M + "0003_mine.py"] = "branch"
        tr = tree(f, origin)
        fs, _ = t.check_tree(tr, order=True)
        self.assertEqual([x.code for x in fs], ["CONFLICT"])
        self.assertTrue(t.brought_in(tr, fs[0]))
        self.assertTrue(fs[0].path.endswith("0003_mine.py"))

    def test_conflict_already_on_base_is_not_brought_in(self):
        f = self.base()
        f[self.M + "0002_b.py"] = django(2, [("shop", "0001_initial")])
        f[self.M + "0003_mine.py"] = django(3, [("shop", "0002_a")])
        origin = {p: "shared" for p in f}
        origin[self.M + "0003_mine.py"] = "base"
        tr = tree(f, origin)
        fs, _ = t.check_tree(tr, order=True)
        self.assertEqual([x.code for x in fs], ["CONFLICT"])
        self.assertFalse(t.brought_in(tr, fs[0]))


class AlembicTests(unittest.TestCase):
    V = "alembic/versions/"

    def base(self):
        return {"alembic/env.py": "", self.V + "a1_init.py": alembic("a1", None),
                self.V + "b2_users.py": alembic("b2", "a1")}

    def test_single_head_passes(self):
        self.assertEqual(codes(self.base())[0], [])

    def test_two_heads(self):
        f = self.base()
        f[self.V + "c3_x.py"] = alembic("c3", "b2")
        f[self.V + "d4_y.py"] = alembic("d4", "b2")
        c, fs, _ = codes(f)
        self.assertEqual(c, ["HEADS"])
        self.assertIn("c3", fs[0].msg)
        self.assertIn("d4", fs[0].msg)

    def test_merge_revision_joins_heads(self):
        f = self.base()
        f[self.V + "c3_x.py"] = alembic("c3", "b2")
        f[self.V + "d4_y.py"] = alembic("d4", "b2")
        f[self.V + "e5_merge.py"] = alembic("e5", ("c3", "d4"))
        self.assertEqual(codes(f)[0], [])

    def test_annotated_assignments(self):
        f = self.base()
        f[self.V + "c3_x.py"] = alembic("c3", "b2", annotated=True)
        f[self.V + "d4_y.py"] = alembic("d4", "b2", annotated=True)
        self.assertEqual(codes(f)[0], ["HEADS"])

    def test_separate_bases_are_separate_chains(self):
        f = self.base()
        f[self.V + "x1_other.py"] = alembic("x1", None, ("other",))
        self.assertEqual(codes(f)[0], [])

    def test_labelled_fork_warns(self):
        f = self.base()
        f[self.V + "c3_x.py"] = alembic("c3", "b2", ("feature",))
        f[self.V + "d4_y.py"] = alembic("d4", "b2")
        self.assertEqual(codes(f)[0], ["HEADS?"])

    def test_missing_down_revision(self):
        f = self.base()
        f[self.V + "c3_x.py"] = alembic("c3", "zz")
        c, _, _ = codes(f)
        self.assertIn("MISSING", c)

    def test_duplicate_revision(self):
        f = self.base()
        f[self.V + "b2_again.py"] = alembic("b2", "a1")
        c, _, _ = codes(f)
        self.assertEqual(c, ["DUPREV"])

    def test_two_environments_are_apart(self):
        f = self.base()
        f["other/env.py"] = ""
        f["other/versions/a1_init.py"] = alembic("a1", None)
        f["other/versions/b2_x.py"] = alembic("b2", "a1")
        c, _, st = codes(f)
        self.assertEqual(c, [])
        self.assertEqual(st["sets"]["alembic"], 2)

    def test_version_locations_under_one_script_folder(self):
        f = {"db/env.py": "", "db/script.py.mako": "",
             "db/versions/core/a1.py": alembic("a1", None),
             "db/versions/extra/b2.py": alembic("b2", "a1")}
        self.assertEqual(codes(f)[0], [])

    def test_fork_across_version_folders_of_one_environment(self):
        f = {"db/env.py": "", "db/script.py.mako": "",
             "db/versions/core/a1.py": alembic("a1", None),
             "db/versions/core/b2.py": alembic("b2", "a1"),
             "db/versions/extra/c3.py": alembic("c3", "a1")}
        c, _, st = codes(f)
        self.assertEqual(c, ["HEADS"])
        self.assertEqual(st["sets"]["alembic"], 1)

    def test_staged_copies_outside_versions_are_not_read(self):
        f = self.base()
        f["alembic/script.py.mako"] = ""
        f["alembic/_staged/b2_users.py"] = alembic("b2", "a1")
        f["alembic/_staged/c3_x.py"] = alembic("c3", "a1")
        self.assertEqual(codes(f)[0], [])

    def test_version_locations_from_alembic_ini(self):
        f = {"alembic.ini": "[alembic]\nscript_location = db\nversion_locations = %(here)s/db/chain\n",
             "db/env.py": "", "db/chain/a1.py": alembic("a1", None),
             "db/chain/b2.py": alembic("b2", "a1"), "db/chain/c3.py": alembic("c3", "a1")}
        self.assertEqual(codes(f)[0], ["HEADS"])

    def test_database_folders_are_separate_chains(self):
        f = {"m/env.py": ""}
        for db in ("postgresql", "sqlite"):
            f["m/versions/%s/a1.py" % db] = alembic("a1", None)
            f["m/versions/%s/b2.py" % db] = alembic("b2", "a1")
        f["m/versions/sqlite/c3.py"] = alembic("c3", "b2")
        f["m/versions/postgresql/d4.py"] = alembic("d4", "b2")
        c, _, st = codes(f)
        self.assertEqual(c, [])
        self.assertEqual(st["sets"]["alembic"], 2)

    def test_python_files_elsewhere_are_not_read(self):
        f = self.base()
        f["app/models.py"] = alembic("c3", "b2") + alembic("d4", "b2")
        f["app/other.py"] = alembic("d4", "b2")
        self.assertEqual(codes(f)[0], [])

    def test_newer_python_syntax_read_as_text(self):
        f = self.base()
        body = ("revision: str = 'c3'  # the id\ndown_revision: Union[str, None] = (\n    'b2',\n)\n"
                "def upgrade():\n    try:\n        pass\n    except KeyError, ValueError:\n        pass\n")
        f[self.V + "c3_x.py"] = body
        f[self.V + "d4_y.py"] = body.replace("'c3'", "'d4'")
        c, _, st = codes(f)
        self.assertEqual(c, ["HEADS"])
        self.assertEqual(st["by_text"], 0 if NEW_PY else 2)

    def test_revision_not_literal_is_counted(self):
        f = self.base()
        f[self.V + "c3_x.py"] = "revision = make_id()\ndown_revision = 'b2'\n"
        c, _, st = codes(f)
        self.assertEqual(c, [])
        self.assertEqual(st["unread"], 1)


class MergedTreeTests(unittest.TestCase):
    def test_union_without_split(self):
        tr = t.merged_tree(["a", "b"], {"a": "A", "b": "B"}.get, ["a", "c"], {"a": "A2", "c": "C"}.get)
        self.assertEqual(tr.paths, ["a", "b", "c"])
        self.assertEqual(tr.origin, {"a": "shared", "b": "base", "c": "branch"})
        self.assertEqual(tr.read("a"), "A")
        self.assertEqual(tr.read("c"), "C")

    def test_split_drops_what_the_branch_deleted(self):
        tr = t.merged_tree(["a", "old"], lambda p: p, ["a", "new"], lambda p: p, ["a", "old"])
        self.assertEqual(tr.paths, ["a", "new"])
        self.assertEqual(tr.origin["new"], "branch")

    def test_split_keeps_what_the_base_added(self):
        tr = t.merged_tree(["a", "b"], lambda p: p, ["a"], lambda p: p, ["a"])
        self.assertEqual(tr.paths, ["a", "b"])
        self.assertEqual(tr.origin["b"], "base")

    def test_file_the_branch_edited_is_read_from_the_branch(self):
        tr = t.merged_tree(["s"], {"s": "base"}.get, ["s"], {"s": "head"}.get, ["s"], ["s"])
        self.assertEqual(tr.read("s"), "head")


@unittest.skipIf(shutil.which("git") is None, "git not installed")
class GitBaseTests(unittest.TestCase):
    """--base end to end on a scratch repository."""

    def setUp(self):
        self.d = tempfile.mkdtemp()
        self.g("init", "-q", "-b", "main")
        self.g("config", "user.email", "t@example.invalid")
        self.g("config", "user.name", "t")
        self.g("config", "commit.gpgsign", "false")

    def tearDown(self):
        shutil.rmtree(self.d, ignore_errors=True)

    def g(self, *a):
        subprocess.run(["git", "-C", self.d] + list(a), check=True, capture_output=True)

    def put(self, path, text=""):
        p = os.path.join(self.d, path)
        os.makedirs(os.path.dirname(p), exist_ok=True)
        with open(p, "w", encoding="utf-8") as f:
            f.write(text)
        self.g("add", path)

    def run_main(self, *args):
        import io
        import contextlib
        out = io.StringIO()
        with contextlib.redirect_stdout(out):
            rc = t.main([self.d] + list(args))
        return rc, out.getvalue()

    def test_each_side_passes_the_merge_does_not(self):
        D = "db/migration/"
        self.put(D + "V1__init.sql")
        self.g("commit", "-q", "-m", "init")
        self.g("checkout", "-q", "-b", "feature")
        self.put(D + "V2__mine.sql")
        self.g("commit", "-q", "-m", "mine")
        self.g("checkout", "-q", "main")
        self.put(D + "V2__theirs.sql")
        self.g("commit", "-q", "-m", "theirs")
        self.g("checkout", "-q", "feature")
        rc, out = self.run_main()
        self.assertEqual(rc, 0, out)
        rc, out = self.run_main("--base", "main")
        self.assertEqual(rc, 1, out)
        self.assertIn("V2__mine.sql:1: error DUP", out)
        self.assertIn("1 files added by HEAD", out)

    def test_branch_rename_is_not_a_collision(self):
        D = "db/migration/"
        self.put(D + "V1__init.sql")
        self.put(D + "V2__mine.sql")
        self.g("commit", "-q", "-m", "init")
        self.g("checkout", "-q", "-b", "feature")
        self.g("mv", D + "V2__mine.sql", D + "V3__mine.sql")
        self.g("commit", "-q", "-m", "renumber")
        rc, out = self.run_main("--base", "main")
        self.assertEqual(rc, 0, out)

    def test_already_broken_base_is_not_blamed_on_the_branch(self):
        D = "db/migration/"
        self.put(D + "V1__a.sql")
        self.put(D + "V1__b.sql")
        self.g("commit", "-q", "-m", "broken")
        self.g("checkout", "-q", "-b", "feature")
        self.put(D + "V2__c.sql")
        self.g("commit", "-q", "-m", "c")
        rc, out = self.run_main("--base", "main")
        self.assertEqual(rc, 0, out)
        self.assertIn("1 finding(s) already on the base not shown", out)

    def test_no_migrations(self):
        self.put("README.md", "hi")
        self.g("commit", "-q", "-m", "r")
        rc, out = self.run_main()
        self.assertEqual(rc, 2)
        self.assertIn("0 migration sets (none found)", out)


if __name__ == "__main__":
    unittest.main()

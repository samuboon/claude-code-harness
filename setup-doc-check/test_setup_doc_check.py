# -*- coding: utf-8 -*-
"""Tests for setup_doc_check.py.   python -m unittest test_setup_doc_check -v

Every repository here is a dict of path -> text, read through TreeRepo, so nothing touches disk.
"""
import io
import json
import os
import shutil
import sys
import tempfile
import unittest
from contextlib import redirect_stderr, redirect_stdout

sys.path.insert(0, os.path.dirname(os.path.abspath(__file__)))
import setup_doc_check as t  # noqa: E402


def repo(files, name="proj"):
    return t.TreeRepo(files.keys(), files.get, name=name)


def codes(files, docs=None):
    findings, _ = t.check_repo(repo(files), docs)
    return sorted((f[0], f[1], f[2]) for f in findings)


def msgs(files, docs=None):
    return [f[3] for f in t.check_repo(repo(files), docs)[0]]


def pkg(**scripts):
    return json.dumps({"name": "p", "scripts": scripts})


def md(*blocks, lang="bash"):
    return "\n\n".join("```%s\n%s\n```" % (lang, b) for b in blocks) + "\n"


class ScriptTest(unittest.TestCase):
    def test_missing_npm_script_is_an_error_and_names_the_near_ones(self):
        files = {"README.md": md("npm install\nnpm run dev"), "package.json": pkg(**{"dev:web": "x", "build": "y"})}
        self.assertEqual(codes(files), [("README.md", 3, "SCRIPT")])
        self.assertIn("dev:web", msgs(files)[0])

    def test_present_script_is_fine(self):
        files = {"README.md": md("npm run build"), "package.json": pkg(build="tsc")}
        self.assertEqual(codes(files), [])

    def test_npm_test_needs_a_test_script_but_start_falls_back_to_server_js(self):
        files = {"README.md": md("npm test\nnpm start"), "package.json": pkg(), "server.js": ""}
        self.assertEqual(codes(files), [("README.md", 2, "SCRIPT")])

    def test_yarn_bare_name_is_only_a_warning_and_a_dependency_is_not_reported(self):
        files = {"README.md": md("yarn dev\nyarn tsc\nyarn husky-helper"),
                 "package.json": json.dumps({"scripts": {}, "devDependencies": {"husky-helper": "1"}})}
        self.assertEqual(codes(files), [("README.md", 2, "SCRIPT?")])

    def test_yarn_and_pnpm_builtins_are_not_scripts(self):
        files = {"README.md": md("yarn install\nyarn add left-pad\npnpm install\npnpm add x\npnpm dlx y"),
                 "package.json": pkg()}
        self.assertEqual(codes(files), [])

    def test_pnpm_run_is_strict(self):
        files = {"README.md": md("pnpm run lint"), "package.json": pkg()}
        self.assertEqual(codes(files), [("README.md", 2, "SCRIPT")])

    def test_cd_is_followed_to_the_nearest_package_json(self):
        files = {"README.md": md("cd web\nnpm run dev", "npm run build\nnpm run lint", "npm run dev"),
                 "package.json": pkg(build="x"), "web/package.json": pkg(dev="vite"), "web/src/a.ts": ""}
        # the second block may go on in web/ or start over at the root: build is at the root,
        # dev is in web/, lint is nowhere
        self.assertEqual(codes(files), [("README.md", 8, "SCRIPT")])

    def test_heading_does_not_reset_a_known_directory_but_does_reset_a_lost_one(self):
        files = {"README.md": "```bash\ncd $HOME/x\n```\n\n## Run\n\n```bash\nnpm run nope\n```\n",
                 "package.json": pkg()}
        self.assertEqual(codes(files), [("README.md", 8, "SCRIPT")])

    def test_wrong_both_ways_is_reported_even_with_different_codes(self):
        files = {"README.md": md("cd backend\ncp .env.example .env", "npm run gen-api-key"),
                 "backend/package.json": pkg(**{"generate-api-key": "x"}), "backend/.env.example": ""}
        self.assertEqual(codes(files), [("README.md", 7, "SCRIPT")])

    def test_workspace_root_missing_a_script_a_package_has_is_a_warning(self):
        files = {"README.md": md("pnpm test\nyarn build:cli\npnpm run nowhere"), "pnpm-workspace.yaml": "",
                 "package.json": pkg(), "packages/a/package.json": pkg(test="x", **{"build:cli": "y"})}
        self.assertEqual(codes(files), [("README.md", 2, "SCRIPT?"), ("README.md", 4, "SCRIPT")])

    def test_inline_yarn_command_that_may_be_a_plugin_is_not_reported(self):
        files = {"README.md": "adds the [`yarn stage`](x) command\n", "package.json": pkg()}
        self.assertEqual(codes(files), [])

    def test_package_json_in_a_parent_is_used(self):
        files = {"README.md": md("cd src\nnpm run build"), "package.json": pkg(build="x"), "src/a.js": ""}
        self.assertEqual(codes(files), [])

    def test_prefix_and_workspace_flags(self):
        files = {"README.md": md("npm --prefix web run dev\nnpm run dev -w web\nnpm run --if-present x"),
                 "package.json": pkg(), "web/package.json": pkg()}
        self.assertEqual(codes(files), [("README.md", 2, "SCRIPT")])

    def test_no_package_json(self):
        files = {"README.md": md("npm run build")}
        self.assertEqual(codes(files), [("README.md", 2, "NOPROJ")])

    def test_inline_code_in_prose_is_read_for_scripts(self):
        files = {"README.md": "Then run `npm run serve` and open the page.\n", "package.json": pkg(dev="x")}
        self.assertEqual(codes(files), [("README.md", 1, "SCRIPT")])

    def test_inline_code_matches_any_package_of_the_repository(self):
        files = {"README.md": "## Frontend\n\n- `npm run preview` serves the build\n- `npm run nope`\n",
                 "package.json": pkg(), "web/package.json": pkg(preview="vite preview")}
        self.assertEqual(codes(files), [("README.md", 4, "SCRIPT")])

    def test_a_block_starting_with_cd_is_read_from_the_root(self):
        files = {"README.md": md("cd backend\nnpm run dev", "cd frontend\nnpm run dev"),
                 "backend/package.json": pkg(dev="x"), "frontend/package.json": pkg(dev="y")}
        self.assertEqual(codes(files), [])

    def test_a_lost_directory_comes_back_with_a_cd_that_works_from_the_root(self):
        files = {"README.md": md("cd $APP\nnpm run nope\ncd web\nnpm run gone"),
                 "web/package.json": pkg()}
        self.assertEqual(codes(files), [("README.md", 5, "SCRIPT")])

    def test_inline_code_in_prose_is_not_read_for_paths(self):
        files = {"README.md": "The shape `python gh_api.py post <path>` was refused.\n"}
        self.assertEqual(codes(files), [])


class MakeTest(unittest.TestCase):
    def test_missing_target(self):
        files = {"README.md": md("make setup\nmake tset"), "Makefile": "setup: deps\n\t@echo\ndeps:\n\ttrue\n"}
        self.assertEqual(codes(files), [("README.md", 3, "TARGET")])

    def test_included_file_and_pattern_rules(self):
        files = {"README.md": md("make lint\nmake out/app.o"),
                 "Makefile": "include mk/lint.mk\n%.o: %.c\n\tcc\n", "mk/lint.mk": "lint:\n\ttrue\n"}
        self.assertEqual(codes(files), [])

    def test_unreadable_include_makes_it_a_warning(self):
        files = {"README.md": md("make deploy"), "Makefile": "include $(TOP)/rules.mk\nall:\n"}
        self.assertEqual(codes(files), [("README.md", 2, "TARGET?")])

    def test_variables_and_flags_are_not_targets(self):
        files = {"README.md": md("make -j 4 DEBUG=1 all\nmake -C sub build"),
                 "Makefile": "all:\n", "sub/Makefile": "build:\n"}
        self.assertEqual(codes(files), [])

    def test_no_makefile_but_cmake_generates_one(self):
        files = {"README.md": md("mkdir build\ncd build\ncmake ..\nmake install"), "CMakeLists.txt": ""}
        self.assertEqual(codes(files), [])

    def test_makefile_written_by_cmake_into_a_new_folder(self):
        files = {"README.md": md("cmake -S cpp -B out\nmake -C out"), "cpp/CMakeLists.txt": ""}
        self.assertEqual(codes(files), [])

    def test_no_makefile(self):
        files = {"README.md": md("make")}
        self.assertEqual(codes(files), [("README.md", 2, "NOPROJ")])

    def test_double_colon_and_multiple_targets(self):
        files = {"README.md": md("make clean\nmake test"), "Makefile": "clean::\n\trm\nlint test: x\n"}
        self.assertEqual(codes(files), [])

    def test_shorthand_for_several_commands_is_not_read(self):
        files = {"README.md": md("make logs-core / logs-ingest"), "Makefile": "all:\n"}
        self.assertEqual(codes(files), [])

    def test_default_rule_takes_every_target(self):
        files = {"README.md": md("make distclean"), "Makefile": ".DEFAULT:\n\tcd src && $(MAKE) $@\n"}
        self.assertEqual(codes(files), [])

    def test_inline_make_without_a_makefile_is_about_another_project(self):
        files = {"README.md": "searches the Linux tree (after `make defconfig && make -j8`)\n"}
        self.assertEqual(codes(files), [])

    def test_recipe_lines_are_not_rules(self):
        files = {"README.md": md("make echo"), "Makefile": "all:\n\techo: hi\n"}
        self.assertEqual(codes(files), [("README.md", 2, "TARGET")])


class PathTest(unittest.TestCase):
    def test_cp_env_example(self):
        files = {"README.md": md("cp .env.example .env\ncat .env"), ".env.sample": ""}
        self.assertEqual(codes(files), [("README.md", 2, "PATH")])

    def test_created_file_is_known_afterwards(self):
        files = {"README.md": md("cp .env.example .env\nsource .env"), ".env.example": ""}
        self.assertEqual(codes(files), [])

    def test_requirements_file(self):
        files = {"README.md": md("pip install -r requirements-dev.txt\npython -m pip install -r requirements.txt"),
                 "requirements.txt": ""}
        self.assertEqual(codes(files), [("README.md", 2, "PATH")])

    def test_venv_then_activate(self):
        files = {"README.md": md("python3 -m venv .venv\nsource .venv/bin/activate\npip install -e '.[dev]'"),
                 "pyproject.toml": ""}
        self.assertEqual(codes(files), [])

    def test_gitignored_paths_are_generated(self):
        files = {"README.md": md("source venv/bin/activate\n./build/app"), ".gitignore": "venv/\n/build\n"}
        self.assertEqual(codes(files), [])

    def test_cd_into_missing_folder_and_then_lost(self):
        files = {"README.md": md("cd frontend\nnpm run dev"), "web/package.json": pkg()}
        self.assertEqual(codes(files), [("README.md", 2, "PATH")])

    def test_clone_then_cd_into_the_clone(self):
        files = {"README.md": md("git clone https://github.com/o/upstream-name.git\ncd upstream-name\n./scripts/setup.sh"),
                 "scripts/bootstrap.sh": ""}
        self.assertEqual(codes(files), [("README.md", 4, "PATH")])

    def test_clone_then_cd_into_a_folder_of_the_clone(self):
        files = {"README.md": md("git clone https://github.com/o/app.git\ncd app/web\nnpm run dev"),
                 "web/package.json": pkg(dev="vite")}
        self.assertEqual(codes(files), [])

    def test_clone_of_a_placeholder_then_cd_into_a_folder_of_it(self):
        files = {"research/README.md": md("git clone <this-repo>\ncd tribe-social\nmake setup"),
                 "research/Makefile": "setup:\n", "package.json": pkg()}
        # the document is in research/, but after the clone it starts from the clone's root
        self.assertEqual(codes(files, ["research/README.md"]), [("research/README.md", 4, "NOPROJ")])

    def test_clone_into_named_folder(self):
        files = {"README.md": md("git clone https://x/y.git mine && cd mine && python manage.py migrate"),
                 "manage.py": ""}
        self.assertEqual(codes(files), [])

    def test_after_a_build_step_a_missing_path_is_a_warning(self):
        files = {"README.md": md("npm run build\nnode dist/index.js"), "package.json": pkg(build="tsc")}
        self.assertEqual(codes(files), [("README.md", 3, "PATH?")])

    def test_placeholders_urls_and_absolute_paths_are_skipped(self):
        files = {"README.md": md("cp <your-config> config.yml\ncd /opt/app\nsource ~/.bashrc\n"
                                 "bash https://x.sh\npython path/to/script.py")}
        self.assertEqual(codes(files), [])

    def test_node_resolves_folders_and_extensions(self):
        files = {"README.md": md("node examples/chat\nnode scripts/seed\nnode examples/gone"),
                 "examples/chat/index.js": "", "scripts/seed.js": ""}
        self.assertEqual(codes(files), [("README.md", 4, "PATH")])

    def test_git_clone_options_with_values(self):
        files = {"README.md": md("git clone --depth 1 -b main https://x/proj.git\ncd proj\n./go.sh"),
                 "run.sh": ""}
        self.assertEqual(codes(files), [("README.md", 4, "PATH")])

    def test_compose_file(self):
        files = {"README.md": md("docker compose -f docker-compose.dev.yml up\ndocker-compose up"),
                 "docker-compose.yml": ""}
        self.assertEqual(codes(files), [("README.md", 2, "PATH")])

    def test_no_compose_file(self):
        files = {"README.md": md("docker compose up -d")}
        self.assertEqual(codes(files), [("README.md", 2, "NOPROJ")])

    def test_console_blocks_read_only_prompted_lines(self):
        files = {"README.md": md("$ ./run.sh\n./missing.sh: done\n$ npm run x", lang="console"),
                 "run.sh": "", "package.json": pkg(x="1")}
        self.assertEqual(codes(files), [])

    def test_a_block_with_prompts_shows_output_on_the_other_lines(self):
        files = {"README.md": md("$ http pie.dev/basic-auth\nHTTP/1.1 200 OK\n./gone.sh"), "x": ""}
        self.assertEqual(codes(files), [])

    def test_missing_path_names_the_file_of_that_name_elsewhere(self):
        files = {"README.md": md("./compare.sh main next"), "scripts/benchmark/compare.sh": ""}
        self.assertIn("scripts/benchmark/compare.sh", msgs(files)[0])

    def test_angle_prompts_and_cd_written_from_the_parent_of_the_repository(self):
        files = {"README.md": md("> fd netfl\nSoftware/python/netflix.py\n> cd proj/tests\n> ./run.sh"),
                 "tests/run.sh": ""}
        self.assertEqual(codes(files), [])

    def test_a_folder_named_in_the_prose_just_before_the_block(self):
        files = {"README.md": "Install them (from the `docs` directory):\n\n" + md("pip install -r requirements.txt")
                 + "\nThe script [`scripts/bench/compare.sh`](x) compares:\n\n" + md("./compare.sh a b")
                 + "\n## Next\n\nAnd then:\n\n" + md("pip install -r requirements.txt"),
                 "docs/requirements.txt": "", "scripts/bench/compare.sh": ""}
        # the third block, under a new heading, has no folder named before it
        self.assertEqual(codes(files), [("README.md", 18, "PATH?")])

    def test_a_folder_named_in_a_list_step_holds_for_the_next_steps(self):
        files = {"CONTRIBUTING.md": "1. `cd` into the `/docs` directory.\n2. Install:\n\n   ```sh\n   npm install\n"
                 "   ```\n\n3. Start:\n\n   ```sh\n   npm run dev\n   ```\n",
                 "docs/package.json": pkg(dev="x"), "package.json": pkg()}
        self.assertEqual(codes(files), [])

    def test_prompted_lines_are_read_whatever_the_command(self):
        files = {"README.md": md("$ cat > script <<EOF\nfoo:\nEOF\n$ chmod +x script\n$ ./script foo\n$ ./gone",
                                 lang="console")}
        self.assertEqual(codes(files), [("README.md", 7, "PATH")])

    def test_a_folder_readme_names_its_own_package_first(self):
        files = {"web/README.md": md("npm run nope"), "web/package.json": pkg(), "package.json": pkg()}
        self.assertIn("web/package.json", msgs(files, ["web/README.md"])[0])

    def test_a_folder_readme_that_says_run_from_the_root(self):
        files = {"docs/README.md": "Run from the project root:\n\n" + md("npm run lint:docs"),
                 "docs/package.json": pkg(start="x"), "package.json": pkg(**{"lint:docs": "y"})}
        self.assertEqual(codes(files, ["docs/README.md"]), [])

    def test_placeholders_dots_and_foo(self):
        files = {"README.md": md("cd ...\nnode test/foo.test.js\nnode docs/test/repro-XXXX.js")}
        self.assertEqual(codes(files), [])

    def test_script_from_stdin_worktree_and_copy_into_another_repository(self):
        files = {"README.md": md("cp src/api.c <your-path-to-undici>/deps/\nbash -s -- ./out/tool < install.sh\n"
                                 "git worktree add main main\ncd main"), "install.sh": ""}
        self.assertEqual(codes(files), [])

    def test_tutorial_file_shown_in_the_block_before(self):
        files = {"README.md": "```python\nprint('hi')\n```\n\n```\n$ python hello.py\n```\n\n"
                              "```bash\npython gone.py\n```\n"}
        self.assertEqual(codes(files), [("README.md", 10, "PATH")])

    def test_folder_named_by_a_file_inside_it_and_by_an_absolute_looking_path(self):
        files = {"README.md": "Run a single file, for example `test/basic.test.js`:\n\n" + md("node test/basic.test.js")
                 + "\n1. `cd` into the `/docs` directory.\n\n" + md("npm run dev"),
                 "packages/core/test/basic.test.js": "", "docs/package.json": pkg(dev="x"), "package.json": pkg()}
        self.assertEqual(codes(files), [])

    def test_project_makers_and_archives(self):
        files = {"INSTALL.md": md("curl -L https://x/eza.tar.gz | tar xz\nsudo mv eza /usr/local/bin/eza"),
                 "README.md": md("uv init awesome-project --bare\ncd awesome-project\nuv add x",
                                 "cargo new hello\ncd hello")}
        self.assertEqual(codes(files), [])

    def test_rust_toolchain_reads_the_channel_not_the_license(self):
        files = {"README.md": "hi\n", "rust-toolchain.toml": "# SPDX: EUPL-1.2\n[toolchain]\nchannel = \"1.90\"\n",
                 "Cargo.toml": "rust-version = \"1.90\"\n"}
        self.assertEqual(codes(files), [])

    def test_readme_in_docs_starts_in_docs(self):
        files = {"docs/README.md": md("npm start"), "docs/package.json": pkg(start="x"), "package.json": pkg()}
        self.assertEqual(codes(files), [])

    def test_unlabelled_blocks_read_only_known_commands(self):
        files = {"README.md": "```\nsrc/\n  lib/util.py\npython main.py\n```\n", "src/main.py": ""}
        self.assertEqual(codes(files), [("README.md", 4, "PATH")])

    def test_other_languages_are_not_shell(self):
        files = {"README.md": md("cd nowhere", lang="python")}
        self.assertEqual(codes(files), [])

    def test_continuation_heredoc_and_substitution(self):
        files = {"README.md": md("cat > .env <<EOF\ncd nowhere\nEOF\nsource .env\ncd $(git rev-parse --show-toplevel)\n"
                                 "pip install \\\n  -r req.txt")}
        self.assertEqual(codes(files), [("README.md", 7, "PATH")])

    def test_folder_readme_starts_in_its_folder(self):
        files = {"tools/x/README.md": md("python x.py\npython tools/x/x.py"), "tools/x/x.py": ""}
        self.assertEqual(codes(files, ["tools/x/README.md"]), [])

    def test_powershell_prompt_and_backslashes(self):
        files = {"README.md": md("PS> .\\scripts\\setup.ps1", lang="powershell"), "scripts/setup.ps1": ""}
        self.assertEqual(codes(files), [])

    def test_env_prefix_and_sudo(self):
        files = {"README.md": md("NODE_ENV=dev sudo -E ./start.sh"), "start.sh": ""}
        self.assertEqual(codes(files), [])


class VersionTest(unittest.TestCase):
    def test_prose_below_engines(self):
        files = {"README.md": "Requires Node.js 16 or later.\n",
                 "package.json": json.dumps({"engines": {"node": ">=18.17"}})}
        self.assertEqual(codes(files), [("README.md", 1, "VERSION")])

    def test_prose_at_or_above_is_fine(self):
        files = {"README.md": "You need Node 20+.\n", "package.json": json.dumps({"engines": {"node": "^18 || ^20"}})}
        self.assertEqual(codes(files), [])

    def test_python_minor(self):
        files = {"README.md": "Prerequisites: Python 3.8+\n",
                 "pyproject.toml": "[project]\nrequires-python = \">=3.10\"\n"}
        self.assertEqual(codes(files), [("README.md", 1, "VERSION")])

    def test_python_same_minor_is_fine(self):
        files = {"README.md": "Prerequisites: Python 3.10+\n",
                 "pyproject.toml": "[project]\nrequires-python = \">=3.10\"\n"}
        self.assertEqual(codes(files), [])

    def test_lines_without_a_requirement_word_are_ignored(self):
        files = {"README.md": "We moved from Python 3.6 in 2021.\nPython 3.7 is no longer supported; install a newer one.\n",
                 "pyproject.toml": "requires-python = \">=3.10\"\n"}
        self.assertEqual(codes(files), [])

    def test_history_is_not_a_requirement(self):
        files = {"README.md": "Node.js includes fetch() starting from Node.js v18, unlike installing undici.\n",
                 "package.json": json.dumps({"engines": {"node": ">=22"}})}
        self.assertEqual(codes(files), [])

    def test_java_release_and_one_dot_eight(self):
        files = {"README.md": "Requires Java 1.8 or JDK 11\n", "pom.xml": "<maven.compiler.release>17</maven.compiler.release>"}
        self.assertEqual([c for c in codes(files)], [("README.md", 1, "VERSION"), ("README.md", 1, "VERSION")])

    def test_go_mod(self):
        files = {"README.md": "Install Go 1.20 or newer.\n", "go.mod": "module x\n\ngo 1.22\n"}
        self.assertEqual(codes(files), [("README.md", 1, "VERSION")])

    def test_go_since_1_21_fetches_the_toolchain_so_only_a_warning(self):
        files = {"README.md": "Prerequisites: Go 1.26+\n", "go.mod": "module x\n\ngo 1.27.0\n"}
        self.assertEqual(codes(files), [("README.md", 1, "VERSION?")])
        self.assertIn("GOTOOLCHAIN=local", msgs(files)[0])

    def test_rust_version(self):
        files = {"README.md": "you need Rust 1.79.0 or higher\n", "Cargo.toml": "rust-version = \"1.88\"\n"}
        self.assertEqual(codes(files), [("README.md", 1, "VERSION")])

    def test_only_a_pin_is_a_warning(self):
        files = {"README.md": "Install Node 18.\n", ".nvmrc": "v20.11.1\n"}
        self.assertEqual(codes(files), [("README.md", 1, "VERSION?")])

    def test_install_command_below_requirement(self):
        files = {"README.md": md("nvm install 16\npyenv install 3.9.7"),
                 "package.json": json.dumps({"engines": {"node": ">=18"}}),
                 ".python-version": "3.11.4\n"}
        self.assertEqual(codes(files), [("README.md", 2, "VERSION"), ("README.md", 3, "VERSION?")])

    def test_the_strictest_minimum_of_the_repository_wins(self):
        files = {"README.md": "Requires Python 3.9+\n", "setup.cfg": "python_requires = >=3.8\n",
                 "pyproject.toml": "requires-python = \">=3.10\"\n"}
        self.assertEqual(codes(files), [("README.md", 1, "VERSION")])

    def test_pin_below_minimum_inside_the_repository(self):
        files = {"README.md": "hi\n", ".nvmrc": "18\n", "package.json": json.dumps({"engines": {"node": ">=20"}})}
        self.assertEqual(codes(files), [(".nvmrc", 1, "PINS")])

    def test_range_min(self):
        self.assertEqual(t.range_min("node", ">=18.17.0 <21"), (18,))
        self.assertEqual(t.range_min("node", "^20 || ^18"), (18,))
        self.assertEqual(t.range_min("node", "^18 || ^20"), (18,))
        self.assertEqual(t.range_min("python", "~=3.9"), (3, 9))
        self.assertEqual(t.range_min("python", ">=3.8,<4"), (3, 8))
        self.assertEqual(t.range_min("node", "18.x"), (18,))


class DocsAndCliTest(unittest.TestCase):
    def test_default_documents(self):
        r = repo({"README.md": "", "CONTRIBUTING.md": "", "docs/development.md": "", "docs/api.md": "",
                  ".github/CONTRIBUTING.md": "", "src/README.md": ""})
        self.assertEqual(t.find_docs(r), ["README.md", "CONTRIBUTING.md", "docs/development.md",
                                          ".github/CONTRIBUTING.md"])

    def test_markdown_fence_rules(self):
        text = "  ```bash\n  cd x\n  ```\n~~~~sh\n```\nnot closed by a shorter fence\n~~~~\n"
        ev = [(k, lg, n, s) for k, lg, n, s in t.read_markdown(text) if k == "code"]
        self.assertEqual(ev, [("code", "bash", 2, "cd x"), ("code", "sh", 5, "```"),
                              ("code", "sh", 6, "not closed by a shorter fence")])

    def test_cli_exit_codes_and_summary(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as f:
                f.write(md("npm run dev"))
            with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as f:
                f.write(pkg(dev="x"))
            out, err = io.StringIO(), io.StringIO()
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(t.main([d]), 0)
            self.assertIn("1 things checked", err.getvalue())
            with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as f:
                f.write(pkg())
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(t.main([d, "--tsv"]), 1)
            self.assertIn("README.md\t2\terror\tSCRIPT", out.getvalue())
            os.remove(os.path.join(d, "README.md"))
            with redirect_stdout(out), redirect_stderr(err):
                self.assertEqual(t.main([d]), 2)
        finally:
            shutil.rmtree(d)

    def test_warnings_fail_only_with_strict(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as f:
                f.write(md("yarn dev"))
            with open(os.path.join(d, "package.json"), "w", encoding="utf-8") as f:
                f.write(pkg())
            with redirect_stdout(io.StringIO()), redirect_stderr(io.StringIO()):
                self.assertEqual(t.main([d]), 0)
                self.assertEqual(t.main([d, "--strict"]), 1)
        finally:
            shutil.rmtree(d)

    def test_nothing_checked_is_said(self):
        d = tempfile.mkdtemp()
        try:
            with open(os.path.join(d, "README.md"), "w", encoding="utf-8") as f:
                f.write("# hello\n")
            err = io.StringIO()
            with redirect_stdout(io.StringIO()), redirect_stderr(err):
                self.assertEqual(t.main([d]), 0)
            self.assertIn("nothing was checked", err.getvalue())
        finally:
            shutil.rmtree(d)


if __name__ == "__main__":
    unittest.main()

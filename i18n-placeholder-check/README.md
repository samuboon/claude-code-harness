**日本語版: [README.ja.md](README.ja.md)**

# i18n-placeholder-check — Jenkins fixed 34 of these by hand in 12 commits since 2008, and its master today still prints `{0}` where an agent's name should be

`java.text.MessageFormat` treats an apostrophe as the start of a quoted section. In a
translation that nobody runs through the English test suite, that is a quiet bug:

```properties
# hudson/model/Messages.properties                (the base, with typographic quotes)
ComputerSet.SlaveAlreadyExists=Agent called ‘{0}’ already exists
# hudson/model/Messages_pt_BR.properties          (ASCII quotes, on Jenkins master 2026-09-24)
ComputerSet.SlaveAlreadyExists=O agente chamado '{0}' já existe
```

The Portuguese message prints `O agente chamado {0} já existe` — the braces literally, no name.
`Il valore dev'essere maggiore o uguale a {0}` (Italian) prints `Il valore devessere maggiore o uguale a {0}`.
The file loads, every key is there, the English build is fine, and nothing fails.

`i18n_placeholder_check.py` reads a tree of `.properties` bundles the way `Properties.load` and
`MessageFormat.applyPattern` do, and compares every translation with its base file.

```bash
python i18n_placeholder_check.py src/main/resources
python i18n_placeholder_check.py src/main/resources --always-messageformat --key-as-base   # Jenkins, Stapler
python i18n_placeholder_check.py src/main/resources --tsv                                  # one row per finding
```

```
.../Messages_pt_BR.properties:127: error QUOTED ComputerSet.SlaveAlreadyExists: an apostrophe quoted {0}; prints: O agente chamado {0} já existe
.../Messages_it.properties:178: error QUOTED Hudson.MustBeAtLeast: an apostrophe quoted {0}; prints: Il valore devessere maggiore o uguale a {0}
.../changes_tr.properties:25: warning APOS from.label: a lone apostrophe is eaten by MessageFormat; prints: #<0>dan
```

In `prints:`, `<0>` is where argument 0 goes; a `{0}` there is one that will be printed as is.
Standard library only. Reads files, writes nothing, no network (except `replay_fixes.py`, below).

---

## What it reports

| Code | Level | Meaning |
|---|---|---|
| `BROKEN` | error | `MessageFormat` throws `IllegalArgumentException` on the value: an unmatched brace, `{}`, `{name}`, `{{0}}`, an unknown type, a bad choice pattern (or a choice branch that would throw when chosen). |
| `QUOTED` | error | An apostrophe opened a quoted section that swallowed a placeholder the base uses; it is printed as `{0}`. |
| `BADFILE` | error | The file does not load at all (a malformed `\uXXXX` escape — `ResourceBundle` refuses the whole file). |
| `APOS` | warning | A lone apostrophe in a value read as a pattern; it disappears from the output (`n'existe` → `nexiste`). A quoted section with a brace in it (`'{'`) is the documented way to print a brace and is not reported. |
| `MISSING` | warning | The translation does not use a placeholder the base uses. |
| `EXTRA` | warning | The translation uses a placeholder the base does not. Unless the code passes more arguments than the base shows, it is printed as `{2}`. |
| `BOM` | warning | The file starts with a byte-order mark; `Properties.load` keeps it, so the first key becomes U+FEFF + key and never matches. |
| `TYPE` | note | The translation formats a placeholder the base leaves plain (`{0,choice,...}` for plural forms where the base has `{0}`). Fine for a number; throws `Cannot format given Object as a Number` for a string. A translation that *drops* a type is not reported: `{0}` and `{0,number}` print a number the same way. |
| `ORPHAN` | note | A key the base does not have. Its value is still checked on its own. |
| `DUP` | note | The same key twice in one file (the later one wins). |

**Which values are patterns.** By default, a key whose base value has at least one placeholder
(most code calls `MessageFormat.format` only when it has arguments), and a `.properties` file with
no translation next to it is taken for configuration and not read at all.
`--always-messageformat` reads every value as a pattern. **That is Jenkins' convention**, as its
own history says: `db7a19810d` "MessageFormat treats ' as a special character", `655601ebb3`
"Unescaped apostrophes were dropped from message formats" — both fix messages with no placeholder.

**Keys that are the text.** In Jelly views, `${%Other Jenkins}` makes the English text the key,
and the translation file often has no base file. `--key-as-base` compares such a key with itself
— only a key with a space or a brace in it, so an id like `PluginWrapper.disabled` is not mistaken
for text. `--base-locale en` uses `Messages_en.properties` when there is no `Messages.properties`.

**Java 21 or 25.** `--java 21` (the default; Java 8 to 21 behave the same here) knows the four
format types `number`, `date`, `time`, `choice` and reads an unquoted `#` inside a choice branch as
the end of a limit, which throws. `--java 25` also accepts `dtf_date`, `dtf_time`, `dtf_datetime`,
`list` and the `iso_*` formatter names, and keeps `#` in a branch as text. On Jenkins master the
two give the same findings.

**Exit codes:** 0 = no error (warnings do not fail unless `--strict`). 1 = an error.
2 = no `.properties` file found. **3 = nothing failed, but some translation files had no base
file and were not compared** (use `--key-as-base` or `--base-locale`). 3 is not a pass.

---

## Measured

### Jenkins' own fixes, replayed (`replay_fixes.py`)

We searched the Jenkins repository's history for commits about apostrophes and quotes, and took
the 15 that change `.properties` files. For each one, every key whose value changed was checked
as it was **before** and **after** the commit (`--always-messageformat --key-as-base`).

| Commits | Changed keys | Flagged before | Still flagged after |
|---|---|---|---|
| 12 that fix an apostrophe `MessageFormat` ate (2008–2019) | 36 | **36** | 2 |
| 3 that only change style (`''` → `’`, `''` → `„“`, a contraction spelled out) | 96 | **0** | 0 |

The 2 still flagged after are left over by the commit itself: `8a8fbbaad6` ("Spelling and proper
escaping for apostrophes", 2009) corrected the spelling of "it'll wrec havoc" and left the
apostrophe, which `527c5935fd` fixed in 2019 (JENKINS-55834); `655601ebb3` left `href='...'` in the
same message, which today's master writes with double quotes.
**Without `--always-messageformat`, 4 of the 36 are flagged** — most of these messages have no
placeholder, which is exactly the case the default leaves alone.

```bash
python replay_fixes.py            # prints every changed key with both values; -q for one line per commit
```

### Jenkins master today (commit `bdefb3e`, read 2026-09-24)

7,489 `.properties` files, 348 bundles.

| Mode | Compared keys | `BROKEN` | `QUOTED` | `APOS` | `MISSING` | `EXTRA` | `TYPE` (note) |
|---|---|---|---|---|---|---|---|
| default | 19,806 (2,993 files without a base not compared, exit 3 otherwise) | 1 | 11 | 8 | 95 | 15 | 35 |
| `--always-messageformat --key-as-base` | 27,600 | 9 | 11 | 80 | 95 | 17 | 35 |

- **`QUOTED`, 11 in 10 messages**: 7 in 6 Brazilian Portuguese messages (`'{0}'` written for the base's
  `‘{0}’`), 2 in Italian (`dev'essere`), 2 in Turkish (`#{0}'dan #{1}'a`, `'{0}' adlı`). Each prints
  a literal `{0}` or `{1}` in place of a name or a build number.
- **`BROKEN`**: 1 message in both modes — Estonian `kataloog {{0}}`. With `--always-messageformat`
  on the whole tree, 6 more are Maven filter templates (`${project.version}` under `src/filter`),
  which are not messages, and 2 are a translated key with an unescaped `:` (`Log:\ ${my.displayName}`),
  so the file defines the key `Log` and the translation is never used.
- **`APOS`**: 80, of which 19 in Turkish, 13 in French, 10 in Italian; 1 is in the English base
  (`_safeRestart.properties`: "if you don't supply one").
- **`TYPE`**: 33 of the 35 are translations adding plural forms to `Util.second`, `Util.year` and
  the like, whose argument is a number; the other 2 (German, Italian) format as a number what the
  base prints plain. That is why `TYPE` is a note.

**What we have not checked.** We have not seen any of these in a running Jenkins, and there is no
Java on the machine we measured on. The parser was checked against the source of `MessageFormat`,
`ChoiceFormat` and `Properties` in OpenJDK's `jdk21u` and `jdk25u` (2026-09-24) by reading it, not
by running it. Whether a given Jelly view formats a message with no arguments is Jenkins' business; the
fix history above is why we think it does.

---

## Limits

- **`java.text.MessageFormat` only.** ICU's MessageFormat (`{count, plural, one {...} other {...}}`,
  `select`), Android `strings.xml`, gettext and JSON catalogues are not read.
- Number and date *styles* (`{0,number,#.##}`) are not validated; a bad `DecimalFormat` pattern
  would throw in Java and pass here.
- Two JDK quirks are kept on purpose: an unfinished argument with an inner brace still open
  (`{0,choice,0#{1`) is silently dropped, as `applyPattern` does, and `{+1}` is argument 1.
- A file name like `help_ant.properties` next to `help.properties` is read as locale `ant`, as
  Java would read it if that locale were asked for.
- 55 tests; `mutation_check.py` breaks the checker 26 ways and all 26 are caught. **The first run
  had 22 and caught 21**: trying the shortest file-name stem first (`Messages_pt` for
  `Messages_pt_BR`) was not noticed until a test with `help_ant_de.properties` was added. The 4
  added after reading the OpenJDK source (Java 25's types, `#` in a choice branch, the argument
  index limit of 10,000, an infinity limit with a space before it) were caught the first time.

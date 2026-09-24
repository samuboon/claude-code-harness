**English: [README.md](README.md)**

# setup-doc-check —— bat の README は「Rust 1.79 で作れる」と書く。Cargo.toml は 1.88 より古いものを受け付けない

環境構築の手順は、改名 1 回ごとに古くなります。スクリプトは `db:migrate` になり、Makefile から
`convert` が消え、requirements のファイルが移り、対応する Python の下限が上がる —— それでも
README は昔のまま残ります。README を走らせるものは何も無いからです。

`setup_doc_check.py` は、リポジトリの README・CONTRIBUTING・環境構築の文書にあるシェルの命令を読み、
それぞれが動くかどうかを、シェルではなく**リポジトリに**尋ねます。その npm スクリプトは届く先の
`package.json` にあるか、その make の対象を作る規則はあるか、命令が要るファイルはあるか、文書が
書く言語の版はプロジェクトが宣言する下限以上か。何も実行しません。

```bash
python setup_doc_check.py path/to/repo
python setup_doc_check.py path/to/repo --doc docs/development.md   # この文書だけ
python setup_doc_check.py path/to/repo --explain                   # 読んだ命令と、どのフォルダで読んだか
```

2026-09-24 の `sharkdp/bat` と `date-fns/date-fns` の写しで:

```
$ python setup_doc_check.py bat
README.md:430: error VERSION the document says rust 1.79; Cargo.toml rust-version requires 1.88
doc/README-ja.md:369: error VERSION the document says rust 1.79; Cargo.toml rust-version requires 1.88
6 documents, 456 commands read, 5 things checked against the repository, 38 lines not read (substitutions, heredocs), 0 paths skipped as ignored or generated; 2 errors, 0 warnings

$ python setup_doc_check.py date-fns
CONTRIBUTING.md:113: warning PATH? run scripts/build/package.sh: not in the repository (an earlier step may make it); package.sh is at pkgs/core/scripts/build/package.sh
CONTRIBUTING.md:114: warning PATH? cd lib: not in the repository (an earlier step may make it)
CONTRIBUTING.md:131: warning SCRIPT? pnpm run lint: no script 'lint' in the workspace root package.json; 1 workspace package(s) have it, e.g. pkgs/core/package.json
2 documents, 16 commands read, 8 things checked against the repository, 0 lines not read (substitutions, heredocs), 0 paths skipped as ignored or generated; 0 errors, 3 warnings
```

(bat で 456 本読んで照合が 5 件なのは、README の大半が `bat` そのものの使い方で、リポジトリに
尋ねて答えの出る問いではないからです。)

標準ライブラリのみ。ファイルを読むだけで、何も書かず、通信もしません(下の `replay_fixes.py` を除く)。
最後の行は、実際にいくつ照合したかを必ず言います。リポジトリに触れる命令が 1 本も無い README は、
黙って合格にせず、そう書きます。

---

## 何を報告するか

| 記号 | 水準 | 意味 |
|---|---|---|
| `SCRIPT` | error | `npm run X`・`npm test`・`pnpm run X` で、命令を打つフォルダから上に辿って最初の `package.json` に `X` が無い(npm は上に辿るので、これも辿る)。近い名前を並べる。 |
| `TARGET` | error | `make X` で、その Makefile にも `include` 先にも `X` を作る規則が無い(パターン規則と `.DEFAULT` は数える)。 |
| `PATH` | error | 命令が要るファイルかフォルダがリポジトリに無く、前の命令が作ってもいない: `cd`、`cp`/`mv` の元、`source`、`./x`、`bash x.sh`、`python x.py`、`node x.js`、`pip install -r x`、`docker compose -f x`、`conda env create -f x`。 |
| `NOPROJ` | error | 上に `package.json` の無い `npm run`、Makefile の無い `make`(CMake・configure・meson など Makefile を書くものも無い)、compose ファイルの無い `docker compose`。 |
| `VERSION` | error | 文書が、リポジトリの要求より古い言語の版を書いている: `engines.node`、`requires-python` / Poetry の `python`、`python_requires`、`go.mod`、Gradle / Maven の Java の版、`Gemfile` の `ruby`、`Cargo.toml` の `rust-version`。文(「Node 16 以上が必要」)も、導入の命令(`nvm install 16`、`pyenv install 3.9`)も数える。 |
| `SCRIPT?` | warning | `yarn X` / `pnpm X` / `bun run X` にスクリプト `X` が無い(次にその名前の実行ファイルを探す)。または、ワークスペースの根に無く、ワークスペースの中のパッケージにはある。 |
| `TARGET?` | warning | 規則は無いが、読めない `include`(`include $(TOP)/rules.mk`)がある。 |
| `PATH?` | warning | 無いが、前の段(ビルド・導入・ダウンロード)が作ったかもしれない。 |
| `VERSION?` | warning | *固定した*版(`.nvmrc`・`.python-version`・`.tool-versions` など)より下なだけ。または Go 1.21 以上で `go.mod` より下(`GOTOOLCHAIN=local` でなければ Go が新しい版を自分で取ってくる)。 |
| `PINS` | warning | リポジトリの中で食い違っている: `.nvmrc` は 18、`engines.node` は 20 以上。 |

**文書の読み方。** `sh`・`bash`・`console`・`powershell` などの札が付いたコードブロック。プロンプト
(`$ `・`> `・`PS> `)を見せるブロックでは、プロンプトの行だけ。札の無いブロックは、知っている道具で
始まる行だけ。本文中のインラインコードは npm スクリプトと make の対象だけを読み(「次に
`npm run dev` を打つ」)、パスは読みません —— 本文が命令を引く理由は他にも多すぎるからです。
ヒアドキュメントの中身・`$(...)`・バッククォートを含む行は飛ばして数えます。`<置き場所>`・`path/to/`・
`your-`・`...`・`XXXX` も飛ばします。

**命令をどのフォルダで打つか。** `cd` は追い、`git clone URL [dir]` の後の `cd dir` はリポジトリの根、
フォルダの中の README はそのフォルダから始めます。文書が*書かない*のは、新しいブロックがどこから
始まるかです。そこで、`cd` しないブロックの命令は、読み方の**どれで読んでも**誤りのときだけ報告します:
前のブロックが終わった場所・文書が始まる場所・根・すぐ前の本文が名指ししたフォルダ(「`docs`
ディレクトリで」「スクリプト `scripts/benchmark/compare.sh`」)。前の命令が作ったものは覚えます:
`cp .env.example .env`・`mkdir`・`touch`・`> file`・`python -m venv .venv`・`uv init NAME`・`cargo new NAME`・
`git worktree add DIR`。`.gitignore` に載るパスと、アーカイブを展開した後のものは生成物とみなします。

**終了コード:** 0 = 誤りなし(警告は `--strict` でなければ失敗にしない)。1 = 誤りあり。
2 = 読む文書が無い。

---

## 実測

### 各プロジェクトが自分の README に入れた修正を再生した(`replay_fixes.py`)

GitHub のコミット検索で「README の命令を直した」と書くコミットを探し(「fix README script name」
「wrong script name」「make target」「fix setup instructions」など。`apache` や `vercel` を含む
いくつかの組織でも)、読者が打つ命令を差分が変えている 33 本を残しました。1 本ずつ、コミットの
**前**と**後**のリポジトリで検査器を走らせました。GitHub が配る tarball から読み、API は 1 回も
呼んでいません。

| コミット | 前に印が付き、後で消えた | 後にだけ付いた | 付かなかった |
|---|---|---|---|
| 文書のほうを直した 27 本 | **15** 本(27 行) | 1 | 11 |
| リポジトリのほうを文書に合わせた 6 本 | **2** 本(6 行) | 0 | 4 |

- **捕まえたもの(一部):** `redis/node-redis` の `7dff63f33d`(CONTRIBUTING の `npm run build:tests-tools`。
  `package.json` に無いスクリプト)、`apache/teaclave-trustzone-sdk` の `bb1647d333`(Hello World の例が
  文書の言う場所に無く、`cd examples/hello_world-rs` とその後の `make` が失敗する)、README の下で
  改名されたスクリプト(`prisma:migrate` → `db:migrate`、`gen-api-key` → `generate-api-key`、
  `build` → `build:chrome:prod`)、一度も存在しなかった Makefile の対象(`make scale`・`make drain`)。
- **逆向きの 1 本:** `ermesjoandreas/praetrace` の `57bf95a63b` は、`package.json` より先に README の
  `npm run codemap` を `codemaps` に改名しました。検査器はこのコミットの*後*の側に印を付けます。
  次のコミットまでは、実際に README のほうが誤っていました。
- **付かなかったものと理由。** 11 本のうち 8 本は、リポジトリに尋ねて答えの出る名前ではありません:
  Gradle のテスト名(`apache/kafka`)、Go のモジュールパス(`apache/incubator-seata-go`)、Cargo の
  機能フラグ(`apache/datafusion`)、`chmod` のグロブ(`apache/ranger`)、`grep`・`rm`・`flatc` の引数
  (`apache/arrow-java`)、スクリプトの名前ではなく中身(`vercel/turborepo`)、両方とも存在する 2 本の
  スクリプトのうち違うほう(`agent-substrate/substrate`)、`readme.txt`。3 本は取りこぼしです: リポジトリに
  無いフォルダへの `cd` の後で検査器が位置を見失い、その後の行を読まない(`cd` は報告する)。
  `--workspace` を追わない。Makefile が同じコミットで変わった 1 本。
- 付かなかったリポジトリ側の 4 本: 足りなかったのが依存パッケージ(ファイルではない)、壊れていたのが
  レシピの中身、requirements のファイルと README の手順を同時に足した 2 本。

```bash
python replay_fixes.py                              # 33 本すべて。前後の指摘を全部出す
python replay_fixes.py owner/name@SHA               # 他の公開コミット
```

### 公開リポジトリ 100 本(2026-09-24)

よく知られた 100 本(Python・JavaScript・Go・Rust)の既定のブランチで、根・`docs/`・`.github/` にある
README・CONTRIBUTING・環境構築の文書をすべて: 文書 236 本、読んだ命令 2,813 本、リポジトリと照合
したもの 470 件。

**50 本で調整し、50 本は 25 本ずつ 2 回に分けて取っておきました。** 取っておいた側では、それを見て
直す前の時点で **error は 14 件中 9 件が本物、warning は 12 件中 2 件が本物**。偽物は、チュートリアルの
`python hello.py`(ファイルはすぐ上のブロック)、「変更したパッケージのディレクトリで」の `pnpm test`、
`make` の振る舞いを見せる README の `make test`、手順の箇条書きで名指しされた `/docs`、
`uv init awesome-project` の後の `cd awesome-project`、`EUPL-1.2` というライセンスの行から読んだ Rust の版、
プラグインが足す `yarn stage` などです。どれも直して試験を足しました。その後の 100 本では
**指摘 30 件のうち 22 件が本物**(error は 17 件中 15 件、warning は 13 件中 7 件)。この 2 つ目の数は、
その時点では中身を見てしまったリポジトリでの数なので、取っておいた側の測定ではありません。

本物(2026-09-24 に各ファイルで読んで確かめた):

| リポジトリ | 文書 | 文書が言うこと | リポジトリが言うこと |
|---|---|---|---|
| sharkdp/bat | README.md:430(と doc/README-ja.md) | 「Rust 1.79.0 以上が要る」 | `rust-version = "1.88"` —— Cargo は古いコンパイラを断る |
| sharkdp/hyperfine | README.md:308 | 「Rust 1.76 以降を使うこと」 | `rust-version = "1.88.0"` |
| sharkdp/hexyl | README.md:148 | 「Rust 1.56 以上があれば」 | `rust-version` 1.88 |
| Textualize/rich | README.md:42(と README.tr.md は 3.6.3) | 「Python 3.8 以降が要る」 | `python = ">=3.9.0"` |
| moment/luxon | docs/install.md:26・CONTRIBUTING.md | 「Node.js 6+ に対応」「Node 10 を入れた前提で」`npm run docs`・`npm run check-doc-coverage` | `engines.node >=12`。スクリプトは `api-docs`。`check-doc-coverage` は無い |
| nodejs/undici | CONTRIBUTING.md:197 | `cd docs && npm i && npm run serve` | `docs/` に `package.json` が無いので npm は根のものを使い、そこにある `serve:website` は「Documentation has been moved to '/docs'」と言って終わる |
| tiangolo/typer | docs/contributing.md:40 | `uv pip install -r requirements.txt`(リポジトリを `/code` に載せる開発用コンテナの中で) | 根に `requirements.txt` が無い |
| ajv-validator/ajv | CONTRIBUTING.md:168 | `npm run watch` | `watch` スクリプトが無い |
| date-fns/date-fns | CONTRIBUTING.md:113 | `./scripts/build/package.sh` | 実物は `pkgs/core/scripts/build/package.sh` |
| golang-migrate/migrate | CONTRIBUTING.md:5 | 「例: Go 1.11+」 | `go 1.25.11` |
| cli/cli | docs/install_source.md:3・.github/CONTRIBUTING.md | 「Go 1.26+」 | `go 1.27.0`(warning: `GOTOOLCHAIN=local` でなければ Go 1.26 は 1.27 を自分で取ってくる) |
| drizzle-team/drizzle-orm | CONTRIBUTING.md:58 | `nvm install 18.13.0` | `.nvmrc` は `22` |

**その 100 本でまだ偽物のもの:** `make bin/gh`(cli/cli の規則は変数入りの `bin/gh$(EXE):`)、
「`node --test`(Node 20+)」を要件と読んだもの(undici)、中のファイルのパスでしか名指しされない
「各ディレクトリで」走らせる astro のテスト、パッケージのディレクトリで打つ pnpm の `pnpm test`、
他の道具の振る舞いを見せる `just` の説明書の例 3 つ。

---

## 限界

- **Markdown だけ。** `readme.txt`・reStructuredText・AsciiDoc は読みません。
- **名前であって意味ではない。** 存在するが違うスクリプト、Gradle・Cargo・Go のタスクやテストの名前、
  フラグ、環境変数、ポート —— どれも照合しません。パス引数を読むのは上に挙げた命令だけです
  (`grep x file`・`rm -rf dir` は読まない)。
- yarn / pnpm のワークスペース: `--workspace` / `--filter` は追いません。Yarn のプラグインと実行ファイルは
  導入しないと分からないので `SCRIPT?` にします。
- Make: `$(eval ...)` で作る規則や変数で名付けた規則は見えません(その Makefile は「不完全」とし、無いものは
  warning)。`just`・`task`・`mise` のレシピは読みません。
- フォルダの推測(上)は、取りこぼしと引き換えに黙ります: 前のブロックの続きとしては誤りでも、根で読めば
  正しいブロックは報告しません。
- 試験 89 本。`mutation_check.py` は検査器を 54 通りに壊し、54 通りとも捕まります。**最初の 32 通りの
  初回は 24 通り**。残り 8 通りのうち 1 つは冗長な 1 行を壊す等価な変異だったので行ごと消し、7 つには試験を
  足しました。後の直しと一緒に足した 22 通りは直した後に書いたもので、うち 4 通りは初め生き残りました
  —— 試験の組み方のせいで壊した行に届いていなかった(前に作ったフォルダへの `cd`、同じ文書の前のほうで
  展開したアーカイブ)。3 通りは、後の直しが壊す先の行を変えたので書き直しました。

**English: [README.md](README.md)**

# migration-collision-check —— どちらのブランチも検査を通る。合流すると V24 が 2 本になる

2 人が `main` から枝を切り、それぞれ次の DB マイグレーションを足し、それぞれ次の番号を選びます。
片方は `V24__add_is_platform_creator.sql`、もう片方は `V24__compete_solve_log_unique_constraint.sql`。
どちらのブランチも緑です。2 本目が合流したあと、Flyway は起動しません。Django なら同じ事故は、
どちらも `0238` に依存する `0239_*.py` が 2 本 ——「Conflicting migrations detected; multiple leaf
nodes in the migration graph」—— で、Alembic なら `down_revision` が同じリビジョンが 2 本で、
`alembic upgrade head` が複数の head で止まります。

衝突はどちらのブランチにも存在しません。合流したものにだけ存在します。だからブランチの上で
走る検査には見えず、最初に表に出るのは合流後の基底のブランチか、デプロイです。

`migration_check.py` は **Flyway・Django・Alembic・Rails(Active Record)・golang-migrate** の
マイグレーションのファイルを読み、それぞれの道具が何かを実行する前に自分で尋ねる問いを、
ファイルの組に尋ねます。`--base` を付けると、まず合流が作る木 —— 基底のブランチに、2 本が
分かれてからこのブランチが足したものを加えた木 —— を組み立て、**このブランチが持ち込む
ものだけ**を報告します。

```bash
python migration_check.py path/to/repo                      # いまの木
python migration_check.py path/to/repo --base origin/main   # HEAD を origin/main に合流したときの木
python migration_check.py path/to/repo --explain            # 見つけた組と、読めなかったファイルも出す
```

`main` が分岐のあとに `V2__theirs.sql` を足し、このブランチが `V2__mine.sql` を足した場合:

```
$ python migration_check.py .
1 migration sets (flyway 1), 2 migration files read; 0 errors, 0 warnings
$ echo $?
0
$ python migration_check.py . --base main
db/migration/V2__mine.sql:1: error DUP Flyway version 2 is also used by db/migration/V2__theirs.sql (Flyway stops: more than one migration with this version)
1 migration sets (flyway 1), 3 migration files read, 1 files added by HEAD since d203f0da5d split from main, 0 finding(s) already on the base not shown; 1 errors, 0 warnings
$ echo $?
1
```

標準ライブラリのみ。ファイルを読むだけで(`--base` のときは `git` にファイルの一覧と中身を
尋ねます)、マイグレーションを実行せず、DB も要らず、何も書かず、どこにも送りません
(GitHub から読むのは下の `replay_fixes.py` だけです)。最後の行は、読んだ組とファイルの数を
必ず言います。知っている組が 1 つも無いリポジトリは、合格にせず終了コード 2 でそう言います。

---

## 何を報告するか

| 記号 | 水準 | 道具 | 意味 |
|---|---|---|---|
| `DUP` | error | Flyway | 1 つの場所に同じ版のマイグレーションが 2 本。版は Flyway と同じに読みます: `_` は `.`、各部分は数、末尾の 0 は落とす —— `1_1`・`1.1`・`1.01` は同じ版、`2.0` は `2`。同じクラスパスの場所にある SQL と Java/Kotlin のクラス(`src/main/resources/db/migration` と `src/main/java/db/migration`)は 1 組です。 |
| `DUP` | error | golang-migrate | 1 つのフォルダに同じ版の up(または down)が 2 本(`011` と `11` は同じ版)。gobuffalo/pop の名前(`<版>_<名前>.<方言>[.autocommit].up.sql`)は方言ごとに分け、1 つの方言用のファイルと全方言用のファイルは衝突とみなしません。`go.mod` が名前全体で並べる maragudk/migrate を要求していれば、同じ番号は警告(`DUP?`)にします。 |
| `DUP` / `DUPNAME` | error | Rails | 同じ版、または同じ名前のマイグレーションが 2 本(`DuplicateMigrationVersionError` / `DuplicateMigrationNameError`)。`db/migrate` は Rails が `**/[0-9]*_*.rb` で拾うとおり下のフォルダまで読み、2 つ目の DB の `db/<名前>_migrate` は別の組です。 |
| `CONFLICT` | error | Django | 葉(leaf)のマイグレーションが 2 本以上あるアプリ。番号は関係なく(連なっていれば `0005_*` が 2 本でもよい)、見るのはグラフです。同じアプリへの依存は辺、`run_before` は逆向きの辺、squash したマイグレーションは `replaces` の名前すべての代わりに立ちます(その名前のファイルが残っていても消えていても)。`__first__` / `__latest__` は数えません。アプリのラベルは `apps.py` の `AppConfig.label`、無ければフォルダ名。`__init__.py` の無い `migrations/` は Django が読まないので読まず、`Migration` という名前のクラスも基底が `…Migration` のときだけ数えます。 |
| `HEADS` | error | Alembic | 1 本の鎖に head が 2 つ以上(`alembic upgrade head` が止まる)。鎖は `down_revision` だけで繋ぎ(`depends_on` は使わない)、1 つのスクリプトのフォルダ(`env.py` のある一番近いフォルダ)の中で見ます。`versions/` の下の DB の名前のフォルダ(`postgresql/`・`sqlite/`)はそれぞれ別の鎖です。根が別なら別の鎖です。 |
| `MISSING` | error | Django・Alembic | アプリにも、どの `replaces` にも無いマイグレーションへの依存(Django は `NodeNotFoundError`)。どのリビジョンのファイルにも無い `down_revision`。リポジトリに無いアプリ(`auth`・外部パッケージ)への依存は見ません。 |
| `DUPREV` | error | Alembic | 1 つのリビジョン ID が 2 つのファイルに。Alembic は警告だけ出して片方を使います。 |
| `ORDER` | error | Flyway・golang-migrate | `--base` のときだけ。このブランチが、基底がもう持っている版より小さい番号を足した。Flyway は大きいほうを適用済みの DB でこれを拒みます(`outOfOrder` の既定は false。設定ファイルが有効にしていれば `ORDER` は見ず、最後の行にどのファイルかを書きます)。golang-migrate は、いまの版より小さい版を**黙って**適用しません。 |
| `DUP?` | warning | Flyway | 1 つの `migration` フォルダの下の兄弟フォルダで同じ版(`db/migration/control/V1__…` と `db/migration/tenant/V1__…`)。Flyway の場所が親なら(下のフォルダまで読むので)衝突、フォルダごとに別の場所なら衝突ではない —— ファイルからはどちらか分かりません。DB の名前のフォルダ(`mysql/`・`postgresql/`・`h2/` …)はそれぞれ別の場所とみなして報告しません。親フォルダごとに 1 行。 |
| `DUP?` | warning | Rails | エンジン(`.gemspec` のあるフォルダ)の中で同じ版。`install:migrations` は写すたびに新しい版を振るので、止まるのはエンジンのフォルダを自分の経路に足したアプリだけ。エンジンの中の同じ**名前**は error のまま —— 写すときに 2 本目が飛ばされます。 |
| `HEADS?` | warning | Alembic | `branch_labels` を使っている鎖で head が複数: わざとかもしれない。 |
| `SCHEMA` | warning | Rails | `db/schema.rb` の版より新しいマイグレーションがある: その後にスキーマの書き出しが更新されていない。 |

`fixtures`・`testdata`・`__fixtures__`・`test_fixtures` という名前のフォルダは外します(試験は壊れた
組をわざと持つため)。外した数は最後の行が数えます。この Python で構文解析できないファイル
(Python 3.14 は `except A, B:` を許し、3.13 は読めない)は、同じ少しの名前だけを文字列として
読み直し、その数も最後の行が数えます。

**終了コード:** 0 = 誤りなし(警告は `--strict` でなければ失敗にしない)。1 = 誤りあり。2 = 組が
1 つも見つからない、または `git` が失敗した。

### CI で、プルリクエストごとに

```yaml
# .github/workflows/migrations.yml
on: pull_request
jobs:
  migrations:
    runs-on: ubuntu-latest
    steps:
      - uses: actions/checkout@v4
        with: { fetch-depth: 0 }          # --base は分岐点を探すので履歴が要る
      - run: curl -fsSLO https://raw.githubusercontent.com/samuboon/claude-code-harness/main/migration-collision-check/migration_check.py
      - run: python3 migration_check.py . --base origin/${{ github.base_ref }}
```

**私たちは GitHub の上でこれを走らせていません。**`--base` の経路は、2 本のブランチを持つ
リポジトリを作る試験で確かめたもので、実際のプルリクエストで確かめたものではありません。
(ワークフローを `.github/workflows/` ではなくここに置いているのは、このフォルダを公開する鍵に
workflow の権限が無いからです。)

---

## 実測

### 衝突を直したコミットを再生した(`replay_fixes.py`)

直した人が使う言葉 ——「multiple leaf nodes」「merge migrations」「alembic merge heads」「duplicate
Flyway migration version」「rename Flyway migration conflict」「duplicate migration version rails」
「renumber duplicate migration」—— で GitHub のコミット検索をかけ、公開のコミット 106 本を
得ました。1 本ずつ、コミットの直前の木とコミットの木で検査器を走らせました。GitHub が配る
tarball から読み、メモリの上だけで扱い、展開はしていません。

**調整を始める前に 2 つに分けました: 調整に使う 53 本と、取っておく 53 本。**

| | 調整側(53) | 取っておいた側(53)—— 中を見る前の最初の 1 回 |
|---|---:|---:|
| 直す前に印(error)が付き、直した後に消えた | 49 | **46** |
| 警告としてだけ付いた | 1 | 1 |
| 付かなかった | 3 | 6 |
| 再生した木の上の、本物でない指摘 | — | 10、ほかに手で確かめていないもの 2(1 つのリポジトリが Alembic のリビジョン 10 本の写しを `versions/` の外に置いていた) |

取っておいた側を見て直したあと、106 本すべてをもう一度: **95 本が直す前に印が付き、直した後に
消えた** —— Django 26 本中 25・Alembic 16 本中 14・Flyway 36 本中 30・Rails 7 本中 7・golang-migrate
21 本中 19。ほかに警告だけが 2 本、付かなかったのが 9 本。(この 2 つ目の数は、もう取っておいた側の
測定ではありません。)途中で 1 つ、直しが逆向きに効きました:「golang-migrate を要求しない `go.mod`」を
「別の道具」と読んだら、この再生で本物の golang-migrate の衝突 7 本が警告に落ちたので、外しました。

- **調整側で捕まえたもの:** Django の分岐(`0238` にどちらも依存する `0239_servercargoarrivedlog_delivery_id`
  と `0239_worldobject_tag_notes`)、Alembic の 2 つ・3 つの head、Flyway の `V24` が 2 本・`V30` が
  2 本・`V100`〜`V102` が 3 組・`V1.0.34` が 2 本・`V42_2` が 2 本、Rails の `20260828000001` が 2 本、
  golang-migrate の `055`・`000118`・`085` が各 2 本。
- **付かなかった 9 本の理由。****6 本は、もう片方のブランチをよけるための改名でした** —— コミットの
  文がそう書いている(「to avoid Flyway conflict」「develop のブランチが 0069〜0071 をもう使っていた」)か、
  基底と合流させると分かる —— そして直す前の木には、もう片方のブランチのファイルが入っていません。
  調整側では 53 本中 3 本が、衝突の相手がもう片方のブランチにあり、直す前の
  木にはそもそも入っていませんでした(msdnna/tessera: 相手のブランチが `0069`〜`0071` をもう使っていた。
  narindra20/projectAsync: 順序の外れを直す改名。nachoechave/comercio-flex)。これが `--base` の仕事です。
  comercio-flex は、直す前のブランチを、そのプルリクエストが合流する直前の基底に合流させると
  (`--against pr`)`V020` の `DUP` が出ます。残り 2 本は公開の情報から基底を組み立て直せませんでした
  (見つかったプルリクエストが後のリリースの合流だった・プルリクエストが無かった)。もう 1 本は
  `DUP?` の警告としてだけ捕まえました(anjanx44/Bazario: 1 つの `db/migration` の下の兄弟フォルダ 4 つで
  `V1`。本物の衝突として直されていた)。取っておいた側では、さらに 3 本がよけるための改名
  (thangnq090/evchargingplatform の `V202` を `V502` に、tenant-hub の `V8` を `V19` に、
  tobi-techy/RAIL-BACKEND-SERVICE を `300` に)、3 本は説明がつきません: SentenciaSQL/animalin(直す前の
  木に `V3` は 1 本だけ)、vortex-tecnologia/rxtrack(コミットが合わせた分岐が木に無い。足した合流の
  マイグレーションは `0039_merge_20260619_1029` に依存するが、そのコミットの時点でリポジトリに無い ——
  本物の `MISSING` で、GitHub の上で確かめた)、hussu97/mm-ecommerce(コミットはリビジョンを
  `251_noon_commission_incl` の上に付け替えるが、その時点でそれを宣言するリビジョンのファイルが無い ——
  `MISSING` として印を付けたが、手では確かめていない)。もう 1 本は警告だけでした
  (hassan-mohagheghian/job-flow: `versions/` と `processing/versions/` にまたがる 2 つの head。
  `branch_labels` を使っている)。
- **直したコミットが別の衝突を残した・作ったもの:** Tayebbb/TurfChai は `V8` を `V11` に改名した先に
  既に `V11__ml_pricing_tables.sql` があった。cscpratapnagar-ai は 1 つの版を直して `V24`・`V25`・`V36` の
  重複を残し、`V23` を 2 本にした。formalizese-hub は `V49` を 2 本残した。検査器はそのコミット自身に
  印を付けます(そのコミットの時点のファイルから読んだもの)。
- **この検査は手で書かれています。**同じ検索で、それを足すコミットが出てきます:「2 本の Flyway の
  スクリプトが同じ版なら落ちる試験を足す」(SentenciaSQL/animalin)、「2 本のマイグレーションが同じ版を
  名乗ったら `lint` で落とす」(tadasant/zimmer)、「flyway-duplicate-version-guard」(workin-hr)、
  「migration version collision guard」(evo-crm-community)、「CI の single-head guard」
  (SaifulHaqueNiloy/supremeai)。どれも 1 本の木を見ます。

```bash
python replay_fixes.py                                   # 106 本
python replay_fixes.py owner/name@SHA                    # 他の公開コミット
python replay_fixes.py owner/name@SHA --against pr       # 親を、そのプルリクエストの基底に合流させた木も見る
python replay_fixes.py --search "duplicate migration"    # コミット検索から候補(API 1 回)
python replay_fixes.py --head owner/name                 # 今日の既定のブランチ
```

### 公開リポジトリ 99 本の今日

マイグレーションを持つよく知られたリポジトリ —— Django 30・Alembic 17・Flyway 14・Rails 24・
golang-migrate の形 14 —— の既定のブランチ(2026-09-24)。**同じく 50 本で調整し、49 本を取って
おきました。**指摘はすべて、そのファイルを読んで確かめました。

| | 調整側(50) | 取っておいた側(49)—— 中を見る前の最初の 1 回 |
|---|---:|---:|
| 組を読めたリポジトリ | 46 | 43 |
| error | 10 リポジトリに 42 件 | **3 リポジトリに 34 件** |
| そのうち本物 | 0 | **0** |

毎日本番で動いている既定のブランチなら、本物の error は稀のはずで、実際に 1 件もありませんでした。
error はすべて、検査器がフォルダの形を読み違えたものです。調整側では: 置き換えたファイルを消した
squash(kitsune・paperless-ngx・cvat)、Python 3.14 の構文(`except A, B:`。kitsune と readthedocs)、
`dependencies = [...] + settings.X`(django-helpdesk)、試験の置き物(discourse・golang-migrate)、pop の
`.autocommit`(ory/kratos)、Rails のエンジンの中の同じ版(spree・decidim)。取っておいた側では:
`migrations/` パッケージにある PostHog 独自の非同期マイグレーションのクラス、Prefect が
`versions/postgresql` と `versions/sqlite` に分けて持つ別々の鎖、Harness の `0001_create_table_a` …
`0001_create_table_c`(その道具 maragudk/migrate は名前全体で並べる)。

直したあと 99 本すべて: **error 0 件**。89 リポジトリで 741 組・34,003 本のマイグレーションを読みました
(8 本は知っている組が無く、2 本は読めず: 400 MB を超える tarball と、解決できなかった 1 本)。警告は
3 リポジトリに 40 件で、どれも本物の衝突ではありません: spree 13 件と decidim 2 件(エンジン)、
Harness 25 件(maragudk/migrate)。

---

## 限界

- **ファイル名と、そこに書かれた少しの値だけ。**SQL は読まず、DB がどのマイグレーションを適用
  済みかも知らず、各道具自身の検証も走らせません。`flyway validate`・`manage.py makemigrations --check`・
  `alembic heads`・`rails db:migrate:status` は 1 本の木の上ではこれより多くを見ます。できないのは、
  まだ起きていない合流を見ることです。
- **Flyway の場所はフォルダの形から推します。**`spring.flyway.locations` も
  `Flyway.configure().locations(...)` も読みません。兄弟フォルダが警告なのはそのためです。
  接頭辞(`sqlMigrationPrefix`)や区切りの設定も読まず、`V` と `__` を前提にします。
- **Django:** ラベルは `apps.py` を読み込まずに型で読み、依存は値の中の文字列の `(アプリ, 名前)` の
  組をすべて取ります(`[...] + settings.X` でも文字列の部分は読む)。`MIGRATION_MODULES` は読み
  ません。squash は置き換えたものの代わりに立つと仮定します —— DB の上でそれらが 1 本も、または
  全部が適用済みのときに正しい仮定です。
- **Alembic:** リビジョンのファイルは、`versions/` フォルダの下か、`alembic.ini` の `version_locations` が
  名指すフォルダの下の `.py` だけ。`env.py` や `pyproject.toml` でだけ設定した場所は見つけません。
  `versions/` の下の DB の名前のフォルダは別の鎖です。`revision` / `down_revision` は文字列の値だけ
  読みます。
- **golang-migrate:** 同じ名前を、名前全体で並べる道具も使います。見分けるのは `go.mod` にある
  maragudk/migrate だけで、そのときは同じ番号を警告にします。
- **`--base`** は、このブランチが編集したファイルはこのブランチから、それ以外は基底から読みます。
  中身の 3 方向の合流はしません。
- 試験 88 本。`mutation_check.py` は検査器を 62 通りに壊し、62 通りとも捕まります。**最初の 42 通りの
  初回は 41 通り**: 2 つの Alembic のスクリプトのフォルダを 1 つと読む壊し方が生き残りました。1 つの環境の
  版のフォルダをまたぐ分岐の試験が無かったためで、その試験を足しました。残り 20 通りは後の直しと一緒に
  書いたものです。

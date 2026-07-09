
## 推奨する画面構成

```text
Chat
  - Chat

Schedule
  - All Tasks
  - New Task
  - History
```


| 画面        | 役割                       |
| --------- | ------------------------ |
| Chat      | 通常の対話実行                  |
| All Tasks | 登録済みタスク一覧、ON/OFF、手動実行、編集 |
| Schedule  | 新規タスク作成・スケジュール設定         |
| History   | 実行履歴、成功/失敗、出力確認          |


## 任意プロンプト方式のタスク作成画面

タスク作成画面は、最初はこれだけでよいです。

```text
タスク名
実行タイミング
Agent Profile
プロンプト
有効 / 無効
手動実行
保存
```

具体例です。

```text
タスク名:
  第1工場 朝会用レポート

実行タイミング:
  毎日 08:00

Agent Profile ID: 
xx

Agent Profile Name:
  製造業務エージェント

プロンプト:
  {{yesterday}} の第1工場の生産実績を確認してください。
  計画未達のライン、不良率が悪化した工程、設備停止があればまとめてください。
  最後に朝会で共有しやすい形式で、重要度順にMarkdownで出力してください。

有効:
  ON
```

この方式なら、タスク種別を作らなくても、ユーザが自由に業務を定義できます。


## この方式でのAgent連携

Chat と Schedule の違いは、**AgentRunner に渡す入力文の作り方だけ**です。

```text
Chat:
  ユーザがその場で入力した文章
    ↓
  AgentRunner

Schedule:
  tasks.prompt_template を日付変数で展開した文章
    ↓
  AgentRunner
```

つまり、Agent側はほぼ共通です。

```python
RunAgentInput(
    messages=[
        {
            "role": "user",
            "content": input_text,
        }
    ],
    agent_profile_id=agent_profile_id,
    source="task",
    run_id=run_id,
)
```

Chat UI では `input_text` がユーザ入力です。Schedule では `input_text` がタスク定義から作られた文章です。


## DB設計もよりシンプルになる

タスク種別をなくすなら、`tasks` はかなり単純になります。

```sql
create table tasks (
    id text primary key,
    name text not null,

    enabled integer not null default 1,

    schedule_type text not null,       -- daily / weekly / interval / manual
    schedule_value text not null,      -- 08:00 / mon 08:00 / 60m / none
    next_run_at text,

    agent_profile_id text not null,

    prompt_template text not null,

    last_status text,
    last_run_at text,
    last_error text,

    created_at text not null,
    updated_at text not null
);
```

実行履歴はこれで十分です。

```sql
create table runs (
    id text primary key,
    task_id text,

    status text not null,              -- pending / running / succeeded / failed / skipped
    source text not null,              -- schedule / manual / chat

    input_text text not null,
    output_text text,
    error_text text,

    started_at text,
    finished_at text,
    created_at text not null,

    foreign key (task_id) references tasks(id)
);
```

重要なのは、`tasks.prompt_template` と `runs.input_text` を分けることです。

`tasks.prompt_template` は毎回使うテンプレートです。`runs.input_text` は、実行時点で `{{yesterday}}` などを実日付に置換した完成済み入力です。

## 変数だけは用意したほうがよい

任意プロンプト方式でも、日付変数は最低限必要です。これがないと、毎日実行するタスクで「昨日」「今週」「先週」の扱いが曖昧になります。

最初はこれだけでよいです。

```text
{{today}}
{{yesterday}}
{{this_week_start}}
{{this_week_end}}
{{last_week_start}}
{{last_week_end}}
```

ユーザは任意プロンプトの中でこう書きます。

```text
{{yesterday}} の製造実績を確認してください。
```

実行時にこうなります。

```text
2026-07-08 の製造実績を確認してください。
```

この変換後の文章を `runs.input_text` に保存します。あとから履歴を見たときに、「実際にAIへ何を依頼したのか」が分かります。

## Schedule画面の作成フロー

任意プロンプト方式では、ユーザ導線はこうなります。

```text
1. Schedule > New Task を開く
2. タスク名を入力する
3. 実行タイミングを選ぶ
4. Agent Profile を選ぶ
5. 任意プロンプトを書く
6. 手動実行する
7. 結果を確認する
8. 保存して有効化する
```

この中で一番大事なのは **手動実行** です。

任意プロンプトは自由度が高い反面、実行してみないと意図通りに動くか分かりません。なので、保存前に1回だけ実行して結果確認できるようにするべきです。

手動実行時も、裏側では `runs` に1件作ればよいです。

```text
source = manual
status = pending
input_text = 変数展開済みプロンプト
```

その後、Worker が通常タスクと同じように実行します。

## SchedulerとWorkerの流れ

全体の動きはこうです。

```text
APScheduler
  1分ごとに tasks を見る
    ↓
  next_run_at <= now のタスクを探す
    ↓
  prompt_template を変数展開する
    ↓
  runs に pending を作る
    ↓
  tasks.next_run_at を次回時刻に更新

Worker
  pending の run を1件拾う
    ↓
  runs.input_text を AgentRunner に渡す
    ↓
  結果を runs.output_text に保存する
```

コードのイメージです。

```python
def create_run_from_task(task: dict) -> None:
    input_text = render_prompt(
        template=task["prompt_template"],
        base_date=today_jst(),
    )

    db.execute(
        """
        insert into runs (
            id,
            task_id,
            status,
            source,
            input_text,
            created_at
        )
        values (?, ?, 'pending', 'schedule', ?, ?)
        """,
        [
            new_id(),
            task["id"],
            input_text,
            now_iso(),
        ],
    )
```

Worker 側です。

```python
def execute_run(run: dict) -> None:
    task = db.fetch_one(
        "select * from tasks where id = ?",
        [run["task_id"]],
    )

    db.execute(
        """
        update runs
        set status = 'running',
            started_at = ?
        where id = ?
        """,
        [now_iso(), run["id"]],
    )

    try:
        result = agent_runner.run(
            RunAgentInput(
                messages=[
                    {
                        "role": "user",
                        "content": run["input_text"],
                    }
                ],
                agent_profile_id=task["agent_profile_id"],
                source="task",
                run_id=run["id"],
            )
        )

        db.execute(
            """
            update runs
            set status = 'succeeded',
                output_text = ?,
                finished_at = ?
            where id = ?
            """,
            [result.final_text, now_iso(), run["id"]],
        )

    except Exception as e:
        db.execute(
            """
            update runs
            set status = 'failed',
                error_text = ?,
                finished_at = ?
            where id = ?
            """,
            [str(e), now_iso(), run["id"]],
        )
```

## All Tasks 画面

`All Tasks` は一覧と運用操作の画面です。

表示項目はこれくらいでよいです。

```text
タスク名
有効/無効
スケジュール
次回実行
最終実行
最終結果
手動実行
編集
削除
```

ここではタスクの中身を細かく表示しすぎなくてよいです。詳細を開いたら、プロンプトや履歴が見える形で十分です。

## History 画面

`History` は `runs` の一覧です。

```text
実行日時
タスク名
実行元
ステータス
入力
出力
エラー
```

ここで `input_text` を見られるようにしておくと、トラブル時にかなり助かります。

例えば「今日の結果がおかしい」と言われたら、開発者や管理者はまず `runs.input_text` を見ます。

```text
AIに渡した入力が悪いのか
AgentやToolの動作が悪いのか
参照データが悪いのか
```

この切り分けができます。

## Chatとの関係

Chat は「その場の相談」、Schedule は「定型処理」です。

```text
Chat:
  今すぐ聞きたいことを聞く
  結果について追加質問する
  プロンプトの書き方を相談する

Schedule:
  定期的に実行する処理を登録する
  実行履歴を見る
  手動再実行する
```

たとえば、Schedule で作った結果を History で開いて、その出力について Chat に投げる機能は便利です。

```text
この実行結果について質問する
```

このボタンを押すと、Chat に `runs.output_text` をコンテキストとして渡します。

## 最終案

今回の前提なら、最適案はこれです。

```text
タスク種別は作らない
任意プロンプト方式にする
タスク名はユーザが設定する
日付変数だけ用意する
保存前に手動実行できるようにする
AgentRunner は Chat と Schedule で共通化する
DB は tasks / runs の2テーブルから始める
```

この方式が一番シンプルです。UIも狭い業務テンプレートに縛られず、製造業以外の定型業務にもそのまま広げられます。開発者にとっても、タスク種別ごとのUIや分岐を作らなくて済むので、実装・保守・トラブル調査がかなり楽になります。



はい、その理解でかなり合っています。**20人程度が使う社内向けシステムで、書き込み頻度が高くなく、トランザクションを短く保てるなら SQLite で十分成立する可能性が高い**です。

ただし、重要なのは、**トランザクションを入れれば同時書き込みできるようになるわけではない**という点です。SQLite は基本的に「同時に書けるのは1つの書き込みトランザクションだけ」です。公式ドキュメントでも、同時に存在できる書き込みトランザクションは1つだけと説明されています。([SQLite][1])

なので正確にはこうです。

```text id="9ecfsr"
誤解:
  トランザクションを入れると複数人が同時に書ける

正しい理解:
  SQLiteは同時書き込みを1つずつ順番に処理する
  ただし、1回の書き込みが短ければ20人程度なら十分回る
```

## 20人程度なら問題になりにくい理由

あなたの用途だと、20人が同時に使っても、多くの操作は読み取りです。

```text id="wh52jf"
読み取り:
  タスク一覧を見る
  Historyを見る
  実行結果を見る
  Chat画面を見る

書き込み:
  タスクを作る
  タスクを編集する
  手動実行する
  Workerがrunsを書き換える
```

20人が全員、毎秒何十回も書き込むわけではないなら、SQLiteで十分現実的です。SQLite公式も、SQLiteは1つのDBファイルにつき同時writerは1つだが、多くの場合write transactionはミリ秒単位で終わるため、複数writerは順番に処理できる、と説明しています。([SQLite][2])

今回のような社内向けAIエージェントであれば、主な書き込みはこの程度です。

```text id="7grqxu"
ユーザ:
  task作成・編集
  手動実行ボタン
  タスクON/OFF

Worker:
  pending → running
  running → succeeded / failed
```

このくらいなら、トランザクションを短く保てば問題になりにくいです。

## トランザクションで重要なこと

大事なのは、**Agentの実行中にトランザクションを開きっぱなしにしない**ことです。

これは避けるべきです。

```python id="4x73cn"
# 悪い例
with transaction():
    update_run_status("running")

    # ここでLLM呼び出し、Tool実行、ファイル処理をする
    result = agent_runner.run(input_)

    update_run_result(result)
```

この書き方だと、Agent実行中ずっとDBの書き込みトランザクションを握る可能性があります。LLM呼び出しが10秒、30秒、1分かかると、その間ほかの書き込みが詰まりやすくなります。

正しくは、DB更新ごとに短く閉じます。

```python id="6oo2ei"
# 良い例

with transaction():
    update_run_status("running")

# DBトランザクション外でAgentを実行する
result = agent_runner.run(input_)

with transaction():
    update_run_result("succeeded", result.final_text)
```

つまり、SQLiteでやるなら原則はこれです。

```text id="d76bqc"
DBトランザクションは短くする
LLM呼び出し中はトランザクションを持たない
ファイル生成中もトランザクションを持たない
外部API呼び出し中もトランザクションを持たない
```

これを守れば、20人程度の利用ではかなり安定しやすいです。

## WAL + busy_timeout + 短いtransaction が現実解

SQLiteで社内向けにやるなら、基本設定はこれでよいです。

```sql id="mhf6j9"
PRAGMA journal_mode = WAL;
PRAGMA busy_timeout = 5000;
```

WALは、読み取りと書き込みを共存しやすくするモードです。SQLite公式でも、WALではreaderがwriterをブロックせず、writerもreaderをブロックしにくくなり、読み取りと書き込みが並行しやすいと説明されています。([SQLite][3])

`busy_timeout` は、他の書き込み中でDBが一時的にロックされていた場合に、すぐエラーにせず一定時間待つ設定です。SQLiteのbusy handler / busy timeoutは、ロック中のDBアクセスで呼ばれる仕組みとして説明されています。([SQLite][4])

Pythonならこうです。

```python id="9oju11"
import sqlite3

def connect_db(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    return conn
```

## 今回の設計なら、かなりSQLite向き

あなたの構成はSQLite向きです。

```text id="msy7yd"
FastAPI:
  UI操作、タスク作成、履歴閲覧

Scheduler:
  1分ごとに due task を確認

Worker:
  pending run を1件ずつ実行

DB:
  tasks / runs
```

特に、**Workerを1本にする**なら、書き込み競合はかなり減ります。Workerが複数いないので、`runs` を同時に取り合う問題も起きにくいです。

ユーザ20人が同時に使っても、多くは読み取りで、書き込みはたまに発生する程度です。であれば、PostgreSQLを最初から入れるより、SQLiteで始める判断は十分ありです。

## 注意すべきケース

SQLiteで問題になりやすいのは、こういうケースです。

```text id="4prk29"
複数Workerを動かす
Web APIを複数プロセスで大量起動する
1回のDB書き込みトランザクションが長い
runs.output_text に巨大データを書き続ける
History検索で全件スキャンする
ユーザが頻繁に一括更新する
```

特に危ないのは、**長いトランザクション**です。SQLiteの弱点は「同時書き込みが1つ」という点なので、1回の書き込みが長いと詰まりやすくなります。

逆に言うと、1回の書き込みを短くすれば問題になりにくいです。

## 実装方針

最初の実装では、これでよいと思います。

```text id="x7tveo"
SQLite + WAL
busy_timeout = 5000
Workerは1本
DB transactionは短くする
Agent実行中はtransactionを開かない
Historyは必ずlimit付き
巨大成果物はartifact_pathに逃がす
```

`runs` の更新も、この程度の短いSQLにします。

```python id="6ksc93"
def mark_running(run_id: str) -> None:
    with transaction():
        db.execute(
            """
            update runs
            set status = 'running',
                started_at = ?
            where id = ?
            """,
            [now_iso(), run_id],
        )
```

```python id="cb5yn7"
def mark_succeeded(run_id: str, output_text: str) -> None:
    with transaction():
        db.execute(
            """
            update runs
            set status = 'succeeded',
                output_text = ?,
                finished_at = ?
            where id = ?
            """,
            [output_text, now_iso(), run_id],
        )
```

これなら1回の書き込みはかなり短いです。

## 結論

**20人程度の社内利用で、性能を極端に求めないなら、SQLiteで問題ない可能性は高い**です。特にあなたのように、Workerを1本にして、タスク実行を順番に処理する設計なら相性はよいです。

ただし、トランザクションは「同時書き込みを可能にするもの」ではなく、**短い単位で安全に書き込むためのもの**と考えたほうがよいです。SQLiteは同時書き込みを1つずつ処理するので、1回の書き込みを短くして、WALとbusy_timeoutを使えば、20人規模の初期製品としては十分現実的です。

[1]: https://sqlite.org/lang_transaction.html?utm_source=chatgpt.com "Transaction"
[2]: https://sqlite.org/whentouse.html?utm_source=chatgpt.com "Appropriate Uses For SQLite"
[3]: https://sqlite.org/wal.html?utm_source=chatgpt.com "Write-Ahead Logging"
[4]: https://www.sqlite.org/c3ref/busy_handler.html?utm_source=chatgpt.com "Register A Callback To Handle SQLITE_BUSY Errors"


------

はい、**十分実用的な構成にできます**。むしろ今回のような「社内向け・20人程度・単一サーバ・SQLite・AIエージェント実行」という前提なら、**SQLiteを用途別に2〜3個に分ける設計はかなり現実的**です。

ただし、分け方の目的は「性能を劇的に上げる」よりも、**責務分離・バックアップしやすさ・障害時の切り分け・書き込み競合の分散**です。SQLiteは1つのDBファイルにつき同時writerは1つですが、write transactionが短ければ複数writerは順番に処理できます。SQLite公式も、writerは1つずつだが、多くの場合write transactionは短く、複数writerが順番に処理される、と説明しています。([SQLite][1])

## 推奨構成

最初はこの3つくらいがよいです。

```text id="twb15w"
data/
  auth.db      -- ユーザ、ロール、セッション、権限
  agent.db     -- agent profile、tasks、runs
  audit.db     -- 監査ログ、操作ログ、実行ログの概要
```

この分け方はかなり自然です。

| DB         | 内容                     | 特徴         |
| ---------- | ---------------------- | ---------- |
| `auth.db`  | users, roles, sessions | 小さく、重要度が高い |
| `agent.db` | profiles, tasks, runs  | アプリ本体の状態   |
| `audit.db` | audit_logs             | 追記中心、増えやすい |

特に `audit.db` を分けるのは良いです。監査ログは基本的に追記中心で、件数も増えやすく、アプリ本体の `tasks/runs` とライフサイクルが違います。将来、古い監査ログだけ圧縮・退避・別保存する判断もしやすくなります。

## 何がよくなるか

複数SQLiteに分けるメリットは、主にこの4つです。

```text id="q3vf0g"
1. 関心ごとが分かれる
2. DBファイルごとにロックが分かれる
3. バックアップ・復旧の単位を分けられる
4. audit.db の肥大化が agent.db に影響しにくい
```

SQLiteのWALでは読み取りと書き込みが並行しやすくなります。公式ドキュメントでも、WALはreaderがwriterをブロックせず、writerもreaderをブロックしにくい、つまり読み書きが並行できると説明されています。([SQLite][2])

さらに、DBファイルを分けると、`audit.db` にログを書いている間でも、`agent.db` の読み書きとは別ファイルとして扱えます。SQLite公式も、別ドメインごとにSQLiteファイルを分ける、いわゆる database sharding によって同時接続を扱いやすくできる例を挙げています。([SQLite][1])

## ただし、分けすぎないほうがよい

最初から細かく分けすぎるのは避けたほうがよいです。

```text id="q52v72"
auth.db
profile.db
task.db
run.db
artifact.db
audit.db
settings.db
```

ここまで分けると、逆に管理が面倒になります。バックアップ、マイグレーション、接続管理、整合性確認が増えます。

最初は多くてもこの程度がよいです。

```text id="dxq668"
auth.db
agent.db
audit.db
```

`agent profile`、`tasks`、`runs` は最初は同じ `agent.db` に入れるほうがよいです。Profile と Task は関係が強いからです。

```text id="9s7y2y"
profiles
  ↓
tasks
  ↓
runs
```

これを別DBにすると、外部キー制約を素直に使いにくくなります。SQLiteでは `ATTACH DATABASE` を使えば複数DBを同じ接続から参照できますが、WALモードでは複数attached DBをまたぐトランザクションはDBごとにはatomicでも、全DBセットとしてのatomic性は保証されません。([SQLite][3])

なので、**強い整合性が必要なものは同じDBに置く**のが原則です。

## おすすめの分け方

あなたの構成なら、私はこうします。

```text id="bjy4o0"
auth.db
  users
  roles
  user_roles
  sessions

agent.db
  agent_profiles
  tasks
  runs
  artifacts  または artifact_path だけ

audit.db
  audit_logs
```

`agent_profiles` と `tasks` は同じ `agent.db` がよいです。

理由は、タスク実行時に必ず profile を参照するからです。

```text id="3sz034"
Task Worker
  runs.pending を取得
    ↓
  task を読む
    ↓
  agent_profile を読む
    ↓
  AgentRunner を実行
```

ここで `tasks` と `agent_profiles` が別DBだと、実装上はできますが、参照や整合性の確認が少し面倒になります。最初は同じDBでよいです。

一方、`audit_logs` は別DBでよいです。監査ログは基本的に「あとから見るための記録」であり、アプリ本体の実行に必須ではないからです。

## トランザクション設計の注意

複数SQLiteに分ける場合、**複数DBをまたぐ1つの完全なトランザクションに期待しない**ほうがよいです。

例えばこれは注意です。

```text id="e613iq"
agent.db:
  task を作成する

audit.db:
  「task作成」という監査ログを書く
```

この2つを「絶対に同時成功・同時失敗」にしたいなら、同じDBに入れるほうが単純です。WALモードでは、複数attached DBをまたぐcommit中にクラッシュすると、一部DBだけ反映される可能性があるとSQLite公式ドキュメントに書かれています。([SQLite][3])

ただ、実用上は次の割り切りで十分なことが多いです。

```text id="6g289y"
本体データの更新を優先する
  ↓
監査ログを書く
  ↓
監査ログ書き込みに失敗したらアプリログに残す
```

つまり、監査ログは「本体更新と完全に同一トランザクション」ではなく、**ベストエフォート + 失敗時にファイルログへ退避**くらいから始めるのが現実的です。

## 接続管理

DBごとに接続を分けます。

```python id="l0u4r9"
auth_conn = connect_sqlite("data/auth.db")
agent_conn = connect_sqlite("data/agent.db")
audit_conn = connect_sqlite("data/audit.db")
```

各DBでWALとbusy_timeoutを設定します。

```python id="6gcjl7"
def connect_sqlite(path: str) -> sqlite3.Connection:
    conn = sqlite3.connect(path, timeout=5)
    conn.execute("PRAGMA journal_mode = WAL")
    conn.execute("PRAGMA busy_timeout = 5000")
    conn.execute("PRAGMA foreign_keys = ON")
    return conn
```

WALは同じホスト上で使う前提です。SQLite公式は、WALはネットワークファイルシステムでは動作しない、同じホスト上のプロセスで使う必要があると説明しています。([SQLite][2]) SQLite公式は、データがアプリケーションと別マシンにあるならクライアント/サーバ型DBを検討するべきとも説明しています。([SQLite][4])

## この構成で実用になる条件

この条件なら、十分実用的です。

```text id="zf8fmz"
単一サーバ上で動かす
SQLiteファイルをNASや共有フォルダに置かない
Workerは最初は1本
トランザクションは短くする
LLM実行中にDBトランザクションを開きっぱなしにしない
Historyはlimit付きで表示する
巨大成果物はDBではなくファイル保存する
```

この構成は、オンプレ・社内ネット・Docker配布のAIエージェントにはかなり合います。SQLiteはアプリと同じマシン上で動く、設定不要の組み込みDBとして強い選択肢です。SQLite公式も、デバイスローカルで低い書き込み並行性、1TB未満のデータならSQLiteは良い選択になりやすいと説明しています。([SQLite][1])

## 最終案

この構成がよいです。

```text id="cjz8gd"
auth.db
  認証・認可だけを管理

agent.db
  agent profile
  tasks
  runs
  artifact_path

audit.db
  操作ログ
  監査ログ
  実行ログの概要
```

ただし、**profile と tasks/runs は同じ `agent.db` に置く**のをおすすめします。ここを分けると設計が少し難しくなります。

結論として、**複数SQLite構成は十分実用的**です。特に `auth.db / agent.db / audit.db` の3分割は、複雑にしすぎず、障害切り分け・肥大化対策・バックアップ単位の分離ができるので、今回の規模と配布形態にはかなり合っています。

[1]: https://sqlite.org/whentouse.html "Appropriate Uses For SQLite"
[2]: https://sqlite.org/wal.html "Write-Ahead Logging"
[3]: https://sqlite.org/lang_attach.html "ATTACH DATABASE"
[4]: https://sqlite.org/useovernet.html "SQLite Over a Network, Caveats and Considerations"


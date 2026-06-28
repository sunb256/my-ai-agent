
## AG-UI の特徴

できます。むしろ **assistant-ui ＋ AG-UI はその構成に向いています**。
考え方としては、**フロントエンドは「見た目・操作体験をカスタマイズできるUI層」、バックエンドは「エージェントの頭脳・業務ロジック・ツール制御を持つ秘匿層」**に分けるのが自然です。

一番大事なのは、**フロントエンドに業務ロジックを持たせないこと**です。フロントエンドはAG-UIイベントを受け取って表示するだけに近づけ、エージェントの判断、system prompt、tool選択、状態遷移、承認ルール、ファイル処理、外部API連携などはバックエンド側に閉じ込めます。

構成イメージはこうです。

```text
User Browser
  └─ Frontend
       React / assistant-ui
       UIカスタマイズ可能
       AG-UI Runtime
              ↓
        AG-UI stream API
              ↓
  ┌───────────────────────────┐
  │ Backend                    │
  │ - Agent Core               │
  │ - Tool Registry            │
  │ - Prompt / Workflow        │
  │ - Approval Policy          │
  │ - File Processing          │
  │ - LLM Provider Access      │
  └───────────────────────────┘
```

この場合、フロントエンド側が知っているのは、たとえば次のようなものだけです。

```text
POST /api/agent/runs
GET  /api/threads
POST /api/attachments
AG-UI event stream
```

一方で、バックエンド内部には次のようなものを隠します。

```text
system prompt
tool定義の詳細
業務フロー
状態遷移
承認条件
LLM呼び出し設定
RAGや検索ロジック
顧客別機能制御
エージェントの終了判定
```

つまり、**AG-UIはFE/BE境界の契約**になります。フロントエンドは「どんなイベントが来るか」だけを知ればよく、バックエンドがどう考えているかまでは知りません。

ただし、注意点があります。**バックエンドを顧客環境にDockerイメージとして配布する場合、完全な秘匿はできません。** Pythonは特に、コンテナ内にコードが入っていれば、技術的には解析される可能性があります。Cython、Nuitka、PyInstaller、難読化、wheel化などで「読みづらくする」ことはできますが、「絶対に見られない」にはなりません。

秘匿性の強さでいうと、現実的にはこの順番です。

```text
強い
  SaaSとしてバックエンドを自社運用する
  顧客にはFrontendだけ渡す

中程度
  Backendは自社管理サーバーまたは閉じたAPIとして提供
  Frontendは顧客がカスタマイズ

弱め
  Backend Dockerイメージを顧客オンプレに配布
  ソースは入れない、Cython/Nuitka等で固める

弱い
  Pythonソース付きで配布
```

一番きれいなのは、**フロントエンドだけ顧客に渡し、バックエンドは自社側でホストするSaaS型**です。この場合、エージェントの肝はほぼ守れます。顧客はUIを変えられるが、Agent Coreには触れられません。

オンプレ提供が必要なら、次のような構成が現実的です。

```text
frontend/
  顧客に提供
  React / assistant-ui
  テーマ変更、画面追加、表示カスタム可能

backend-api/
  Docker imageで提供
  FastAPI
  AG-UI endpoint
  認証、ログ、ファイルAPI

agent-core/
  ソース非公開
  wheel / Cython / Nuitka / private package
  Docker image内に組み込み
```

Docker配布なら、少なくともこうします。

```dockerfile
# ソースをそのまま最終イメージに入れない
# build stageでwheel化 / compile
# runtime stageには実行物だけ入れる
```

Pythonの場合は、たとえば次のような方針です。

```text
agent-coreを通常の .py として置かない
agent-coreをwheel化する
重要部分はCython/Nuitkaで固める
Docker imageはprivate registryから配布する
デバッグ用ファイル、tests、docs、prompt原文を入れない
設定は暗号化またはサーバー側管理にする
```

ただ、ここでも本質的には「解析しにくくする」であって、「絶対に秘匿する」ではありません。
本当に守りたいものがあるなら、**バックエンドそのものを顧客に渡さない**のが最も安全です。

あなたの考えどおり、バックエンドが肝です。特に製造業向けエージェントなら、価値はUIよりも次にあります。

```text
業務プロセスの理解
状態遷移
ツール選択
承認フロー
データ加工
LLMへの文脈投入
ファイル処理
顧客別ナレッジ連携
失敗時のリカバリ
```

assistant-uiはかなり良いUI土台ですが、差別化の中心にはなりにくいです。差別化はバックエンド側のAgent Coreにあります。

なので、設計方針としてはこれがよいです。

```text
Frontend
  - カスタマイズ可能
  - 顧客ごとに画面・テーマ・文言を変更可能
  - AG-UI endpointに接続するだけ
  - LLMやtoolの詳細は知らない

Backend
  - 非公開
  - Agent Coreを保持
  - AG-UI protocolでイベントだけ返す
  - 顧客別ライセンスや機能制御を持つ
  - system promptやworkflowは外に出さない
```

特に避けた方がいいのは、フロントエンドにこういう情報を置くことです。

```text
system prompt
tool一覧の詳細
業務ルール
承認条件
LLM API key
RAG検索条件
顧客別ロジック
エージェントの内部状態
```

フロントエンドにはせいぜい、表示用のラベルやUI定義だけを渡すべきです。

assistant-ui + AG-UIでやるメリットは、まさにここです。
**フロントエンドはAG-UIイベントを表示するだけ、バックエンドは内部実装を隠したままエージェント実行を進められる。**
この境界を作れるので、FEを顧客向けに柔軟にしながら、BEを製品の中核として守る構成にしやすいです。

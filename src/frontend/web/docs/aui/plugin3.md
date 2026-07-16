

全体としては、**プラグイン本体はシステムに1回インストールし、どのprofileで使うかだけをprofile側に保存する構成**です。

**ユーザー操作上は「profileへ直接インストール」し、単一Plugin Hostが各profileにインストールされたpluginの集合を実行する構成**にします。

「システム全体へインストールしてからprofileで有効化」という段階はなくします。

## 全体構成

```text
┌──────────────────────────────────────────────┐
│ React / assistant-ui                         │
│                                              │
│ Profile A                                    │
│   ├─ Chat                                    │
│   ├─ Plugin一覧                              │
│   └─ Pluginをアップロード                    │
│                                              │
│ Profile B                                    │
│   ├─ Chat                                    │
│   └─ Plugin一覧                              │
└──────────────────────┬───────────────────────┘
                       │ HTTP / AG-UI streaming
                       ▼
┌──────────────────────────────────────────────┐
│ FastAPI Backend                              │
│                                              │
│ ・AgentApiService                            │
│ ・ProfileService                             │
│ ・ProfilePluginService                       │
│ ・PluginManager                              │
│ ・PluginHostClient                           │
│                                              │
│ built-in tool       → FastAPI内で実行        │
│ plugin tool         → Plugin Hostへ転送      │
└──────────────────────┬───────────────────────┘
                       │ localhost HTTP
                       ▼
┌──────────────────────────────────────────────┐
│ 単一Plugin Host                              │
│ 127.0.0.1:18100                              │
│                                              │
│ Profile A                                    │
│   ├─ weather                                 │
│   └─ report                                  │
│                                              │
│ Profile B                                    │
│   └─ database                                │
└──────────────────────────────────────────────┘
```

Dockerコンテナ内では次の2プロセスです。

```text
Docker Backend Container
├─ FastAPI / Uvicorn     0.0.0.0:8000
└─ Plugin Host           127.0.0.1:18100
```

外部へ公開するのはFastAPIの8000番だけです。

---

## profileへのインストール

Plugin管理画面はシステム共通ではなく、profileの設定画面に配置します。

```text
Profile A
├─ 基本設定
├─ LLM設定
├─ Skill設定
└─ Plugin設定
    ├─ weather 1.0
    ├─ report 1.2
    └─ Pluginをインストール
```

操作の流れは次のとおりです。

```text
1. Profile AのPlugin画面を開く
2. plugin ZIPをアップロード
3. FastAPIがProfile A向けに検証
4. 問題があればインストール失敗
5. 問題がなければProfile Aへ登録
6. Plugin Hostを再起動
7. Profile Aのtool一覧へ反映
```

「インストール」と「有効化」は分けません。

```text
Profile Aにインストール済み
    → Profile Aで利用可能

Profile Aに未インストール
    → Profile Aでは利用不可
```

必要になった場合だけ、後から一時無効化フラグを追加できますが、最初の実装には不要です。

---

## インストール時の検証

検証は、各profileへのインストール操作の中で行います。

```text
Profile AへZIPアップロード
  ↓
一時ディレクトリへ展開
  ↓
ZIP構造検証
  ↓
manifest検証
  ↓
plugin import検証
  ↓
tool定義取得
  ↓
JSON Schema検証
  ↓
tool名重複確認
  ↓
self test
  ↓
すべて成功した場合だけProfile Aへ登録
```

失敗した場合は、profileの設定や現在のPlugin Hostには何も反映しません。

```text
検証成功
    Profile Aへインストール

検証失敗
    一時ファイル削除
    Profile Aは変更しない
```

したがって、システムへ一度登録してからprofileで確認する必要はありません。

---

## ファイル配置

分かりやすさを優先するなら、profile単位のディレクトリにします。

```text
/data/profiles/
├─ profile-a/
│  └─ plugins/
│     ├─ weather/
│     │  └─ release-2/
│     └─ report/
│        └─ release-1/
│
└─ profile-b/
   └─ plugins/
      └─ database/
         └─ release-3/
```

ただし、同じpluginを複数profileへコピーするとファイルが重複します。

内部実装では、pluginファイルをハッシュ単位で共通保存して、profileから参照する方式も使えます。

```text
/data/plugin-artifacts/
├─ sha256-aaa/
│  └─ weather 1.0
└─ sha256-bbb/
   └─ database 1.0
```

DB上では次のように紐付けます。

```text
Profile A → weather artifact
Profile B → database artifact
```

これはあくまで内部的な重複排除です。ユーザーから見た操作は、あくまで「Profile Aへweatherをインストール」です。

最初はprofileディレクトリへのコピーでも問題ありません。ファイル容量が問題になってからハッシュ共有へ変更できます。

---

## DB構成

中心になるのは`profile_plugins`です。

```sql
CREATE TABLE profile_plugins (
    profile_id        TEXT NOT NULL,
    plugin_id         TEXT NOT NULL,
    name              TEXT NOT NULL,
    version           TEXT NOT NULL,
    release_path      TEXT NOT NULL,
    config_json       TEXT NOT NULL DEFAULT '{}',
    status            TEXT NOT NULL,
    installed_at      TEXT NOT NULL,
    updated_at        TEXT NOT NULL,

    PRIMARY KEY (profile_id, plugin_id)
);
```

statusは最低限これだけで足ります。

```text
INSTALLING
ACTIVE
FAILED
```

実行時に必要なtool情報を保存するテーブルを分けても構いません。

```sql
CREATE TABLE profile_plugin_tools (
    profile_id        TEXT NOT NULL,
    plugin_id         TEXT NOT NULL,
    tool_name         TEXT NOT NULL,
    description       TEXT NOT NULL,
    tool_def_json     TEXT NOT NULL,
    need_confirm      INTEGER NOT NULL DEFAULT 0,

    PRIMARY KEY (
        profile_id,
        plugin_id,
        tool_name
    )
);
```

規模が小さいうちは、tool情報を`profile_plugins`の`manifest_json`にまとめても十分です。

---

## Plugin Hostが保持するもの

単一Plugin Hostは、各profileのインストール済みpluginを読み込みます。

内部registryは次のような形です。

```python
type PluginKey = tuple[str, str]
# (profile_id, plugin_id)

plugins: dict[PluginKey, LoadedPlugin]
```

具体的には次の状態になります。

```python
plugins = {
    ("profile-a", "weather"): weather_plugin,
    ("profile-a", "report"): report_plugin,
    ("profile-b", "database"): database_plugin,
}
```

toolのキーにもprofileを含めます。

```python
type ToolKey = tuple[str, str, str]
# (profile_id, plugin_id, tool_name)

tools = {
    (
        "profile-a",
        "weather",
        "get_forecast",
    ): get_forecast_tool,

    (
        "profile-a",
        "report",
        "create_report",
    ): create_report_tool,

    (
        "profile-b",
        "database",
        "execute_query",
    ): execute_query_tool,
}
```

これにより、同じtool名が別profileに存在しても区別できます。

---

## Chat実行時の流れ

Profile Aでチャットを開始した場合です。

```text
1. Reactがprofile_id付きでChatを開始
2. FastAPIがProfile Aのインストール済みpluginを取得
3. Profile A用のRemoteToolだけをAgentへ渡す
4. LLMがtool callを生成
5. FastAPIがPlugin Hostへ実行要求
6. Plugin HostがProfile Aのpluginを実行
7. 結果をAgentへ返す
8. AG-UIでReactへstreaming
```

```text
React
  │ profile_id = profile-a
  ▼
FastAPI
  │
  ├─ built-in tool
  │
  ├─ profile-a / weather
  └─ profile-a / report
           │
           ▼
          LLM
           │
           │ tool call
           ▼
      RemoteTool
           │
           │ profile_id = profile-a
           │ plugin_id  = weather
           │ tool_name  = get_forecast
           ▼
      Plugin Host
```

Profile Bのdatabase toolは、Profile AのLLMには渡されません。

---

## Agentへ渡すtoolの取得

```python
async def get_tools_for_profile(
    profile_id: str,
) -> list[BaseTool]:
    builtin_tools = builtin_tool_registry.snapshot()

    plugin_records = await profile_plugin_repository.list_active(
        profile_id=profile_id,
    )

    plugin_tools = [
        RemoteTool(
            client=plugin_host_client,
            profile_id=record.profile_id,
            plugin_id=record.plugin_id,
            name=tool.name,
            desc=tool.description,
            tool_def=tool.tool_def,
            need_confirm=tool.need_confirm,
        )
        for record in plugin_records
        for tool in record.tools
    ]

    return [
        *builtin_tools,
        *plugin_tools,
    ]
```

Agent実行時にprofileのtool一覧を取得します。

```python
async def run_agent(
    profile_id: str,
    input_: RunAgentInput,
):
    tools = await get_tools_for_profile(profile_id)

    return await agent.run(
        input_,
        tools=tools,
    )
```

現在のAgentが起動時にtoolを固定している場合は、`run()`ごとにtoolを渡せるように変更する必要があります。

---

## RemoteTool

`RemoteTool`自身がprofile情報を保持します。

```python
class RemoteTool(BaseTool):
    def __init__(
        self,
        *,
        client: "PluginHostClient",
        profile_id: str,
        plugin_id: str,
        name: str,
        desc: str,
        tool_def: dict[str, Any],
        need_confirm: bool = False,
    ):
        super().__init__(
            name=name,
            desc=desc,
            tool_def=tool_def,
            need_confirm=need_confirm,
        )

        self.profile_id = profile_id
        self.plugin_id = plugin_id
        self._client = client

    async def exec(
        self,
        ctx: ExecContext,
        **kwargs: Any,
    ) -> Any:
        return await self._client.call_tool(
            profile_id=self.profile_id,
            plugin_id=self.plugin_id,
            tool_name=self.name,
            arguments=kwargs,
            context={
                "user_id": ctx.user_id,
                "thread_id": ctx.thread_id,
                "run_id": ctx.run_id,
            },
        )
```

Plugin Hostへのリクエストは次のようになります。

```json
{
  "profile_id": "profile-a",
  "plugin_id": "weather",
  "tool_name": "get_forecast",
  "arguments": {
    "location": "Tokyo"
  },
  "context": {
    "user_id": "user-1",
    "thread_id": "thread-1",
    "run_id": "run-1"
  }
}
```

Plugin Host側では、必ず3項目で検索します。

```python
tool = registry.get(
    profile_id=request.profile_id,
    plugin_id=request.plugin_id,
    tool_name=request.tool_name,
)
```

---

## 認可上の注意

リクエストに`profile_id`が入っているだけでは不十分です。

FastAPI側で、そのユーザーが指定profileを使用できるかを確認します。

```text
ユーザー
  ↓
Profile Aへのアクセス権確認
  ↓
Profile Aにインストール済みのtoolか確認
  ↓
Plugin Hostへ実行要求
```

LLMが任意の`profile_id`を生成できる形にはしません。

`RemoteTool`が保持しているprofile IDと、現在の実行コンテキストを照合します。

```python
if ctx.profile_id != self.profile_id:
    raise PermissionError(
        "Tool does not belong to the active profile"
    )
```

また、Plugin Host側でもprofileとpluginの組み合わせがregistryに存在するか確認します。

---

## Profile Aへのインストール処理

```python
class ProfilePluginService:
    def __init__(
        self,
        repository: "ProfilePluginRepository",
        validator: "PluginValidator",
        plugin_manager: "PluginManager",
    ):
        self._repository = repository
        self._validator = validator
        self._plugin_manager = plugin_manager
        self._lock = asyncio.Lock()

    async def install(
        self,
        *,
        profile_id: str,
        archive_path: Path,
    ) -> None:
        async with self._lock:
            staged_release = await self._plugin_manager.stage(
                profile_id=profile_id,
                archive_path=archive_path,
            )

            try:
                validation = await self._validator.validate(
                    profile_id=profile_id,
                    release=staged_release,
                )

                await self._repository.save_installing(
                    profile_id=profile_id,
                    release=staged_release,
                    tools=validation.tools,
                )

                await self._plugin_manager.activate_release(
                    profile_id=profile_id,
                    release=staged_release,
                )

                await self._plugin_manager.restart_host()

                await self._repository.mark_active(
                    profile_id=profile_id,
                    plugin_id=staged_release.plugin_id,
                )

            except Exception:
                await self._plugin_manager.remove_staged(
                    staged_release
                )
                raise
```

実際には、Host再起動後のhealth checkが成功してから`ACTIVE`にします。

---

## Plugin Host再起動時の流れ

Profile Aにpluginを追加しても、Plugin Hostは単一なので、全profile分を読み直します。

```text
現在のPlugin Host

Profile A
    weather

Profile B
    database
```

Profile Aへreportをインストールします。

```text
新しいPlugin Host

Profile A
    weather
    report

Profile B
    database
```

更新処理は次のとおりです。

```text
1. Profile A用のreportをstagingへ展開
2. 検証用プロセスでreportを検証
3. 検証成功
4. Plugin toolの新規実行を一時停止
5. 現在実行中のplugin callがないことを確認
6. Plugin Hostを停止
7. reportをProfile Aのactive領域へ移動
8. 同じ127.0.0.1:18100でPlugin Hostを起動
9. Plugin Hostが全profile分を読み込む
10. health check
11. Profile AのreportをACTIVEにする
12. plugin実行を再開
```

FastAPI、チャット履歴、AG-UI接続、Dockerコンテナは再起動しません。

---

## 更新失敗時

Profile Aのplugin更新に失敗しても、Profile Bのplugin構成を壊さないようにします。

```text
Profile A / weather 1.1を検証
  ↓
検証失敗
  ↓
weather 1.0はそのまま
Plugin Hostは再起動しない
Profile Bにも影響なし
```

Host再起動後に失敗した場合は、旧releaseに戻して同じポートでHostを再起動します。

```text
新Hostの起動失敗
  ↓
Profile Aのactive releaseを旧版へ戻す
  ↓
旧構成でPlugin Hostを再起動
```

更新完了までは旧releaseを残します。成功後に削除します。

---

## 同じpluginを複数profileへ入れる場合

ユーザー操作としては、それぞれのprofileへインストールします。

```text
Profile A
    weatherをインストール

Profile B
    weatherをインストール
```

内部では同じファイルを2回保存しても動きますが、同じPlugin Host内に同じPythonコードを二重importすると扱いが複雑になります。

初期実装では次の制約が安全です。

> 同じplugin IDについて、Plugin Host内で動作するコードバージョンは1つにする。profileごとに異なるのは、インストール有無と設定だけにする。

つまり次は対応します。

```text
Profile A
    weather 1.0をインストール

Profile B
    weather 1.0をインストール
```

次は初期版では対応しません。

```text
Profile A
    weather 1.0

Profile B
    weather 2.0
```

同じpluginを別profileへインストールする場合、内部では既存artifactを再利用できます。

```text
Plugin Artifact
    weather 1.0を1回だけロード

Profile A
    weather 1.0への参照

Profile B
    weather 1.0への参照
```

ただし、ユーザーに「全体へインストール済みなので有効化してください」という操作は見せません。Profile Bでも通常どおりZIPをアップロードするか、利用可能なパッケージを選んでインストールします。

---

## 修正後の設計方針

```text
Pluginのインストール先
    profile

Pluginの検証
    profileへのインストール操作時

インストール失敗時
    profileに何も登録しない

Plugin Host
    システムに1プロセス

Plugin Hostが読み込むもの
    全profileのインストール済みplugin

Agentへ渡すtool
    現在のprofileにインストールされたものだけ

profileごとの違い
    pluginのインストール有無
    plugin設定

同一pluginのバージョン
    初期版ではシステム内で統一

Plugin更新時
    Plugin Hostのみ固定ポートで再起動

FastAPIとDocker
    再起動しない
```

この構成なら、UIとデータモデルは自然に「profileがpluginを持つ」形になりながら、実行基盤は単一Plugin Hostのまま維持できます。

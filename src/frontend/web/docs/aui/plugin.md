できます。Python には **zip ファイルをそのまま import できる仕組み**があります。なので、設計としては十分可能です。ただし、**Web から取得した zip を import する＝任意コード実行**なので、実用化するなら認証・署名検証・隔離実行まで考えた方がいいです。

一番現実的な構成はこれです。

```text
Web上の plugin.zip
        ↓ download
ローカルの plugins/cache に保存
        ↓ hash / signature 検証
zip を sys.path に追加
        ↓ importlib で import
Plugin クラスを生成して実行
```

例えば zip の中身をこうします。

```text
my_plugin.zip
  my_plugin/
    __init__.py
    plugin.py
  plugin.json
```

`plugin.py` はこういう形にします。

```python
class Plugin:
    name = "my_plugin"

    def run(self, text: str) -> str:
        return f"plugin processed: {text}"
```

読み込む側は最小だとこう書けます。

```python
import sys
import importlib
from pathlib import Path

def load_plugin_from_zip(zip_path: str, module_name: str, class_name: str = "Plugin"):
    zip_path = str(Path(zip_path).resolve())

    if zip_path not in sys.path:
        sys.path.insert(0, zip_path)

    module = importlib.import_module(module_name)
    plugin_cls = getattr(module, class_name)

    return plugin_cls()


plugin = load_plugin_from_zip(
    zip_path="./plugins/cache/my_plugin.zip",
    module_name="my_plugin.plugin",
)

print(plugin.run("hello"))
```

これで `my_plugin.zip` の中の `my_plugin/plugin.py` を import できます。

Web から取る場合は、直接 import するのではなく、一度ローカルに保存してから import するのがいいです。

```python
import urllib.request
from pathlib import Path

def download_plugin(url: str, save_path: str) -> Path:
    path = Path(save_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(url) as response:
        data = response.read()

    path.write_bytes(data)
    return path
```

使う側はこうです。

```python
zip_path = download_plugin(
    url="https://example.com/plugins/my_plugin.zip",
    save_path="./plugins/cache/my_plugin.zip",
)

plugin = load_plugin_from_zip(
    zip_path=str(zip_path),
    module_name="my_plugin.plugin",
)
```

ただし、このままだと危険です。plugin 側は Python コードなので、読み込んだ瞬間に何でもできます。ファイル削除、ネットワークアクセス、環境変数読み取りなども可能です。AI エージェントの tool plugin のような用途なら、最低限このあたりは入れた方がいいです。

```text
必須に近いもの:
- plugin.json に name / version / entrypoint / permissions を書く
- zip の SHA256 を検証する
- 可能なら署名検証する
- 読み込む前に許可済み plugin か確認する
- plugin 実行は subprocess / container / sandbox に分離する
```

`plugin.json` は例えばこうです。

```json
{
  "name": "my_plugin",
  "version": "0.1.0",
  "entrypoint": "my_plugin.plugin:Plugin",
  "permissions": ["read_file"]
}
```

loader 側では entrypoint を読んで import します。

```python
import json
import sys
import zipfile
import importlib
from pathlib import Path

def read_manifest(zip_path: str) -> dict:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("plugin.json") as f:
            return json.loads(f.read().decode("utf-8"))


def load_plugin(zip_path: str):
    manifest = read_manifest(zip_path)

    entrypoint = manifest["entrypoint"]
    module_name, class_name = entrypoint.split(":")

    zip_path = str(Path(zip_path).resolve())

    if zip_path not in sys.path:
        sys.path.insert(0, zip_path)

    module = importlib.import_module(module_name)
    plugin_cls = getattr(module, class_name)

    return plugin_cls()
```

実装上の注意点はかなり重要です。

まず、**zip import は pure Python には向いています**。一方で、`.so` や `.pyd` のようなネイティブ拡張を含む package はそのままだとうまく扱えないことがあります。NumPy や pandas のような重い依存を plugin zip に入れる設計は避けた方がいいです。

また、plugin 内でファイルを読む場合、通常の `open("path")` では壊れやすいです。zip 内リソースを扱うなら `importlib.resources` を使う方が安全です。

さらに、plugin の reload / unload は面倒です。一度 import すると `sys.modules` に残ります。開発中に差し替えたい場合は、プロセスを分けて実行する方が楽です。

個人的には、AI エージェント向けなら次の設計が一番扱いやすいです。

```text
PluginRegistry
  ├─ plugin zip をダウンロード
  ├─ manifest を読む
  ├─ hash / version / permission を検証
  ├─ plugin を登録
  └─ tool 定義として agent に渡す

PluginRuntime
  ├─ plugin を subprocess / container で起動
  ├─ JSON-RPC 的に呼び出す
  └─ 結果だけ受け取る
```

同一プロセス内 import は簡単ですが、安全性と更新性が弱いです。自分用・ローカル用なら同一プロセス import で十分です。ユーザに配布したり、Web から plugin を追加できる仕組みにするなら、**plugin は別プロセス実行**にした方が後から苦しくなりにくいです。

結論としては、**できます**。ただしおすすめは「Web から zip を取ってその場で import」ではなく、**ダウンロード → 検証 → キャッシュ → manifest に従って import → 可能なら隔離実行**です。特に AI エージェントの tool plugin として使うなら、最初から permission と sandbox 前提で設計した方がいいです。


------

はい、できます。今の `@tool` デコレータ形式は、プラグイン機構とかなり相性がいいです。設計としては、**プラグイン zip の中に `@tool` 付き関数を書き、ホスト側が import して `BaseTool` の一覧として登録する**形にできます。

重要なのは、プラグイン側に `FuncTool` / `BaseTool` 本体をコピーして入れないことです。ホスト側が公開する SDK、たとえば `myagent_sdk` のような小さいパッケージを用意して、プラグインはそこから `tool` を import する形にするのがよいです。

構成例です。

```text
sample_plugin.zip
  plugin.json
  sample_plugin/
    __init__.py
    tools.py
```

`plugin.json` はこうします。

```json
{
  "name": "sample_plugin",
  "version": "0.1.0",
  "api_version": "1",
  "entrypoint": "sample_plugin.tools:register"
}
```

プラグイン側の `sample_plugin/tools.py` はこう書けます。

```python
from myagent_sdk import tool


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


@tool(need_confirm=True, confirm_msg_tmpl="Delete file {args}?")
def delete_file(filepath: str) -> str:
    """Deletes a file. This action cannot be undone."""
    return f"File {filepath} has been deleted."


def register():
    return [
        add_numbers,
        delete_file,
    ]
```

ここで `add_numbers` や `delete_file` は、元の関数ではなく `FuncTool` オブジェクトになります。あなたの `@tool` デコレータが `FuncTool(...)` を返しているからです。なので `register()` は `list[BaseTool]` を返すイメージになります。

ホスト側の loader はこんな感じです。

```python
import json
import sys
import zipfile
import importlib
from pathlib import Path
from typing import Any

from myagent_core import BaseTool


def read_manifest(zip_path: str) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("plugin.json") as f:
            return json.loads(f.read().decode("utf-8"))


def resolve_entrypoint(entrypoint: str):
    module_name, attr_name = entrypoint.split(":", maxsplit=1)

    module = importlib.import_module(module_name)

    obj = module
    for part in attr_name.split("."):
        obj = getattr(obj, part)

    return obj


def load_plugin_from_zip(zip_path: str) -> list[BaseTool]:
    zip_path = str(Path(zip_path).resolve())
    manifest = read_manifest(zip_path)

    if zip_path not in sys.path:
        sys.path.insert(0, zip_path)

    importlib.invalidate_caches()

    register = resolve_entrypoint(manifest["entrypoint"])
    tools = register()

    if not isinstance(tools, list):
        raise TypeError("Plugin register() must return list[BaseTool]")

    for tool_obj in tools:
        if not isinstance(tool_obj, BaseTool):
            raise TypeError(
                f"Invalid plugin tool: {tool_obj!r}. "
                "Plugin tools must be created by myagent_sdk.tool"
            )

    return tools
```

使う側はこうです。

```python
tools = load_plugin_from_zip("./plugins/sample_plugin.zip")

for tool in tools:
    registry.add(tool)
```

Web からインストールするなら、流れはこうです。

```python
import hashlib
import urllib.request
from pathlib import Path


def sha256_file(path: str) -> str:
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def download_plugin(url: str, save_path: str, expected_sha256: str | None = None) -> Path:
    path = Path(save_path)
    path.parent.mkdir(parents=True, exist_ok=True)

    with urllib.request.urlopen(url) as response:
        data = response.read()

    path.write_bytes(data)

    if expected_sha256 is not None:
        actual = sha256_file(str(path))
        if actual != expected_sha256:
            path.unlink(missing_ok=True)
            raise ValueError("Plugin hash mismatch")

    return path
```

使用例です。

```python
zip_path = download_plugin(
    url="https://example.com/plugins/sample_plugin.zip",
    save_path="./plugins/cache/sample_plugin.zip",
    expected_sha256="...",
)

tools = load_plugin_from_zip(str(zip_path))

for tool in tools:
    registry.add(tool)
```

この設計で、あなたの `FuncTool` はほぼそのまま使えます。ただし、1点だけかなり重要です。

プラグイン zip の中に `BaseTool` や `FuncTool` や `tool` の実装を同梱しない方がいいです。ホスト側とプラグイン側で別々の `BaseTool` クラスが読み込まれると、見た目は同じでも Python 的には別クラスになり、`isinstance(tool_obj, BaseTool)` が壊れます。

なので、こういう分離にするとよいです。

```text
myagent_core
  BaseTool
  FuncTool
  ExecContext
  registry

myagent_sdk
  tool
  BaseTool 型だけ公開
  plugin 開発者が import する公開 API

plugin.zip
  from myagent_sdk import tool
```

AI エージェント用途なら、`plugin.json` に permission も入れておくと後で拡張しやすいです。

```json
{
  "name": "sample_plugin",
  "version": "0.1.0",
  "api_version": "1",
  "entrypoint": "sample_plugin.tools:register",
  "permissions": [
    "file.delete"
  ]
}
```

そして `need_confirm=True` のような情報と合わせて、registry 登録時にチェックします。

```python
def validate_plugin_tools(manifest: dict[str, Any], tools: list[BaseTool]) -> None:
    permissions = set(manifest.get("permissions", []))

    for tool_obj in tools:
        if tool_obj.need_confirm:
            continue

        if tool_obj.name in {"delete_file", "write_file", "send_email"}:
            raise ValueError(
                f"Tool {tool_obj.name} is dangerous but need_confirm is false"
            )

        if tool_obj.name == "delete_file" and "file.delete" not in permissions:
            raise ValueError("delete_file requires file.delete permission")
```

`sandbox_exec=True` については注意が必要です。`inspect.getsource(self.func)` は zip import された `.py` からでも動くことがありますが、常に安心できる設計ではありません。特に `.pyc` 化した場合や、配布形式を変えた場合に壊れやすいです。

なので、`sandbox_exec` を本気で使うなら、次のどちらかがよいです。

1つ目は、今のように `inspect.getsource()` で関数ソースを取り出す方式です。これは簡単ですが、開発初期向けです。

2つ目は、プラグイン zip 自体を sandbox に配置して、sandbox 内で同じ entrypoint を import して実行する方式です。こちらの方が実運用向けです。

```text
ホスト側
  plugin.zip を検証
  tool_def だけ読む
  LLM に tool_def を渡す

実行時
  sandbox に plugin.zip を渡す
  sandbox 内で import
  指定 tool を JSON 引数で実行
  結果だけホストへ返す
```

この方式にすると、`get_source_code()` に依存しなくて済みます。プラグインが複数関数や内部 helper を使っていても、そのまま動かせます。

結論として、あなたの今の形式ならかなり自然に実現できます。おすすめのプラグイン仕様はこれです。

```python
from myagent_sdk import tool

@tool
def some_tool(...):
    ...

def register():
    return [some_tool]
```

ホスト側は、

```text
download
→ hash / signature 検証
→ zip を sys.path に追加
→ plugin.json の entrypoint を import
→ register() を呼ぶ
→ BaseTool として registry に登録
```

という流れにすればよいです。同一プロセスで動かすだけなら比較的簡単です。Web から任意プラグインを入れられるようにするなら、最終的には sandbox / subprocess / container 実行に寄せた方が安全です。



結論は、**MCPだけに寄せなくていいです。自作の zip plugin 機構もあってよいです。** むしろ、あなたの今の `BaseTool / FuncTool / @tool` 設計なら、**内部 tool は自作 plugin、外部連携や他アプリとの互換性が欲しいものは MCP**、という分け方が自然です。

MCP は、AIアプリが外部サーバから `Tools / Resources / Prompts` を発見して呼び出すための標準プロトコルです。公式仕様でも Tools は「モデルが外部システムとやり取りするための機能」として定義されています。([Model Context Protocol][1]) つまり MCP は **tool をどう発見し、どう呼び出すかの外部接続規格** です。一方、あなたの zip plugin は **自作エージェント内部で Python tool を増やす仕組み** です。役割が少し違います。

整理するとこうです。

| 方式            | 向いている用途                                                                        |
| ------------- | ------------------------------------------------------------------------------ |
| 自作 zip plugin | 自作エージェント専用 tool、Python 関数をそのまま追加、開発速度重視、`@tool` デコレータを活かしたい場合                  |
| MCP           | 他のAIクライアントからも使わせたい、言語非依存にしたい、別プロセス/別サービスとして分離したい、GitHub/DB/SaaSなど外部連携を標準化したい場合 |

なので、今の設計で一番よいのは **ToolRegistry の入口を複数持つこと** です。

```text
ToolRegistry
  ├─ built-in tools
  ├─ zip plugin tools
  └─ MCP tools
```

LLM に渡す時点では、どちらも同じ `BaseTool` として扱います。

```text
LLM
 ↓ tool_call
Agent
 ↓
BaseTool.exec()
 ├─ FuncTool.exec()        # Python関数を直接実行
 └─ McpTool.exec()         # MCP server に call_tool
```

つまり、あなたの `BaseTool` 抽象はそのまま活かせます。MCP を追加するなら、`FuncTool` と並べて `McpTool` を作るだけでよいです。

イメージはこうです。

```python
class McpTool(BaseTool):
    def __init__(self, client, name: str, desc: str, tool_def: dict):
        self.client = client

        super().__init__(
            name=name,
            desc=desc,
            tool_def=tool_def,
            need_confirm=False,
            confirm_msg_tmpl="",
        )

    async def exec(self, ctx: ExecContext, **kwargs):
        return await self.client.call_tool(
            name=self.name,
            arguments=kwargs,
        )
```

MCP server から tool 一覧を取得して、自分の `BaseTool` に変換します。

```python
async def load_mcp_tools(client) -> list[BaseTool]:
    mcp_tools = await client.list_tools()

    tools: list[BaseTool] = []

    for item in mcp_tools:
        tool_def = format_tool_def(
            name=item.name,
            desc=item.description or "",
            params=item.input_schema,
        )

        tools.append(
            McpTool(
                client=client,
                name=item.name,
                desc=item.description or "",
                tool_def=tool_def,
            )
        )

    return tools
```

この形にすると、エージェント本体は「これは zip plugin 由来か、MCP 由来か」をほとんど意識しなくてよくなります。

```python
registry.add_many(load_builtin_tools())
registry.add_many(load_zip_plugin_tools("./plugins/sample.zip"))
registry.add_many(await load_mcp_tools(mcp_client))
```

判断基準としては、まず **自作エージェントに密結合してよい tool は zip plugin** でいいです。たとえば、あなたの `ExecContext` を使いたい tool、agent 内部状態に触る tool、独自の `need_confirm` や `sandbox_exec` と強く結びつく tool は、自作 plugin の方が扱いやすいです。

逆に、GitHub、Google Drive、社内DB、ERP、PLM、ファイルサーバなど、**外部システムとの接続口**は MCP に寄せる価値があります。MCP にしておけば、将来的に別のAIクライアントや別のagentからも同じ server を使える可能性があります。

ただし、MCP にすれば認証認可や安全性が全部解決するわけではありません。MCP の Authorization 仕様では OAuth 2.1 などが扱われていますが、tool を実行してよいか、危険操作に確認を挟むか、どの tool を LLM に見せるかは、結局 host / agent 側の制御が必要です。([Model Context Protocol][2]) あなたの `need_confirm=True` や `confirm_msg_tmpl` の設計は、MCP を使う場合でも残した方がいいです。

おすすめの結論はこれです。

```text
短期:
  今の @tool / FuncTool / zip plugin を作る

中期:
  ToolRegistry を抽象化して、zip plugin と MCP の両方を登録できるようにする

長期:
  外部連携系は MCP server 化
  agent内部専用・業務ロジック専用 tool は zip plugin のまま
```

最初から全部 MCP にすると、MCP server、client、transport、認証、プロセス管理が増えて、開発が重くなります。今の段階では、自作 plugin 機構を作る意味は十分あります。そのうえで、`BaseTool` の下に `FuncTool` と `McpTool` を並べる設計にしておけば、後から MCP に寄せることもできます。

[1]: https://modelcontextprotocol.io/specification/2025-06-18?utm_source=chatgpt.com "Specification"
[2]: https://modelcontextprotocol.io/specification/draft/basic/authorization?utm_source=chatgpt.com "Authorization"


-----

これはskillsでも機能するような気がするけど違うのでしょうか？


はい、かなり近いです。**「agent に後から能力を足す」という意味では、plugin と skills は同じ方向の仕組み**です。違いは主に、**実行可能コードとして扱うか、LLM に読ませる手順・知識として扱うか**です。

ざっくり言うと、こう分けると分かりやすいです。

| 仕組み           | 主体                        | 向いているもの                       |
| ------------- | ------------------------- | ----------------------------- |
| Skill         | LLMが読む説明・手順・テンプレート        | 作業手順、プロンプト、注意点、業務ルール、出力フォーマット |
| Plugin / Tool | Pythonコードとして実行される関数       | 検証、変換、計算、ファイル操作、API呼び出し、DB操作  |
| MCP           | 外部プロセス/外部サービスとして公開されるtool | GitHub、DB、SaaS、社内システム連携       |

なので、あなたが考えている `@tool` のようなものは、**skills だけでも一部は代替できますが、完全には代替できません**。

たとえば、これは skill で十分です。

```text
不具合報告書を作るときは、以下の順番で確認する。
1. 現象
2. 発生条件
3. 暫定対応
4. 恒久対応
5. 再発防止策
不足があればユーザに確認する。
```

これは LLM に読ませれば機能します。コード実行は不要です。

一方で、これは plugin/tool の方が向いています。

```python
@tool
def validate_lot_quantity(quantity: int, lot_size: int) -> dict:
    return {
        "ok": quantity % lot_size == 0,
        "message": "数量はロットサイズの倍数である必要があります"
    }
```

この場合、LLM に「ロットサイズの倍数か確認して」と書かせるより、Python で確定的に検査した方が安全です。

特に違いが出るのはここです。

**Skill は LLM の振る舞いを誘導するもの**です。
つまり、うまく従うかどうかは最終的に LLM 次第です。文章生成、手順遵守、判断補助には向いています。

**Plugin/tool は agent が実行するもの**です。
入力が同じなら同じ結果になりやすく、バリデーション、変換、検索、削除、送信、DB更新などに向いています。

なので、製造業向け agent なら、むしろ両方あるとよいです。

```text
bom_skill
  - BOMを読む時の観点
  - 欠品・代替品・数量を見る順序
  - レポートの書き方

bom_plugin
  - 品番の正規化
  - 数量チェック
  - 単位変換
  - CSV出力
  - BOM差分検出
```

たとえば skill はこうです。

```text
BOMを確認するときは、品番、数量、単位、代替品、手配区分を確認する。
不明な品番は「未確認」として扱い、推測で補完しない。
結果は Markdown の表で出力する。
```

plugin はこうです。

```python
@tool
def normalize_part_number(part_number: str) -> str:
    return part_number.strip().upper().replace(" ", "-")
```

この2つは競合ではなく、組み合わせるものです。
skill が「どう考えるか」を与え、plugin/tool が「確実に実行する処理」を担当します。

あなたの構成でいうと、こういう階層が自然です。

```text
Profile
  ├─ enabled skills
  ├─ enabled plugins
  ├─ enabled MCP servers
  └─ system prompt / model config
```

そして agent 実行時には、

```text
Skill
  → system prompt / context に入れる

Plugin
  → tool list に変換して LLM に渡す

MCP
  → tool list に変換して LLM に渡す
```

という扱いにします。

結論として、**skills でもかなりのことはできます**。ただし、skills は「LLMに読ませる業務知識・手順」、plugin は「実行可能なtool」、MCPは「外部toolサーバ」と分けた方が設計がきれいです。

最初に作るなら、優先順位はこうでよいと思います。

```text
1. Skill
   業務手順・テンプレート・出力形式を追加できるようにする

2. Plugin
   Python関数として確実に実行したい処理を追加できるようにする

3. MCP
   外部サービス連携が必要になったら追加する
```

なので、「plugin は不要で skills だけでよい」というより、**skills を先に作り、コード実行が必要なところだけ plugin にする**のが一番現実的です。



できます。やり方は、**plugin zip の中に `vendor/` ディレクトリを作り、そこへ依存ライブラリを `pip install --target` で入れる**形です。Python は zip 内の `.py` / `.pyc` を import できるので、`sys.path` に `plugin.zip` と `plugin.zip/vendor` を追加すれば、plugin 本体と同梱ライブラリを読み込めます。公式にも zip archive 内の Python module/package は import 可能と説明されています。([Python documentation][1])

構成はこうです。

```text id="ej3vzl"
sample_plugin.zip
  plugin.json
  sample_plugin/
    __init__.py
    tools.py
  vendor/
    requests/
    urllib3/
    idna/
    certifi/
    charset_normalizer/
```

plugin 側は普通に import できます。

```python id="1hjwva"
from myagent_sdk import tool
import requests


@tool
def fetch_text(url: str) -> str:
    """Fetch text from a URL."""
    response = requests.get(url, timeout=10)
    response.raise_for_status()
    return response.text[:1000]


def register():
    return [fetch_text]
```

作り方は、まず plugin 作業ディレクトリを作ります。

```text id="mppxps"
sample_plugin/
  plugin.json
  requirements.txt
  sample_plugin/
    __init__.py
    tools.py
```

`requirements.txt` は例えばこうです。

```txt id="31gknz"
requests==2.32.3
```

そこに依存ライブラリを `vendor/` へ入れます。

```bash id="5jogyu"
cd sample_plugin
python -m pip install -r requirements.txt --target vendor
zip -r ../sample_plugin.zip plugin.json sample_plugin vendor
```

loader 側では、`plugin.zip` と `plugin.zip/vendor` の両方を `sys.path` に追加します。`sys.path` は Python の import 検索パスで、ここに追加した場所が import 対象になります。([Python documentation][2])

```python id="yjc6v6"
import json
import sys
import zipfile
import importlib
from pathlib import Path
from typing import Any

from myagent_core import BaseTool


def read_manifest(zip_path: str) -> dict[str, Any]:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("plugin.json") as f:
            return json.loads(f.read().decode("utf-8"))


def add_plugin_paths(zip_path: str) -> None:
    zip_path = str(Path(zip_path).resolve())

    # plugin本体用
    plugin_root = zip_path

    # vendorライブラリ用
    plugin_vendor = f"{zip_path}/vendor"

    # vendorを先に入れると、plugin同梱版が優先される
    for path in [plugin_vendor, plugin_root]:
        if path not in sys.path:
            sys.path.insert(0, path)

    importlib.invalidate_caches()


def resolve_entrypoint(entrypoint: str):
    module_name, attr_name = entrypoint.split(":", maxsplit=1)

    module = importlib.import_module(module_name)

    obj = module
    for part in attr_name.split("."):
        obj = getattr(obj, part)

    return obj


def load_plugin_from_zip(zip_path: str) -> list[BaseTool]:
    manifest = read_manifest(zip_path)

    add_plugin_paths(zip_path)

    register = resolve_entrypoint(manifest["entrypoint"])
    tools = register()

    if not isinstance(tools, list):
        raise TypeError("register() must return list[BaseTool]")

    for tool_obj in tools:
        if not isinstance(tool_obj, BaseTool):
            raise TypeError(f"Invalid tool object: {tool_obj!r}")

    return tools
```

`plugin.json` はこうです。

```json id="8eyqxl"
{
  "name": "sample_plugin",
  "version": "0.1.0",
  "api_version": "1",
  "entrypoint": "sample_plugin.tools:register",
  "dependencies": {
    "vendored": true,
    "path": "vendor"
  }
}
```

この方式の利点は、**インストール時に venv を作らなくてもいい**ことです。zip 1つをダウンロードして、hash 検証して、`sys.path` に追加すれば動きます。

ただし、かなり重要な制約があります。これは **pure Python ライブラリ向け**です。Python の zip import は Python module/package には使えますが、`.so` や `.pyd` のような動的拡張モジュールは zip から直接 import できません。公式ドキュメントでも、zip import は動的モジュールを読み込めないとされています。([Python documentation][1])

つまり、向いているのはこういうライブラリです。

```text id="h0td4r"
向いている:
  - requests
  - python-dateutil
  - pyyaml
  - markdown
  - jinja2
  - pure Python の小さなライブラリ

向いていない:
  - numpy
  - pandas
  - torch
  - opencv-python
  - lxml
  - cryptography
  - pydantic-core を含む構成
```

もう1つ大きな注意点は、**同一プロセス内では依存ライブラリの衝突を完全には避けられない**ことです。たとえば plugin A が `requests==2.31`、plugin B が `requests==2.32` を同梱していても、最初に import された `requests` が `sys.modules["requests"]` に残ります。その後の plugin も同じ `requests` を見てしまう可能性があります。

なので、この方式は次の前提ならかなり良いです。

```text id="fjlpg3"
- plugin は信頼済み
- 依存ライブラリは pure Python 中心
- plugin 間で依存バージョン衝突が少ない
- 重いライブラリは扱わない
- まずは単一プロセスで簡単に動かしたい
```

少し安全にするなら、plugin 読み込み時だけ `sys.path` を一時的に差し込む方法もあります。

```python id="v0kycb"
from contextlib import contextmanager
import sys
import importlib


@contextmanager
def plugin_import_paths(zip_path: str):
    plugin_root = str(Path(zip_path).resolve())
    plugin_vendor = f"{plugin_root}/vendor"

    added = []

    for path in [plugin_vendor, plugin_root]:
        if path not in sys.path:
            sys.path.insert(0, path)
            added.append(path)

    importlib.invalidate_caches()

    try:
        yield
    finally:
        for path in added:
            if path in sys.path:
                sys.path.remove(path)

        importlib.invalidate_caches()
```

ただし、これでも一度 import された module は `sys.modules` に残ります。完全な隔離ではありません。

```python id="517aky"
def load_plugin_from_zip(zip_path: str) -> list[BaseTool]:
    manifest = read_manifest(zip_path)

    with plugin_import_paths(zip_path):
        register = resolve_entrypoint(manifest["entrypoint"])
        tools = register()

    return tools
```

この書き方だと、plugin 本体の import 時には `vendor/` を見ます。ただし、実行時に plugin 内で遅延 import する場合は、実行時にも path が必要です。なので実用上は、登録後も `sys.path` に残す方式の方が簡単です。

個人的には、まずは次の仕様にするとよいです。

```text id="dlbsbz"
plugin.zip
  plugin.json
  plugin package
  vendor/

制約:
  - vendor は pure Python のみ
  - native extension 禁止
  - 同名ライブラリの複数バージョン混在は非保証
  - 未信頼 plugin は読み込まない
```

native extension が混ざっていないか簡易チェックするなら、zip 内に `.so` / `.pyd` がないか見ます。

```python id="jhj5v4"
import zipfile


def validate_no_native_extensions(zip_path: str) -> None:
    native_suffixes = (".so", ".pyd", ".dll", ".dylib")

    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            if name.lower().endswith(native_suffixes):
                raise ValueError(
                    f"Native extension is not allowed in zip plugin: {name}"
                )
```

最小の install 処理はこうです。

```python id="lv9eed"
import hashlib
from pathlib import Path


def sha256_file(path: str) -> str:
    h = hashlib.sha256()

    with open(path, "rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def install_plugin_zip(
    *,
    zip_path: str,
    plugins_dir: str,
    expected_sha256: str | None = None,
) -> Path:
    validate_no_native_extensions(zip_path)

    if expected_sha256 is not None:
        actual = sha256_file(zip_path)
        if actual != expected_sha256:
            raise ValueError("Plugin hash mismatch")

    manifest = read_manifest(zip_path)
    plugin_name = manifest["name"]
    plugin_version = manifest["version"]

    dest = Path(plugins_dir) / f"{plugin_name}-{plugin_version}.zip"
    dest.parent.mkdir(parents=True, exist_ok=True)
    dest.write_bytes(Path(zip_path).read_bytes())

    return dest
```

結論として、**plugin zip に `vendor/` を同梱する方式はあり**です。最初の実装としてはかなり扱いやすいです。ただし、対象は pure Python ライブラリに限定し、依存バージョン衝突や native extension は割り切る必要があります。重い依存や衝突が出てきたら、その plugin だけ subprocess / venv / container に逃がす、という段階的な設計がよいです。

[1]: https://docs.python.org/3/library/zipimport.html?utm_source=chatgpt.com "zipimport — Import modules from Zip archives"
[2]: https://docs.python.org/3/library/sys_path_init.html?utm_source=chatgpt.com "The initialization of the sys.path module search path"


------

必ず再起動が必要になるわけではありません。**新規 plugin の追加だけなら、backend を起動したままロードできます。** ただし、**既存 plugin の更新・削除・依存ライブラリ差し替え**まで安全にやるなら、設計を少し工夫しないと最終的に再起動が一番楽になります。

おすすめは、まずこの方針です。

```text
新規インストール:
  backend再起動なしでOK

既存pluginの更新:
  開発中はhot reloadでもOK
  本番では versioned install か backend再起動が安全

plugin削除:
  registryから無効化は可能
  Python moduleを完全にunloadするのは難しい
```

FastAPI 側では、`/plugins/install` のような管理 endpoint を作って、Web から zip を取得し、検証し、保存し、`PluginManager` に再ロードさせればよいです。

```text
/plugins/install
  ↓
download plugin.zip
  ↓
hash / manifest 検証
  ↓
plugins/installed に保存
  ↓
plugin_manager.reload()
  ↓
新しい request / session から利用可能
```

既存の `/agent` を止める必要はありません。重要なのは、**registry を直接書き換えるのではなく、新しい registry を作って丸ごと差し替える**ことです。

```python
class PluginManager:
    def __init__(self, plugins_dir: Path):
        self.plugins_dir = plugins_dir
        self._registry = ToolRegistry()

    def reload_plugins(self) -> None:
        new_registry = ToolRegistry()

        for zip_path in self.plugins_dir.glob("*.zip"):
            tools = load_plugin_from_zip(str(zip_path))
            new_registry.add_many(tools)

        # ここで一気に差し替える
        self._registry = new_registry

    def build_session_tools(self, input_: RunAgentInput) -> list[BaseTool]:
        return self._registry.all()
```

こうすると、すでに実行中の agent stream は古い tool list を持ったまま進みます。新しく始まる request から新しい tool registry を使います。これは安全です。

```text
実行中のセッション:
  古い tools のまま完走

新しいセッション:
  reload後の tools を使用
```

管理 endpoint はこんなイメージです。

```python
@app.post("/plugins/reload")
async def reload_plugins():
    if state.service is None:
        raise HTTPException(status_code=503, detail="Service not initialized.")

    state.service.reload_plugins()

    return {"ok": True}
```

`AgentApiService` 側です。

```python
class AgentApiService:
    def __init__(self, agent: Agent, plugin_manager: PluginManager):
        self._agent = agent
        self._plugin_manager = plugin_manager

    def reload_plugins(self) -> None:
        self._plugin_manager.reload_plugins()
```

Web から install までやるならこうです。

```python
@app.post("/plugins/install")
async def install_plugin(req: InstallPluginRequest):
    if state.service is None:
        raise HTTPException(status_code=503, detail="Service not initialized.")

    state.service.install_plugin_from_url(
        url=req.url,
        expected_sha256=req.sha256,
    )

    return {"ok": True}
```

```python
class AgentApiService:
    def install_plugin_from_url(
        self,
        url: str,
        expected_sha256: str | None = None,
    ) -> None:
        zip_path = download_plugin(
            url=url,
            save_dir=self._plugin_manager.plugins_dir,
            expected_sha256=expected_sha256,
        )

        validate_plugin_zip(zip_path)

        self._plugin_manager.reload_plugins()
```

ただし、ここで重要な問題があります。Python は一度 import した module を `sys.modules` にキャッシュします。つまり、同じ module 名の plugin を差し替えても、次の import で新しい zip が読まれないことがあります。

たとえば、最初にこれを読みます。

```text
sample_plugin.zip
  sample_plugin/tools.py
```

次に同じ名前で更新します。

```text
sample_plugin.zip
  sample_plugin/tools.py  # 中身だけ変わった
```

この場合、`sample_plugin.tools` はすでに `sys.modules` に残っているので、単純な `importlib.import_module("sample_plugin.tools")` では古いものが使われる可能性があります。

なので、再起動なしで更新したいなら、**plugin の import 名を version ごとに変える**のが一番安全です。

```text
plugins/
  sample_plugin-0.1.0.zip
    sample_plugin_v0_1_0/
      tools.py

  sample_plugin-0.2.0.zip
    sample_plugin_v0_2_0/
      tools.py
```

`plugin.json` も version ごとに entrypoint を変えます。

```json
{
  "name": "sample_plugin",
  "version": "0.2.0",
  "entrypoint": "sample_plugin_v0_2_0.tools:register"
}
```

この方式なら、古い plugin と新しい plugin が Python 的に別 module になるので、backend を再起動しなくてもロードしやすいです。

逆に、毎回同じ package 名にするなら、

```text
sample_plugin.tools
```

を `sys.modules` から消して reload する必要があります。ただしこれは依存 module や内部状態が絡むと壊れやすいです。

```python
def unload_module_prefix(prefix: str) -> None:
    for name in list(sys.modules):
        if name == prefix or name.startswith(prefix + "."):
            del sys.modules[name]
```

これは開発中は便利ですが、本番用としてはあまりおすすめしません。

整理すると、選択肢はこうです。

| 方針                                   | 再起動 | 安全性 | コメント         |
| ------------------------------------ | --: | --: | ------------ |
| 新規 plugin だけ hot install             |  不要 |  高め | まずはこれでよい     |
| 同名 plugin を `sys.modules` 削除で reload |  不要 |  低め | 開発用ならあり      |
| versionごとに module 名を変える              |  不要 |  高め | 本番でも比較的扱いやすい |
| plugin 更新時は backend 再起動              |  必要 |  高い | 実装が一番簡単      |

あなたの用途なら、最初はこうするのがよいです。

```text
1. plugin install endpoint を作る
2. 新規 plugin は backend 再起動なしで読み込む
3. plugin 更新は version を変えて install する
4. 古い version は registry から無効化する
5. 完全削除や依存衝突が起きたら backend 再起動で整理する
```

つまり、**Webから plugin を追加するたびに backend 再起動は不要**です。ただし、同じ plugin を上書き更新する設計にすると Python の import cache で苦しくなるので、`plugin_name + version` を単位にして追加ロードし、registry だけ差し替える設計にするのがよいです。



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

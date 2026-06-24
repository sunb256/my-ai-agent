結論として、**tool が多いなら文脈に応じてフィルタリングする設計にしたほうがいい**です。全部送るのは PoC や小規模エージェントでは普通ですが、10個、20個、50個と増えると、LLMが「どれを使うべきか」を判断する負荷が上がり、誤った tool call・不要な tool call・回答品質低下が起きやすくなります。

これは感覚論だけではなく、LangChain の公式ドキュメントでも「tool が多すぎるとモデルを圧迫し、エラーが増える」「dynamic tool selection が有効」と説明されています。また、LangChain には「LLM tool selector」という、メインモデルに渡す前に関連 tool を選ぶ仕組みも用意されています。特に 10 個以上 tool があり、多くが各クエリに不要な場合に有効とされています。([LangChain Docs][1])

OpenAI 側でも、多数の関数や大きな schema がある場合は、まれに使う tool を遅延ロードする `tool_search` のような考え方が説明されています。これは「全 tool を毎回投げる」のではなく、必要なものだけを表に出す方向の設計です。([OpenAI デベロッパー][2])

自作エージェントなら、最初はこう考えるのがよいです。

```text
全 tool
  ↓
ToolRegistry に登録
  ↓
ユーザー入力・会話状態・現在フェーズ・権限・ファイル有無などで候補を絞る
  ↓
絞った tools だけを LLM に送る
  ↓
LLM が tool_call する
```

つまり、LLM に直接すべての tool を選ばせるのではなく、**LLM に渡す前にアプリ側で tool 候補を狭める**という設計です。

たとえば製造業向けエージェントなら、全部を一括で渡すのではなく、

```text
図面系:
- read_drawing
- extract_bom
- compare_revision

品質系:
- search_nonconformance
- create_8d_report
- check_inspection_result

ファイル系:
- read_file
- write_file
- list_files

コード実行系:
- exec_python
- run_shell

最終応答系:
- final_answer
```

のようにグループ化しておきます。

ユーザーが「このCSVを集計して」と言ったら、`read_file`, `exec_python`, `write_file` くらいを渡す。
「不具合報告書を作りたい」と言ったら、品質系とファイル系だけを渡す。
「図面の差分を見たい」と言ったら、図面系だけを渡す。
このほうが LLM の判断対象が減るので、かなり安定します。

実装としては、まず単純なルールベースで十分です。いきなりベクトル検索やLLMルーターにしなくていいです。

```python
from dataclasses import dataclass, field
from typing import Callable


@dataclass
class ToolMeta:
    name: str
    tool: object
    tags: set[str] = field(default_factory=set)
    always: bool = False
    enabled: Callable[[object], bool] | None = None


class ToolRegistry:
    def __init__(self):
        self._tools: dict[str, ToolMeta] = {}

    def register(self, meta: ToolMeta) -> None:
        self._tools[meta.name] = meta

    def all(self) -> list[ToolMeta]:
        return list(self._tools.values())


class ToolSelector:
    def __init__(self, registry: ToolRegistry, max_tools: int = 8):
        self.registry = registry
        self.max_tools = max_tools

    def select(self, ctx, user_text: str) -> list[object]:
        metas = [
            meta
            for meta in self.registry.all()
            if meta.enabled is None or meta.enabled(ctx)
        ]

        always = [m for m in metas if m.always]
        candidates = [m for m in metas if not m.always]

        selected = []

        text = user_text.lower()

        if any(word in text for word in ["csv", "集計", "計算", "分析"]):
            selected += self._by_tag(candidates, "data")

        if any(word in text for word in ["ファイル", "読む", "保存", "出力"]):
            selected += self._by_tag(candidates, "file")

        if any(word in text for word in ["図面", "bom", "部品表"]):
            selected += self._by_tag(candidates, "drawing")

        if any(word in text for word in ["不具合", "品質", "検査"]):
            selected += self._by_tag(candidates, "quality")

        # 重複除去
        result = []
        seen = set()

        for meta in always + selected:
            if meta.name in seen:
                continue
            seen.add(meta.name)
            result.append(meta)

        # 何も選ばれない場合は、汎用的な安全 tool だけ渡す
        if not result:
            result = always + self._by_tag(candidates, "general")

        return [meta.tool for meta in result[: self.max_tools]]

    def _by_tag(self, metas: list[ToolMeta], tag: str) -> list[ToolMeta]:
        return [meta for meta in metas if tag in meta.tags]
```

登録側はこういうイメージです。

```python
registry.register(ToolMeta(
    name="read_file",
    tool=read_file_tool,
    tags={"file", "general"},
    always=False,
))

registry.register(ToolMeta(
    name="write_file",
    tool=write_file_tool,
    tags={"file"},
))

registry.register(ToolMeta(
    name="exec_python",
    tool=exec_python_tool,
    tags={"data", "code"},
))

registry.register(ToolMeta(
    name="extract_bom",
    tool=extract_bom_tool,
    tags={"drawing", "manufacturing"},
))

registry.register(ToolMeta(
    name="create_8d_report",
    tool=create_8d_report_tool,
    tags={"quality", "manufacturing"},
))
```

そして LLM 呼び出し前にこうします。

```python
async def call_llm(self, request: Request) -> Response:
    messages = self._build_msgs(request)

    user_text = self._latest_user_text(request)
    selected_tools = self.tool_selector.select(request.ctx, user_text)

    response = await acompletion(
        model=self.model,
        messages=messages,
        tools=[tool.tool_def for tool in selected_tools],
        **({"tool_choice": request.tool_choice} if request.tool_choice else {}),
        **self.config,
    )

    return self._parse_response(response)
```

重要なのは、**tool filtering は LLM の代わりに tool を実行する仕組みではない**という点です。あくまで「LLM に見せる候補を絞る」だけです。最終的にどの tool を使うかは LLM に判断させる。ただし、候補数を減らして判断しやすくする、ということです。

もう少し発展させるなら、3段階にすると安定します。

```text
1. ルールで明らかに不要な tool を除外
2. 残った tool をタグ・フェーズ・権限で絞る
3. まだ多ければ、小さいLLMまたは分類器で上位N個を選ぶ
```

このとき、最初から「LLM に tool 一覧を渡して tool を選ばせる」方式にすると、結局その選択用 LLM にも大量の tool 説明を渡すことになります。なので選択用には詳細 schema ではなく、短いカタログだけ渡すのがよいです。

```text
read_file: ファイルを読む
write_file: ファイルへ保存する
exec_python: Pythonで計算・集計する
extract_bom: 図面や文書から部品表を抽出する
create_8d_report: 品質問題の8Dレポートを作る
```

選ばれた tool 名だけを受け取り、その後で本物の JSON schema を LLM に渡す、という流れです。

注意点もあります。絞りすぎると、LLM が本来必要な tool を使えなくなります。なので最初は `max_tools=8〜12` くらいにして、少し広めに残すのがよいです。また、`read_file` や `list_files` のような基礎 tool は多くのタスクで必要になるので、完全に除外しないほうが安定することがあります。

個人的には、今のあなたの実装なら、次の順番がよいと思います。

```text
第一段階:
ToolRegistry に tags / category / risk / enabled 条件を持たせる

第二段階:
LLM 呼び出し直前に ToolSelector を挟む

第三段階:
ログに「候補 tool」「実際に送った tool」「LLMが呼んだ tool」を出す

第四段階:
誤選択が多いカテゴリだけルールを足す
```

最初から高度なルーターを作るより、まずはこのくらいで十分です。

設計としては、こう分けるときれいです。

```text
agent-core/
  tools/
    registry.py        # 全toolの登録
    selector.py        # 文脈に応じたtool選択
    definitions.py     # 各tool定義
  llm/
    client.py          # LiteLLM呼び出し
  agent/
    runner.py          # agent loop
```

`AgentRunner` が直接 `self.tools` を全部持つのではなく、`ToolRegistry` と `ToolSelector` を通して取得する形にすると、後から Web UI で tool の有効/無効、プロファイル別 tool セット、ユーザー権限別 tool セットなどにも拡張しやすいです。

最終的な判断としては、**「全部送る」は小規模では普通、「文脈で絞る」は中規模以上ではかなり自然な設計**です。

[1]: https://docs.langchain.com/oss/python/langchain/agents?utm_source=chatgpt.com "Agents - Docs by LangChain"
[2]: https://developers.openai.com/api/docs/guides/function-calling "Function calling | OpenAI API"

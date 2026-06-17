
結論からいうと、**AI Agentにおける tool call とは、LLMが「この処理は自分の文章生成だけではなく、外部関数を呼ぶ必要がある」と判断し、呼び出すべき関数名と引数をJSONとして返す仕組み**です。重要なのは、**LLM自身が関数を実行するわけではない**ことです。実行するのはあなたのアプリケーション側です。OpenAIのドキュメントでも、function calling / tool calling は、モデルが外部システムや学習データ外の情報にアクセスするための仕組みとして説明されています。([オープンAIプラットフォーム][1])

たとえばユーザーがこう聞いたとします。

```text
今日の東京の天気は？
```

LLMは現在の天気を内部知識だけでは正確に答えられません。そこで、あなたが事前に `get_weather` というツールを渡しておくと、モデルは最終回答ではなく、まず次のような「関数呼び出し要求」を返します。

```json
{
  "type": "function_call",
  "name": "get_weather",
  "arguments": "{\"location\":\"Tokyo\",\"unit\":\"celsius\"}"
}
```

この時点では、まだ天気APIは呼ばれていません。あなたのAgent実装がこの `name` と `arguments` を読み取り、実際に `get_weather(location="Tokyo", unit="celsius")` を実行します。その結果を再びLLMに渡すと、LLMが人間向けの自然文に整形して最終回答を返します。OpenAIの説明でも、ツール呼び出しは「ツール候補を渡す → モデルからtool callを受け取る → アプリ側で実行する → 結果をモデルに戻す → 最終回答を得る」という複数ステップの会話として説明されています。([オープンAIプラットフォーム][1])

## 1. tool callの正体

OpenAI API的には、tool callはだいたい次の3要素です。

```json
{
  "name": "呼び出す関数名",
  "arguments": "JSON文字列の引数",
  "call_id": "この呼び出しを識別するID"
}
```

Responses APIでは、function tool call は `arguments`, `call_id`, `name`, `type` などを持ち、`arguments` は「関数に渡す引数のJSON文字列」とされています。([オープンAIプラットフォーム][2])

つまり、tool callはPythonでいうこの実行そのものではありません。

```python
get_weather("Tokyo", "celsius")
```

そうではなく、LLMから見るとこういう「実行してほしい」という依頼です。

```json
{
  "name": "get_weather",
  "arguments": {
    "location": "Tokyo",
    "unit": "celsius"
  }
}
```

この違いが一番大事です。

## 2. なぜAI Agentにtool callが必要なのか

LLM単体は、基本的には「文章を生成するモデル」です。なので、次のようなことは本来できません。

```text
現在時刻を取得する
DBを検索する
ファイルを読む
Pythonコードを実行する
メールを送る
注文をキャンセルする
社内APIを叩く
```

しかしAI Agentでは、LLMに「判断」をさせ、アプリ側に「実行」をさせたいわけです。そこでtool callを使います。

役割を分けるとこうです。

| 役割             | 担当     |
| -------------- | ------ |
| 何をすべきか判断する     | LLM    |
| どのツールを使うか選ぶ    | LLM    |
| 引数を作る          | LLM    |
| 実際に関数を実行する     | 自分のアプリ |
| 実行結果をもとに最終回答する | LLM    |

このため、tool callはAI Agentの中核です。Agentを自作する場合、実装の本質は「LLMのtool call出力を読み取り、対応するローカル関数を安全に実行し、その結果を再度LLMに渡すループ」になります。

## 3. OpenAI APIでのtools定義

OpenAI APIでは、モデルに対して「使ってよいツール一覧」を渡します。たとえば `get_current_weather` という関数を使わせたい場合、Responses APIでは次のように定義します。OpenAIのAPIリファレンスでも、`tools` はモデルがレスポンス生成中に呼び出せるツール配列で、function calls は開発者側が定義した関数をモデルが強く型付けされた引数で呼べる仕組みと説明されています。([オープンAIプラットフォーム][2])

```json
{
  "type": "function",
  "name": "get_current_weather",
  "description": "Get the current weather in a given location",
  "parameters": {
    "type": "object",
    "properties": {
      "location": {
        "type": "string",
        "description": "The city and state, e.g. San Francisco, CA"
      },
      "unit": {
        "type": "string",
        "enum": ["celsius", "fahrenheit"]
      }
    },
    "required": ["location", "unit"]
  }
}
```

ここで重要なのは、`parameters` が **JSON Schema** になっていることです。これはモデルに対して、「この関数はこういう引数を受け取る」という型情報を渡しているイメージです。

Python関数で書くと、対応関係はこうです。

```python
def get_current_weather(location: str, unit: str) -> dict:
    ...
```

これをLLMに直接渡すのではなく、APIにはJSON Schemaとして渡します。

## 4. 最小の流れ

OpenAI APIのtool callは、概念的にはこの流れです。

```text
User
  ↓
Agent
  ↓ tools付きでLLMへリクエスト
LLM
  ↓ tool_callを返す
Agent
  ↓ tool_call.name と arguments を見て関数実行
Tool / Function
  ↓ 実行結果
Agent
  ↓ tool resultをLLMへ返す
LLM
  ↓ 最終回答
User
```

具体例で見るとこうです。

### 1回目のリクエスト

```json
{
  "model": "gpt-5.5",
  "input": "東京の天気を教えて",
  "tools": [
    {
      "type": "function",
      "name": "get_weather",
      "description": "Get current weather by location",
      "parameters": {
        "type": "object",
        "properties": {
          "location": { "type": "string" },
          "unit": {
            "type": "string",
            "enum": ["celsius", "fahrenheit"]
          }
        },
        "required": ["location", "unit"]
      }
    }
  ],
  "tool_choice": "auto"
}
```

`tool_choice: "auto"` は、モデルに「ツールを使うかどうか自分で判断してよい」と伝える設定です。OpenAIのドキュメントでは、`auto` は0個、1個、または複数の関数呼び出しをモデルが選べる既定動作として説明されています。([オープンAIプラットフォーム][1])

### モデルからの返答

```json
{
  "output": [
    {
      "type": "function_call",
      "call_id": "call_abc123",
      "name": "get_weather",
      "arguments": "{\"location\":\"Tokyo\",\"unit\":\"celsius\"}",
      "status": "completed"
    }
  ]
}
```

ここであなたのAgentは、こう処理します。

```python
args = json.loads(item.arguments)

result = get_weather(
    location=args["location"],
    unit=args["unit"],
)
```

### 2回目のリクエスト

実行結果をLLMに返します。Responses APIでは `function_call_output` として `call_id` に紐づけて返します。OpenAIの例でも、`function_call` を受け取ったあと、アプリ側で関数を実行し、`type: "function_call_output"`、`call_id`、`output` を入力に追加して再度モデルに渡す形になっています。([オープンAIプラットフォーム][1])

```json
{
  "model": "gpt-5.5",
  "input": [
    {
      "role": "user",
      "content": "東京の天気を教えて"
    },
    {
      "type": "function_call",
      "call_id": "call_abc123",
      "name": "get_weather",
      "arguments": "{\"location\":\"Tokyo\",\"unit\":\"celsius\"}"
    },
    {
      "type": "function_call_output",
      "call_id": "call_abc123",
      "output": "{\"temperature\": 28, \"unit\": \"celsius\", \"condition\": \"cloudy\"}"
    }
  ],
  "tools": [
    {
      "type": "function",
      "name": "get_weather",
      "description": "Get current weather by location",
      "parameters": {
        "type": "object",
        "properties": {
          "location": { "type": "string" },
          "unit": { "type": "string" }
        },
        "required": ["location", "unit"]
      }
    }
  ]
}
```

するとモデルは最終的にこう返します。

```text
東京の現在の天気は曇りで、気温は28℃です。
```

## 5. Chat Completions APIの場合

あなたが使っているLiteLLMの `acompletion(...)` は、基本的にはChat Completions互換の形に近いです。この場合は `messages` と `tools` を渡し、モデルの返答に `message.tool_calls` が入ります。OpenAIのChat Completions例でも、`tools` を渡して1回目の応答を受け取り、`response.choices[0].message.tool_calls` を処理し、結果を `role: "tool"` のメッセージとして `tool_call_id` 付きで追加してから、再度 `chat.completions.create` を呼ぶ流れになっています。([オープンAIプラットフォーム][1])

イメージはこうです。

```python
from openai import OpenAI
import json

client = OpenAI()

tools = [
    {
        "type": "function",
        "function": {
            "name": "get_weather",
            "description": "Get current weather by location",
            "parameters": {
                "type": "object",
                "properties": {
                    "location": {"type": "string"},
                    "unit": {
                        "type": "string",
                        "enum": ["celsius", "fahrenheit"],
                    },
                },
                "required": ["location", "unit"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
]

messages = [
    {"role": "user", "content": "東京の天気を教えて"}
]

response = client.chat.completions.create(
    model="gpt-5.5",
    messages=messages,
    tools=tools,
)

assistant_message = response.choices[0].message
messages.append(assistant_message)

for tool_call in assistant_message.tool_calls or []:
    if tool_call.function.name == "get_weather":
        args = json.loads(tool_call.function.arguments)

        result = get_weather(
            location=args["location"],
            unit=args["unit"],
        )

        messages.append(
            {
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            }
        )

final_response = client.chat.completions.create(
    model="gpt-5.5",
    messages=messages,
    tools=tools,
)

print(final_response.choices[0].message.content)
```

このコードでやっていることは、ほぼ次のループです。

```python
while True:
    response = call_llm(messages, tools)

    if response has tool_calls:
        for tool_call in tool_calls:
            result = execute_tool(tool_call)
            messages.append(tool_result_message)
        continue

    return response.content
```

つまりAgent実装では、`call_llm` だけではなく、**tool callを検出して実行する制御ループ**が必要になります。

## 6. 自作Agentでの実装イメージ

あなたのように自前Agentを作るなら、内部構造はだいたいこうなります。

```python
class Agent:
    def __init__(self, llm, tools):
        self.llm = llm
        self.tools = {tool.name: tool for tool in tools}

    async def run(self, user_input: str):
        messages = [
            {"role": "user", "content": user_input}
        ]

        while True:
            response = await self.llm.call(
                messages=messages,
                tools=[tool.tool_def for tool in self.tools.values()],
            )

            message = response.message
            messages.append(message)

            if not message.tool_calls:
                return message.content

            for tool_call in message.tool_calls:
                tool_name = tool_call.function.name
                args = json.loads(tool_call.function.arguments)

                tool = self.tools[tool_name]
                result = await tool.exec(**args)

                messages.append(
                    {
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps(result, ensure_ascii=False),
                    }
                )
```

ここで `tool.tool_def` がOpenAI APIに渡すJSON Schemaです。

```python
{
    "type": "function",
    "function": {
        "name": "read_file",
        "description": "Read a file from local workspace",
        "parameters": {
            "type": "object",
            "properties": {
                "path": {"type": "string"}
            },
            "required": ["path"],
            "additionalProperties": False
        },
        "strict": True
    }
}
```

実体のPython関数は別にあります。

```python
async def read_file(path: str) -> str:
    with open(path, encoding="utf-8") as f:
        return f.read()
```

この2つを対応づけるのが、自作Agentのtool registryです。

```python
tools = {
    "read_file": read_file,
    "write_file": write_file,
    "exec_python": exec_python,
}
```

## 7. tool callと普通のチャットの違い

普通のチャットでは、LLMはそのまま文章を返します。

```json
{
  "role": "assistant",
  "content": "東京の天気は..."
}
```

tool callでは、LLMは文章ではなく「関数を呼んでください」という構造化データを返します。

```json
{
  "role": "assistant",
  "tool_calls": [
    {
      "id": "call_xxx",
      "type": "function",
      "function": {
        "name": "get_weather",
        "arguments": "{\"location\":\"Tokyo\"}"
      }
    }
  ]
}
```

なのでAgent側では、assistant messageを受け取ったら必ず次を判定します。

```python
if message.tool_calls:
    # ツール実行フェーズ
else:
    # 最終回答フェーズ
```

この判定がないと、tool call対応Agentにはなりません。

## 8. `tool_choice` の意味

`tool_choice` は、モデルにツール利用をどの程度任せるかの設定です。OpenAIのドキュメントでは、`auto`、`required`、特定関数の強制、使用可能ツールの制限、`none` などが説明されています。([オープンAIプラットフォーム][1])

よく使うのはこの3つです。

| 設定         | 意味              |
| ---------- | --------------- |
| `auto`     | モデルが使うかどうか判断する  |
| `required` | 必ず1つ以上のツールを呼ばせる |
| `none`     | ツールを呼ばせない       |

たとえば、通常のAgentでは `auto` が自然です。

```python
response = await acompletion(
    model=self.model,
    messages=msgs,
    tools=tools,
    tool_choice="auto",
)
```

一方、必ずJSON変換ツールを使わせたい、必ず検索させたい、という場面では `required` や特定ツール強制を使います。

## 9. `strict: true` の意味

`strict: true` は、モデルがJSON Schemaにより正確に従うようにする設定です。OpenAIは、関数呼び出しがスキーマに確実に従うようにするため、`strict: true` を有効にすることを推奨しています。([オープンAIプラットフォーム][1])

ただし、strict modeでは制約があります。OpenAIの説明では、`parameters` 内の各objectに `additionalProperties: false` が必要で、`properties` の全フィールドは `required` に含める必要があります。任意項目は `type` に `null` を含めて表現します。([オープンAIプラットフォーム][1])

たとえば任意項目を表現したい場合はこうです。

```json
{
  "type": "object",
  "properties": {
    "location": {
      "type": "string"
    },
    "unit": {
      "type": ["string", "null"],
      "enum": ["celsius", "fahrenheit", null]
    }
  },
  "required": ["location", "unit"],
  "additionalProperties": false
}
```

Python側の感覚ではこうです。

```python
def get_weather(location: str, unit: str | None) -> dict:
    ...
```

`required` に入っているからといって、値が必ず実質的に存在するというより、「キーは必ず存在する。ただし値はnullでもよい」と考えるとわかりやすいです。

## 10. 複数tool call

モデルは1回の応答で複数の関数を呼ぶことがあります。OpenAIのドキュメントでも、モデルが1ターンで複数関数を呼ぶ可能性があり、`parallel_tool_calls: false` にすると0個または1個に制限できると説明されています。([オープンAIプラットフォーム][1])

たとえばユーザーがこう言った場合です。

```text
東京と大阪の天気を比較して
```

モデルはこう返す可能性があります。

```json
[
  {
    "name": "get_weather",
    "arguments": "{\"location\":\"Tokyo\",\"unit\":\"celsius\"}"
  },
  {
    "name": "get_weather",
    "arguments": "{\"location\":\"Osaka\",\"unit\":\"celsius\"}"
  }
]
```

Agent側では、すべてのtool callを実行し、それぞれの結果を `tool_call_id` に紐づけて返す必要があります。

## 11. tool callで注意するべきこと

一番大事なのは、**LLMが出したtool callをそのまま信用してはいけない**ことです。モデルは「この関数をこの引数で呼んで」と提案しているだけです。実行権限を持つのはアプリ側なので、必ず検証・制限を入れます。

特に危険なのは次です。

```text
ファイル削除
シェル実行
外部HTTPリクエスト
メール送信
DB更新
決済・返金
個人情報アクセス
```

たとえば `exec_shell` みたいなツールを作る場合、モデルがこういう引数を出す可能性があります。

```json
{
  "cmd": "rm -rf /"
}
```

なので、Agent側では以下が必要です。

```python
if tool_name not in allowed_tools:
    raise ValueError("unknown tool")

args = validate_args(tool_schema, raw_args)

if tool_name == "exec_shell":
    validate_command_is_safe(args["cmd"])

result = execute_tool(tool_name, args)
```

LLMに「危険なことはしないで」と言うだけでは不十分です。実行前にアプリ側で止める設計が必要です。

## 12. 自作Agentでの最小構成

自作Agentのtool call対応に必要な部品は、最小でこれです。

```text
1. Tool定義
   - name
   - description
   - parameters(JSON Schema)
   - 実行関数

2. Tool registry
   - name → 実行関数 の対応表

3. LLM呼び出し
   - messages
   - tools

4. Tool call parser
   - tool_callsを読む
   - argumentsをJSON parseする

5. Executor
   - 対応する関数を実行
   - 例外処理する
   - 結果をJSON/textにする

6. Loop
   - tool resultをmessagesに追加
   - 再度LLMに渡す
   - tool_callsがなくなったら終了
```

コード上はこの形に集約されます。

```python
async def run_agent(user_input: str) -> str:
    messages = [{"role": "user", "content": user_input}]

    for _ in range(max_steps):
        response = await call_llm(messages, tools)

        assistant_message = response.choices[0].message
        messages.append(assistant_message)

        if not assistant_message.tool_calls:
            return assistant_message.content

        for tool_call in assistant_message.tool_calls:
            result = await execute_tool_call(tool_call)

            messages.append(
                {
                    "role": "tool",
                    "tool_call_id": tool_call.id,
                    "content": json.dumps(result, ensure_ascii=False),
                }
            )

    raise RuntimeError("max steps exceeded")
```

この `max_steps` も重要です。ツール呼び出しが連鎖して無限ループになることがあるので、Agentには必ずステップ上限を入れます。

## 13. まとめ

tool callとは、**LLMに外部処理を直接実行させる仕組みではなく、LLMに「どの関数をどんな引数で呼ぶべきか」を構造化JSONで提案させる仕組み**です。OpenAI APIでは、開発者が `tools` に関数定義を渡し、モデルが必要に応じて `function_call` / `tool_calls` を返し、アプリ側がそれを実行し、結果をLLMへ戻します。

自作AI Agentとして見ると、tool callの本質はこの1行です。

```text
LLMの判断を、アプリケーション側の実処理に接続するためのプロトコル
```

なので、Agentの実装では `call_llm()` よりも、むしろ次の部分が本体になります。

```text
tool定義を作る
tool_callを検出する
引数を検証する
実関数を実行する
結果をLLMに戻す
最終回答までループする
```

この理解で見ると、AI Agentは「LLM + tool registry + execution loop」で構成されている、と考えるとかなり整理しやすいです。

[1]: https://platform.openai.com/docs/guides/function-calling "Function calling | OpenAI API"
[2]: https://platform.openai.com/docs/api-reference/responses/create "Create a model response | OpenAI API Reference"


-----



結論は、**通常回答が来たあとに無理やりtool_callへ誘導する設計ではなく、最初から「このフェーズでは通常回答を許可しない」設計にするのがよい**です。つまり、Agentのループを「LLMに自由に返答させる場」ではなく、**状態ごとに許可される出力形式を制御する実行ループ**として作ります。

OpenAI APIでは、デフォルトの `tool_choice: "auto"` は「0個、1個、または複数の関数呼び出しをモデルが選べる」動作です。一方で `tool_choice: "required"` にすると、1つ以上の関数呼び出しを要求できます。さらに特定関数だけを強制することもできます。つまり、モデルに「必要ならtool_callしてね」とお願いするだけでなく、APIパラメータ側で「このターンはtool_callを返すこと」と制約できます。([OpenAI Developers][1])

なので、自作Agentではこう考えるのがよいです。

```text
悪い設計:
  tool_choice="auto" で投げる
  ↓
  通常メッセージが返る
  ↓
  文面を見て「ツール呼んで」と再依頼する

よい設計:
  このステップは行動フェーズだとAgent側が決める
  ↓
  tool_choice="required" で投げる
  ↓
  tool_call以外はプロトコル違反として扱う
```

ここで重要なのは、**LLMに「使えるツールは何ですか？」と聞かせないこと**です。ツール一覧はAPIリクエストの `tools` に渡しているので、モデルはユーザーに聞くべきではありません。OpenAIのfunction callingも、アプリケーションがツール定義を渡し、モデルが必要に応じてtool callを返し、アプリ側が実行して結果を戻す複数ステップの会話として説明されています。([OpenAI Developers][1])

## 汎用Agentでは「制御用ツール」を用意する

一番実装しやすい設計は、業務ツールとは別に、**制御用ツール**を用意することです。

たとえば、普通のツールはこうです。

```text
read_file
write_file
search_docs
exec_python
send_email
query_database
```

それとは別に、Agent制御用にこういうツールを用意します。

```text
final_answer    # ユーザーに最終回答する
ask_user        # 情報不足なのでユーザーに質問する
```

つまり、LLMにとっての出力を全部tool_call化します。

```text
ファイルを読む必要がある → read_file tool_call
DB検索が必要 → query_database tool_call
情報不足 → ask_user tool_call
完了 → final_answer tool_call
```

この設計にすると、Agentループ側はかなり単純になります。

```python
while step < max_steps:
    response = call_llm(
        messages=messages,
        tools=domain_tools + control_tools,
        tool_choice="required",
    )

    tool_calls = response.tool_calls

    if not tool_calls:
        # このフェーズでは通常回答は禁止
        # 1回だけrepairするか、エラーにする
        continue

    for tool_call in tool_calls:
        if tool_call.name == "final_answer":
            return tool_call.arguments["answer"]

        if tool_call.name == "ask_user":
            return NeedUserInput(tool_call.arguments["question"])

        result = execute_tool(tool_call)
        messages.append(tool_result_message(tool_call.id, result))
```

この考え方だと、通常のassistant messageはほぼ使いません。**最終回答すら `final_answer` というtool_callとして返させる**わけです。

これが汎用Agentではかなり強いです。なぜなら、Agent側が扱う出力種類を次の4つ程度に固定できるからです。

```text
1. domain tool call
2. final_answer
3. ask_user
4. error / max_steps
```

自然文の「わかりました。ツールを教えてください」みたいな曖昧な出力を、Agentの制御フローに入れなくて済みます。

## `final_answer` をtoolにする理由

普通は「tool_callがなければ最終回答」と考えがちです。ただ、それだと今回の問題が起きます。

```text
本当はツールを呼んでほしい
でもモデルが通常回答してしまった
これを最終回答扱いしてよいのか？
それともリトライすべきか？
```

この判定が曖昧になります。

そこで、最終回答も明示的なアクションにします。

```json
{
  "name": "final_answer",
  "arguments": {
    "answer": "処理が完了しました。..."
  }
}
```

こうすると、Agent側はこう判断できます。

```python
if tool_name == "final_answer":
    return args["answer"]
```

「tool_callがないから終了」ではなく、**`final_answer` が呼ばれたから終了**です。このほうがループ設計が安定します。

## `ask_user` もtoolにする理由

`tool_choice="required"` を使うと、情報不足のときにモデルが無理やり引数を作る危険があります。たとえば「山田さんにメール送って」と言われたが、宛先も本文も不明な場合です。

ここで `send_email` を強制すると、モデルが適当なメールアドレスや本文を作る可能性があります。なので、必ず逃げ道として `ask_user` を用意します。

```json
{
  "name": "ask_user",
  "arguments": {
    "question": "送信先のメールアドレスと本文を教えてください。",
    "reason": "メール送信に必要な情報が不足しています。"
  }
}
```

つまり、`tool_choice="required"` を使う場合は、**実行ツールだけでなく、情報不足を表現するツールも必要**です。

OpenAIのstrict modeでは、関数呼び出しがスキーマに従いやすくなりますが、各objectで `additionalProperties: false` が必要で、`properties` の全フィールドを `required` に含める必要があります。任意項目は `null` を型に含めて表現します。([OpenAI Developers][1])

## ツール定義の例

たとえば制御用ツールはこう定義できます。

```python
control_tools = [
    {
        "type": "function",
        "function": {
            "name": "final_answer",
            "description": "Return the final answer to the user when the task is complete.",
            "parameters": {
                "type": "object",
                "properties": {
                    "answer": {
                        "type": "string",
                        "description": "Final response shown to the user.",
                    }
                },
                "required": ["answer"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
    {
        "type": "function",
        "function": {
            "name": "ask_user",
            "description": (
                "Ask the user for missing information required to continue. "
                "Use this instead of guessing tool arguments."
            ),
            "parameters": {
                "type": "object",
                "properties": {
                    "question": {
                        "type": "string",
                        "description": "Question to ask the user.",
                    },
                    "reason": {
                        "type": "string",
                        "description": "Why this information is required.",
                    },
                },
                "required": ["question", "reason"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    },
]
```

ドメインツールは別に定義します。

```python
domain_tools = [
    {
        "type": "function",
        "function": {
            "name": "read_file",
            "description": "Read a file from the workspace.",
            "parameters": {
                "type": "object",
                "properties": {
                    "path": {"type": "string"},
                },
                "required": ["path"],
                "additionalProperties": False,
            },
            "strict": True,
        },
    }
]
```

そして、Agent実行中はこうします。

```python
response = await acompletion(
    model=self.model,
    messages=messages,
    tools=domain_tools + control_tools,
    tool_choice="required",
)
```

この場合、モデルは `read_file`、`final_answer`、`ask_user` のどれかを必ず呼ぶことになります。

## ただし、常に全部のツールを許可しない

実運用では、毎ターンすべてのツールを渡すより、**状態に応じてallowed toolsを絞る**ほうがよいです。OpenAIのドキュメントでも、`tool_choice` で特定ツールを強制したり、使用可能ツールをサブセットに制限できることが説明されています。([OpenAI Developers][1])

たとえば、状態ごとにこうします。

```text
初回判断フェーズ:
  許可: search_docs, read_file, ask_user
  禁止: final_answer

ツール実行後:
  許可: search_docs, read_file, final_answer, ask_user

危険操作前:
  許可: request_approval, ask_user
  禁止: send_email, delete_file など直接実行系

最終化フェーズ:
  許可: final_answer
```

この設計にすると、モデルが早すぎる最終回答をすることを防げます。

たとえば、ファイルを読まないと答えられないタスクなら、最初のターンでは `final_answer` を渡さない。そうすると、モデルは `read_file` か `ask_user` を選ぶしかありません。

## ループ設計の具体例

汎用Agentとしては、このくらいの構造が扱いやすいです。

```python
async def run(self, user_input: str) -> str:
    messages = [
        {
            "role": "system",
            "content": (
                "You are an agent. In action mode, do not answer directly. "
                "Use the provided tools. If information is missing, call ask_user. "
                "When the task is complete, call final_answer."
            ),
        },
        {"role": "user", "content": user_input},
    ]

    ctx = AgentContext(
        step=0,
        has_observation=False,
        waiting_approval=False,
    )

    for _ in range(self.max_steps):
        tools = self.select_tools(ctx)

        response = await self.llm.call(
            messages=messages,
            tools=tools,
            tool_choice="required",
        )

        message = response.choices[0].message
        tool_calls = message.tool_calls or []

        if not tool_calls:
            repaired = await self.repair_no_tool_call(messages, tools)
            tool_calls = repaired.tool_calls or []

            if not tool_calls:
                raise RuntimeError("model did not return a tool call")

        messages.append(message)

        for tool_call in tool_calls:
            name = tool_call.function.name
            args = json.loads(tool_call.function.arguments)

            if name == "final_answer":
                if not self.can_finish(ctx):
                    messages.append({
                        "role": "tool",
                        "tool_call_id": tool_call.id,
                        "content": json.dumps({
                            "error": "Cannot finish yet. Required tool evidence is missing."
                        }, ensure_ascii=False),
                    })
                    continue

                return args["answer"]

            if name == "ask_user":
                return args["question"]

            result = await self.execute_tool(name, args)
            ctx.has_observation = True

            messages.append({
                "role": "tool",
                "tool_call_id": tool_call.id,
                "content": json.dumps(result, ensure_ascii=False),
            })

    raise RuntimeError("max steps exceeded")
```

ポイントは、`message.content` を見て「これは本当に最終回答かな？」と悩まないことです。**終了条件は `final_answer` tool_call** に寄せます。

## 通常回答が来た場合はどうするか

設計上は、通常回答が来たら次のどちらかです。

```text
1. そのフェーズで通常回答を許可している
   → final responseとして扱う

2. そのフェーズで通常回答を許可していない
   → プロトコル違反としてrepairする
```

repairは汎用的に1回だけでよいです。

```python
async def repair_no_tool_call(self, messages, tools):
    repair_messages = [
        *messages,
        {
            "role": "user",
            "content": (
                "The previous response was not valid for this agent step. "
                "Return exactly one tool call. Do not answer in natural language. "
                "If you need missing information, call ask_user. "
                "If the task is complete, call final_answer."
            ),
        },
    ]

    return await self.llm.call(
        messages=repair_messages,
        tools=tools,
        tool_choice="required",
    )
```

ここで大事なのは、**通常回答の文面をルールベースで分類しない**ことです。

```text
「わかりました」が含まれていたらリトライ
「ツール」が含まれていたらリトライ
「できません」が含まれていたら...
```

こういう一品ものにしない。代わりに、Agentの状態として「今はtool_call必須」と決め、その契約に違反したらrepairする。これは汎用設計です。

## plannerを入れる場合

もう少し高度にするなら、最初にplannerを置きます。

```text
User request
  ↓
Planner
  ↓
必要なツール種別、情報不足、危険操作の有無を判定
  ↓
Executor loop
  ↓
Finalizer
```

plannerの出力も自然文ではなく、構造化します。

```json
{
  "requires_tool": true,
  "allowed_tools": ["read_file", "search_docs"],
  "missing_information": [],
  "risk_level": "low"
}
```

このplannerは、特定の「メールならこう」「ファイルならこう」という個別ルールではなく、**現在のリクエストに対してどのツール群を開放するかを決める汎用ルーター**です。

構成としてはこうです。

```text
Planner:
  何をするべきか決める
  どのツール群を開放するか決める
  不足情報があるか決める

Executor:
  tool_choice="required" で実際のtool_callを出させる
  toolを実行する

Finalizer:
  tool結果をもとにfinal_answerさせる
```

小さく始めるなら、plannerを最初から複雑にしなくてもよいです。まずは `tool_choice="required"` + `final_answer` + `ask_user` の設計だけでかなり安定します。

## 実装上の推奨形

あなたの自作Agentなら、最初はこの形がよいと思います。

```text
1. toolsには業務ツール + control toolを入れる
   - read_file
   - write_file
   - exec_python
   - final_answer
   - ask_user

2. Agentループでは原則 tool_choice="required"

3. 通常assistant messageは最終回答扱いしない

4. final_answer tool_call が出たら終了

5. ask_user tool_call が出たらユーザーに確認

6. tool_callがない場合は1回だけrepair

7. max_stepsで必ず止める

8. 危険操作は直接実行せず approval tool を挟む
```

この設計だと、LLMは自由な会話相手ではなく、Agent runtimeに対して次のアクションを返す「意思決定器」になります。

要するに、汎用Agentで重要なのは **「通常回答が来たらどう解析するか」ではなく、「通常回答が来てはいけない状態を作ること」** です。

最終的な設計イメージはこうです。

```text
LLMに自由回答させる:
  不安定
  tool_callするかどうかがモデル任せ
  通常回答の扱いに困る

LLMに次アクションを選ばせる:
  安定
  tool_call / ask_user / final_answer に統一
  Agentループが単純になる
```

なので、自作Agentでは `tool_choice="auto"` を基本にするより、**Agent実行中は `tool_choice="required"` を基本にして、最終回答も `final_answer` という制御用toolで表現する**のが一番わかりやすいです。

[1]: https://developers.openai.com/api/docs/guides/function-calling "Function calling | OpenAI API"


-----

理解はかなり合っています。ただし、少しだけ補正すると、**`final_response` / `final_answer` が来た後に、必ずもう一度LLMに回答を考えさせるわけではありません**。

おすすめはまずこの理解です。

```text
基本のAgentループ:
  LLMには原則 tool_call を返させる

途中:
  read_file / search / exec_python などを呼ぶ

完了時:
  final_answer tool_call を返させる

Agent側:
  final_answer.arguments["answer"] をそのままユーザーに返す
```

つまり、`final_answer` は本物の外部ツールというより、**「これでユーザーに返してよい」という終了シグナル兼、最終回答の入れ物**です。

たとえばモデルが最後にこう返します。

```json
{
  "tool_calls": [
    {
      "id": "call_xxx",
      "type": "function",
      "function": {
        "name": "final_answer",
        "arguments": "{\"answer\":\"ファイルを確認したところ、設定値は `debug=true` になっていました。\"}"
      }
    }
  ]
}
```

この場合、Agent側は `final_answer` を実行するのではなく、こう扱います。

```python
if tool_name == "final_answer":
    return args["answer"]
```

なので、**`final_answer` が来た後にもう一度LLMへ投げる必要は基本ありません**。

---

ただし、設計パターンは2つあります。

## パターンA: `final_answer` に最終回答を入れさせる

これが一番シンプルです。

```text
User
  ↓
LLM: read_file tool_call
  ↓
Agent: read_file 実行
  ↓
LLM: final_answer tool_call
  ↓
Agent: answer を取り出して返す
```

実装イメージはこうです。

```python
for _ in range(max_steps):
    response = await call_llm(
        messages=messages,
        tools=tools + [final_answer_tool, ask_user_tool],
        tool_choice="required",
    )

    message = response.choices[0].message
    messages.append(message)

    for tool_call in message.tool_calls or []:
        name = tool_call.function.name
        args = json.loads(tool_call.function.arguments)

        if name == "final_answer":
            return args["answer"]

        if name == "ask_user":
            return args["question"]

        result = await execute_tool(name, args)

        messages.append({
            "role": "tool",
            "tool_call_id": tool_call.id,
            "content": json.dumps(result, ensure_ascii=False),
        })
```

この場合、`final_answer` の `answer` 自体が、すでにユーザー向けの文章です。

```python
final_answer({
    "answer": "確認したところ、設定ファイルには `model=gpt-4.1` が指定されています。"
})
```

この設計では、**最後の自然文生成もLLMが `final_answer` の引数として行う**ということです。

---

## パターンB: `finalize` は終了シグナルだけにして、その後に最終回答を別LLMで作る

もう1つの設計として、`final_response` / `finalize` toolには「回答素材」だけを入れさせて、その後に別ステップで自然文を作らせる方法もあります。

```text
User
  ↓
LLM: tool_call
  ↓
Agent: tool実行
  ↓
LLM: final_response tool_call
  ↓
Agent: その内容をもとに、別のLLM呼び出しで最終回答を整形
  ↓
User
```

たとえば最後のtool_callをこうします。

```json
{
  "name": "final_response",
  "arguments": {
    "facts": [
      "設定ファイル config.yaml を確認した",
      "model は gpt-4.1",
      "temperature は 0.2"
    ],
    "answer_type": "explanation"
  }
}
```

その後にAgent側で、別途こう投げます。

```python
final_messages = [
    {
        "role": "system",
        "content": "以下の事実だけを使って、ユーザー向けに簡潔に回答してください。",
    },
    {
        "role": "user",
        "content": json.dumps(args, ensure_ascii=False),
    },
]

final = await call_llm(
    messages=final_messages,
    tools=[],
)

return final.choices[0].message.content
```

ただし、このパターンは一段複雑になります。コストも増えますし、最終整形時に事実からズレる可能性もあるので、最初はあまりおすすめしません。

---

## 自作Agentなら、まずはパターンAでよいです

あなたの理解に近い形で書くと、こうです。

```text
基本:
  ほぼすべて tool_call にする

途中のtool_call:
  実際の処理をする
  read_file / write_file / exec_python / search_docs など

最後のtool_call:
  final_answer を呼ばせる
  これは実処理ではなく、終了シグナル

ユーザーへの回答:
  final_answer.arguments["answer"] をそのまま返す
```

つまり、`final_answer` はこういう位置づけです。

```text
read_file       → 実ツール
write_file      → 実ツール
exec_python     → 実ツール
ask_user        → 制御ツール
final_answer    → 制御ツール
```

`final_answer` は「外部処理を実行するツール」ではなく、**Agent runtimeに対する終了命令**です。

---

実装上は、通常回答を終了条件にしないほうが安定します。

```python
# あまりおすすめしない
if not message.tool_calls:
    return message.content
```

おすすめはこうです。

```python
# おすすめ
if tool_name == "final_answer":
    return args["answer"]
```

これだと、終了条件が明確になります。

---

なので、最終的な理解はこうです。

```text
「final_response が来た後に回答を考えさせる」
  → 場合によってはあり

「final_answer tool_call の中に、すでにユーザー向け回答を入れさせる」
  → まずはこちらが基本
```

自作Agentの最小構成では、**`final_answer` の引数にユーザー向け回答を含めさせて、それをそのまま返す**でよいです。

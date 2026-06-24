結論として、Human in the loop は **「エージェントがユーザに聞き返す通常会話」** と **「エージェント実行を一時停止して、承認・選択・入力を待つ中断処理」** を分けて考えるのがよいです。

今回あなたが言っている「選択入力を促す」は、後者の **interrupt / resume 型**で設計するときれいです。assistant-ui でも tool は user input や approval のために実行を pause できる考え方があり、`human()` / `resume()` や tool UI を使う方向のドキュメントがあります。OpenAI Agents SDK でも、承認が必要な tool call で run を pause し、`interruptions` を返して、同じ `RunState` から resume する設計が説明されています。つまり、一般的にも **一時停止して再開する** 形が自然です。([assistant-ui][1])

全体像はこうです。

```text id="luf6gp"
ユーザ入力
  ↓
agent.run_agent_stream()
  ↓
途中でユーザ判断が必要になる
  ↓
human_input_requested イベントを yield
  ↓
FastAPI が stream で frontend へ返す
  ↓
React / assistant-ui が選択UIを表示
  ↓
ユーザが「承認」「却下」「A案」「B案」などを選ぶ
  ↓
/api/runs/{run_id}/resume に送る
  ↓
保存していた agent state から再開
  ↓
最終回答を stream
```

重要なのは、Web UIでは **同じHTTPリクエストを開いたまま何分もユーザ入力を待つ設計にしない** ことです。技術的にはできますが、実装・タイムアウト・再接続・画面リロードが面倒になります。おすすめは、ユーザ入力が必要になった時点で `interrupted` として一度 stream を終え、state を保存し、ユーザ操作後に `resume` API で再開する方式です。

---

## 1. AgentEvent に human_input_requested を追加する

まず agent-core 側のイベントに、人間入力要求を追加します。

```python id="4j3axl"
from dataclasses import dataclass, field
from typing import Any, Literal


AgentEventType = Literal[
    "status",
    "tool_call_started",
    "tool_call_finished",
    "answer_delta",
    "human_input_requested",
    "interrupted",
    "error",
    "done",
]


@dataclass(frozen=True)
class AgentEvent:
    type: AgentEventType
    message: str | None = None
    data: dict[str, Any] = field(default_factory=dict)
```

たとえば、メール送信前にユーザ承認を取りたい場合はこうです。

```python id="nrqqfd"
yield AgentEvent(
    type="human_input_requested",
    message="このメールを送信してよいですか？",
    data={
        "request_id": approval_request_id,
        "kind": "confirmation",
        "title": "メール送信の確認",
        "detail": {
            "to": "customer@example.com",
            "subject": "見積書の送付",
            "body_preview": "お世話になっております。見積書を送付いたします...",
        },
        "options": [
            {"id": "approve", "label": "送信する"},
            {"id": "reject", "label": "送信しない"},
            {"id": "edit", "label": "内容を修正する"},
        ],
    },
)

yield AgentEvent(
    type="interrupted",
    message="ユーザの判断待ちです",
    data={
        "request_id": approval_request_id,
    },
)

return
```

ここで `return` するのがポイントです。agent は一度止まります。ユーザが選んだら、別APIから再開します。

---

## 2. run state を保存する

interrupt / resume 型にするなら、agent の途中状態を保存する必要があります。最初はDBではなくインメモリでも理解できます。

```python id="70aa5s"
from dataclasses import dataclass
from typing import Any


@dataclass
class PendingRun:
    run_id: str
    ctx: ExecContext
    req: Request
    pending_request_id: str
    resume_point: str
    data: dict[str, Any]


pending_runs: dict[str, PendingRun] = {}
```

`human_input_requested` を出す直前に保存します。

```python id="xgkcch"
pending_runs[run_id] = PendingRun(
    run_id=run_id,
    ctx=ctx,
    req=req,
    pending_request_id=approval_request_id,
    resume_point="send_email_approval",
    data={
        "tool_call": tool_call,
    },
)
```

実運用ではDBやRedisに置く方がよいです。画面リロード、サーバ再起動、複数workerを考えるならインメモリだけでは足りません。

---

## 3. resume API を作る

FastAPI 側には、通常の stream API に加えて `resume` API を作ります。

```python id="twdk04"
from pydantic import BaseModel


class ResumeRequest(BaseModel):
    request_id: str
    choice: str
    text: str | None = None


@app.post("/api/runs/{run_id}/resume")
async def resume_run(run_id: str, req: ResumeRequest):
    pending = pending_runs.get(run_id)

    if pending is None:
        return StreamingResponse(
            error_stream("再開対象の実行が見つかりません"),
            media_type="text/event-stream",
        )

    async def stream():
        async for event in agent.resume_agent_stream(
            pending=pending,
            human_response=req,
        ):
            yield to_sse(event)

    return StreamingResponse(
        stream(),
        media_type="text/event-stream",
    )
```

agent 側には `resume_agent_stream()` を作ります。

```python id="wf2tke"
async def resume_agent_stream(
    self,
    pending: PendingRun,
    human_response: ResumeRequest,
):
    yield AgentEvent(
        type="status",
        message="ユーザの選択を反映しています",
    )

    if pending.resume_point == "send_email_approval":
        async for event in self._resume_send_email(
            pending=pending,
            human_response=human_response,
        ):
            yield event
        return

    yield AgentEvent(
        type="error",
        message="未対応の再開ポイントです",
    )
```

メール送信の承認なら、こうなります。

```python id="bo9myl"
async def _resume_send_email(
    self,
    pending: PendingRun,
    human_response: ResumeRequest,
):
    if human_response.choice == "reject":
        yield AgentEvent(
            type="answer_delta",
            message="メール送信はキャンセルしました。",
        )
        yield AgentEvent(type="done")
        return

    if human_response.choice == "edit":
        yield AgentEvent(
            type="answer_delta",
            message="修正内容を入力してください。",
        )
        yield AgentEvent(type="done")
        return

    if human_response.choice != "approve":
        yield AgentEvent(
            type="error",
            message="不明な選択です",
        )
        return

    tool_call = pending.data["tool_call"]

    yield AgentEvent(
        type="tool_call_started",
        message="メールを送信しています",
        data={
            "name": "send_email",
            "tool_call_id": tool_call.tool_call_id,
        },
    )

    result = await self.tools.execute(pending.ctx, tool_call)

    yield AgentEvent(
        type="tool_call_finished",
        message="メールを送信しました",
        data={
            "name": "send_email",
            "tool_call_id": tool_call.tool_call_id,
            "result_summary": str(result),
        },
    )

    yield AgentEvent(
        type="answer_delta",
        message="メールを送信しました。",
    )

    yield AgentEvent(type="done")
```

この形にすると、「承認待ち」「却下」「修正」「再開」を明示的に扱えます。

---

## 4. React側では選択UIを表示する

React側では `human_input_requested` を受け取ったら、ボタン付きUIを出します。

assistant-ui に寄せるなら、これは **tool UI として扱う** のが自然です。assistant-ui には `makeAssistantToolUI` があり、tool name ごとに `args`、`result`、`status` を受け取って専用UIを描画できます。tool interaction の real-time visualization や、custom tool UI を登録する用途として説明されています。([assistant-ui][2])

概念的には、`human_input_requested` を React 側で `human_approval` という tool part に変換します。

```tsx id="wnhxic"
if (event.type === "human_input_requested") {
  toolCalls.set(event.data.request_id as string, {
    type: "tool-call",
    toolCallId: event.data.request_id,
    toolName: "human_approval",
    args: {
      runId,
      requestId: event.data.request_id,
      title: event.data.title,
      message: event.message,
      detail: event.data.detail,
      options: event.data.options,
    },
    argsText: JSON.stringify(event.data),
  });
}
```

そして `human_approval` 用の tool UI を作ります。

```tsx id="yjqfzx"
import { makeAssistantToolUI } from "@assistant-ui/react";

type ApprovalOption = {
  id: string;
  label: string;
};

type HumanApprovalArgs = {
  runId: string;
  requestId: string;
  title: string;
  message: string;
  detail?: Record<string, unknown>;
  options: ApprovalOption[];
};

export const HumanApprovalToolUI = makeAssistantToolUI({
  toolName: "human_approval",
  render: ({ args }) => {
    const approval = args as HumanApprovalArgs;

    async function submit(choice: string) {
      const response = await fetch(`/api/runs/${approval.runId}/resume`, {
        method: "POST",
        headers: {
          "Content-Type": "application/json",
        },
        body: JSON.stringify({
          request_id: approval.requestId,
          choice,
        }),
      });

      if (!response.body) {
        return;
      }

      // ここで resume stream を読み、assistant-ui の message に反映する
      // LocalRuntimeで実装するなら、resume用のイベント読み取り処理へ渡す
    }

    return (
      <div className="rounded-md border p-3 text-sm">
        <div className="font-medium">{approval.title}</div>
        <div className="mt-1">{approval.message}</div>

        {approval.detail ? (
          <pre className="mt-2 whitespace-pre-wrap rounded bg-muted p-2">
            {JSON.stringify(approval.detail, null, 2)}
          </pre>
        ) : null}

        <div className="mt-3 flex gap-2">
          {approval.options.map((option) => (
            <button
              key={option.id}
              className="rounded border px-3 py-1"
              onClick={() => submit(option.id)}
            >
              {option.label}
            </button>
          ))}
        </div>
      </div>
    );
  },
});
```

これを `App.tsx` などで登録します。

```tsx id="y94d8l"
export default function App() {
  return (
    <MyRuntimeProvider>
      <HumanApprovalToolUI />
      <Thread />
    </MyRuntimeProvider>
  );
}
```

ただし、ここで1点注意があります。`makeAssistantToolUI` の中で直接 `fetch` して resume stream を読む設計にすると、runtime の state 更新との接続が少し難しくなります。最初は、tool UI のボタン押下時に **runtime 側の resume 関数を呼べるようにする** 方がきれいです。実装を簡単にするなら Zustand などの store に `resumeRun()` を置き、tool UI からそれを呼ぶ形にします。

---

## 5. LocalRuntime での実装イメージ

`LocalRuntime` は custom backend に接続する一番シンプルな方法で、`ChatModelAdapter` の `run` を実装すれば、messages、threads、editing、regeneration、cancellation などは runtime が扱います。([assistant-ui][3])

HITL ありの場合は、`run()` の中で stream を読みます。

```tsx id="2lq17c"
const MyModelAdapter: ChatModelAdapter = {
  async *run({ messages, abortSignal }) {
    const response = await fetch("/api/chat/stream", {
      method: "POST",
      headers: {
        "Content-Type": "application/json",
      },
      body: JSON.stringify({ messages }),
      signal: abortSignal,
    });

    if (!response.body) {
      throw new Error("Response body is empty");
    }

    let text = "";
    const toolCalls = new Map<string, any>();

    for await (const event of readSseEvents(response.body)) {
      if (event.type === "answer_delta") {
        text += event.message ?? "";
      }

      if (event.type === "human_input_requested") {
        const requestId = String(event.data.request_id);

        toolCalls.set(requestId, {
          type: "tool-call",
          toolCallId: requestId,
          toolName: "human_approval",
          args: {
            runId: event.data.run_id,
            requestId,
            title: event.data.title,
            message: event.message,
            detail: event.data.detail,
            options: event.data.options,
          },
          argsText: JSON.stringify(event.data),
        });
      }

      if (event.type === "error") {
        throw new Error(event.message ?? "Agent error");
      }

      yield {
        content: [
          ...Array.from(toolCalls.values()),
          ...(text ? [{ type: "text" as const, text }] : []),
        ],
      };
    }
  },
};
```

ここでの基本は、前回と同じです。`answer_delta` は assistant message の text に追加し、`human_input_requested` は tool UI として表示します。

---

## 6. Data Stream Protocol に寄せるなら

長期的には、`Data Stream Protocol` に寄せるのもよいです。assistant-ui の Data Stream Protocol は、streaming text、tool calls、error handling、cancellation、attachments を扱える標準化された形式として説明されています。([assistant-ui][4])

この場合、React側は `useDataStreamRuntime` に寄せられるので薄くなります。ただし、FastAPI側が assistant-ui / AI SDK 系の data stream 形式に合わせて、text delta、tool call、tool result などを返す必要があります。AI SDK の stream protocol ドキュメントでも、Python など別言語の custom backend で互換APIを作る用途に使えると説明されています。([AI SDK][5])

HITL を Data Stream Protocol に乗せる場合は、`human_approval` を「実行中の tool call」として流し、ユーザが承認したら `resume` で tool result を返す、という設計になります。

```text id="vcifof"
agent-core:
  human_input_requested

FastAPI adapter:
  tool_call: human_approval

assistant-ui:
  HumanApprovalToolUI を表示

user click:
  /api/runs/{run_id}/resume

FastAPI adapter:
  tool_result: human_approval result
  answer_delta
```

最初から Data Stream Protocol に完全準拠させると、FastAPI側の実装がやや重くなります。React初心者・assistant-ui初回なら、まずは `LocalRuntime + 独自AgentEvent` で動かし、その後 Data Stream Protocol へ寄せる順番が安全です。

---

## 7. 通常の聞き返しと HITL は分ける

ここは設計上とても重要です。

たとえば、ユーザの依頼が曖昧で「AとBどちらですか？」と聞くだけなら、普通の assistant message で十分です。

```text id="1aqw36"
ユーザ: 見積書を作って
AI: 対象製品はAとBのどちらですか？
ユーザ: Aです
AI: Aの見積書を作成します
```

これは interrupt / resume にしなくてよいです。単に会話履歴に user message が追加され、次回の agent 実行で続きます。

一方で、次のようなものは HITL として扱う方がよいです。

```text id="jercn6"
- メールを送信する前の承認
- ファイルを書き換える前の承認
- 外部システムへ登録する前の承認
- 複数案から処理ルートを選ばせる
- 高コストな処理を実行する前の確認
- 失敗時に「リトライ / スキップ / 中止」を選ばせる
```

つまり、

```text id="mlth24"
情報不足の質問:
  assistant message として聞く

実行制御上の判断:
  human_input_requested で interrupt する
```

この区別を入れると、UI/UXも実装もかなり整理されます。

---

## 8. 実装上のおすすめ

あなたのエージェントなら、まず次の3種類だけ入れるとよいです。

```python id="b8y1z1"
@dataclass(frozen=True)
class HumanInputRequest:
    request_id: str
    kind: Literal["confirmation", "choice", "text"]
    title: str
    message: str
    options: list[dict[str, str]] = field(default_factory=list)
    metadata: dict[str, Any] = field(default_factory=dict)
```

用途はこうです。

```text id="7q6o5a"
confirmation:
  はい / いいえ

choice:
  A案 / B案 / C案

text:
  ユーザに自由入力してもらう
```

最初は `confirmation` と `choice` だけで十分です。`text` は、普通のチャット入力と競合しやすいので後回しでもよいです。

---

## 9. 最終的な構成

今回の構成をまとめると、こうなります。

```text id="lf7fik"
agent-core
  run_agent_stream()
    status
    tool_call_started
    human_input_requested
    interrupted
    answer_delta
    done

  resume_agent_stream()
    human response を受け取って再開

agent-api
  POST /api/chat/stream
    通常実行

  POST /api/runs/{run_id}/resume
    HITL後の再開

frontend
  assistant-ui Thread
  LocalRuntime or Data Stream Runtime
  human_approval tool UI
  ボタン押下で resume API

state storage
  run_id
  ctx
  req
  pending_request_id
  resume_point
```

この方式にすると、ユーザは ChatGPT 風の画面で自然に「承認」「却下」「A案を選ぶ」などを押せます。一方で agent-core 側は、単なる会話と実行中断を分けて扱えるので、製造業向けの業務フローにも拡張しやすいです。

[1]: https://www.assistant-ui.com/docs/guides/tools?utm_source=chatgpt.com "Tools"
[2]: https://www.assistant-ui.com/docs/copilots/make-assistant-tool-ui?utm_source=chatgpt.com "makeAssistantToolUI"
[3]: https://www.assistant-ui.com/docs/runtimes/custom/local-runtime?utm_source=chatgpt.com "LocalRuntime — assistant-ui (React Chat UI for AI)"
[4]: https://www.assistant-ui.com/docs/runtimes/custom/data-stream?utm_source=chatgpt.com "Data Stream Protocol"
[5]: https://ai-sdk.dev/docs/ai-sdk-ui/stream-protocol?utm_source=chatgpt.com "AI SDK UI: Stream Protocols"


はい、その懸念はかなり本質的です。前の例のように backend 側で、

```python
message="このメールを送信してよいですか？"
title="メール送信の確認"
options=[
    {"id": "approve", "label": "送信する"},
    {"id": "reject", "label": "送信しない"},
]
```

のように書き始めると、**tool が増えるたびに backend が UI 文言を抱える**ことになります。これは汎用エージェント基盤としてはあまりよくありません。

よりよい設計は、backend は **UI文言ではなく、意味のあるイベントだけを出す**ことです。

```text
悪い寄せ方:
  backend が「このメールを送信してよいですか？」という表示文言を作る

よい寄せ方:
  backend が「send_email という副作用toolの承認が必要」とだけ伝える
  frontend がそれを見て「メール送信の確認」UIを表示する
```

つまり、`human_input_requested` は UIイベントではなく、**意思決定要求イベント**として設計した方がよいです。

---

## backend が出すべきもの

backend から出すのは、こういう情報です。

```python
yield AgentEvent(
    type="human_input_requested",
    data={
        "interaction_id": approval_request_id,
        "interaction_type": "approval",
        "target": {
            "type": "tool_call",
            "tool_call_id": tool_call.tool_call_id,
            "tool_name": tool_call.name,
        },
        "risk": {
            "level": "external_side_effect",
            "reason_code": "sends_external_message",
        },
        "preview": {
            "to": "customer@example.com",
            "subject": "見積書の送付",
            "body_preview": "お世話になっております。見積書を送付いたします...",
        },
        "allowed_actions": ["approve", "reject", "edit"],
    },
)
```

ここでは、backend は「送信する」「送信しない」のようなラベルを持っていません。持っているのは、

```text
interaction_type: approval
tool_name: send_email
allowed_actions: approve / reject / edit
preview: 判断に必要なデータ
```

だけです。

frontend 側がこれを見て、表示文言を決めます。

```ts
const actionLabels = {
  approve: "承認する",
  reject: "却下する",
  edit: "修正する",
};
```

あるいは tool ごとに表示を変えます。

```ts
const toolActionLabels = {
  send_email: {
    approve: "送信する",
    reject: "送信しない",
    edit: "内容を修正する",
  },
  write_file: {
    approve: "書き込む",
    reject: "中止する",
    edit: "内容を修正する",
  },
};
```

この方が、backend は汎用エージェント基盤として残せます。

---

## さらによい形：tool定義に approval metadata を持たせる

toolごとに backend コードへ個別実装を書くのではなく、tool の metadata として「承認が必要か」「preview に何を出すか」を持たせるとよいです。

たとえば tool 定義をこうします。

```python
@dataclass(frozen=True)
class ToolApprovalPolicy:
    mode: Literal["never", "always", "dangerous_only"]
    risk_level: Literal["none", "read_only", "write", "external_side_effect"]
    reason_code: str
    allowed_actions: list[str]


@dataclass(frozen=True)
class ToolMeta:
    name: str
    approval: ToolApprovalPolicy | None = None
    preview_fields: list[str] = field(default_factory=list)
```

`send_email` はこう定義します。

```python
send_email_meta = ToolMeta(
    name="send_email",
    approval=ToolApprovalPolicy(
        mode="always",
        risk_level="external_side_effect",
        reason_code="sends_external_message",
        allowed_actions=["approve", "reject", "edit"],
    ),
    preview_fields=["to", "subject", "body_preview"],
)
```

`read_file` は承認不要。

```python
read_file_meta = ToolMeta(
    name="read_file",
    approval=None,
)
```

`write_file` は承認あり。

```python
write_file_meta = ToolMeta(
    name="write_file",
    approval=ToolApprovalPolicy(
        mode="always",
        risk_level="write",
        reason_code="modifies_local_file",
        allowed_actions=["approve", "reject", "edit"],
    ),
    preview_fields=["path", "content_preview"],
)
```

agent 側は tool ごとの文言を知りません。単に policy を見ます。

```python
async def maybe_request_approval(
    self,
    tool_call: ToolCall,
) -> AgentEvent | None:
    tool = self.tools.get(tool_call.name)

    if tool.meta.approval is None:
        return None

    approval = tool.meta.approval
    preview = build_preview(
        args=tool_call.args,
        fields=tool.meta.preview_fields,
    )

    return AgentEvent(
        type="human_input_requested",
        data={
            "interaction_id": str(uuid.uuid4()),
            "interaction_type": "approval",
            "target": {
                "type": "tool_call",
                "tool_call_id": tool_call.tool_call_id,
                "tool_name": tool_call.name,
            },
            "risk": {
                "level": approval.risk_level,
                "reason_code": approval.reason_code,
            },
            "preview": preview,
            "allowed_actions": approval.allowed_actions,
        },
    )
```

agent loop 側ではこう使います。

```python
approval_event = await self.maybe_request_approval(tool_call)

if approval_event is not None:
    self.save_pending_run(ctx, req, tool_call, approval_event)

    yield approval_event
    yield AgentEvent(
        type="interrupted",
        data={
            "interaction_id": approval_event.data["interaction_id"],
        },
    )
    return
```

この形なら、tool が増えても backend の agent loop は増えません。増えるのは tool metadata だけです。

---

## frontend 側が UI を担当する

frontend は `tool_name`、`interaction_type`、`allowed_actions` を見て表示します。

```tsx
function HumanApprovalCard({ request }: { request: HumanInputRequest }) {
  const toolName = request.target.tool_name;

  const title = getApprovalTitle(toolName, request);
  const actions = request.allowed_actions.map((action) => ({
    id: action,
    label: getActionLabel(toolName, action),
  }));

  return (
    <div className="rounded-md border p-3">
      <div className="font-medium">{title}</div>

      <Preview toolName={toolName} preview={request.preview} />

      <div className="mt-3 flex gap-2">
        {actions.map((action) => (
          <button key={action.id}>
            {action.label}
          </button>
        ))}
      </div>
    </div>
  );
}
```

文言は frontend に寄せます。

```ts
function getApprovalTitle(toolName: string, request: HumanInputRequest): string {
  if (toolName === "send_email") {
    return "メール送信の確認";
  }

  if (toolName === "write_file") {
    return "ファイル書き込みの確認";
  }

  return "操作の確認";
}
```

action label も frontend 側です。

```ts
function getActionLabel(toolName: string, action: string): string {
  const labels: Record<string, Record<string, string>> = {
    send_email: {
      approve: "送信する",
      reject: "送信しない",
      edit: "修正する",
    },
    write_file: {
      approve: "書き込む",
      reject: "中止する",
      edit: "修正する",
    },
  };

  return labels[toolName]?.[action] ?? defaultActionLabel(action);
}

function defaultActionLabel(action: string): string {
  const labels: Record<string, string> = {
    approve: "承認する",
    reject: "却下する",
    edit: "修正する",
  };

  return labels[action] ?? action;
}
```

この構成なら、frontend を作る人が UI/UX を自由にできます。backend は、承認が必要な理由と対象だけを渡します。

---

## backend に最低限残すべきもの

ただし、backend から完全に文言をなくせばよい、というわけでもありません。backend が持つべきなのは **業務的・安全上の意味情報**です。

backend が持つべきもの:

```text
- tool_name
- tool_call_id
- risk_level
- reason_code
- allowed_actions
- preview data
- resumeに必要なID
- 承認対象の実データ
```

frontend が持つべきもの:

```text
- ボタン文言
- タイトル
- 説明文
- レイアウト
- 色
- icon
- toolごとの表示カード
- 多言語化
```

特に `reason_code` は入れておくと便利です。

```python
"reason_code": "sends_external_message"
```

frontend はこれを使って文言にできます。

```ts
const reasonLabels = {
  sends_external_message: "外部宛てにメッセージを送信します",
  modifies_local_file: "ファイルを書き換えます",
  calls_external_api: "外部APIを実行します",
};
```

---

## YAML設定に寄せることもできる

あなたが前に言っていた「業務フローを YAML 設定化する」方向とも相性がよいです。

```yaml
tools:
  send_email:
    approval:
      mode: always
      risk_level: external_side_effect
      reason_code: sends_external_message
      allowed_actions:
        - approve
        - reject
        - edit
    preview_fields:
      - to
      - subject
      - body_preview

  read_file:
    approval:
      mode: never

  write_file:
    approval:
      mode: always
      risk_level: write
      reason_code: modifies_local_file
      allowed_actions:
        - approve
        - reject
        - edit
    preview_fields:
      - path
      - content_preview
```

backend はこの YAML を読んで、承認イベントを汎用生成します。

```python
def create_human_input_event(
    tool_call: ToolCall,
    policy: ToolApprovalPolicy,
) -> AgentEvent:
    return AgentEvent(
        type="human_input_requested",
        data={
            "interaction_id": str(uuid.uuid4()),
            "interaction_type": "approval",
            "target": {
                "type": "tool_call",
                "tool_call_id": tool_call.tool_call_id,
                "tool_name": tool_call.name,
            },
            "risk": {
                "level": policy.risk_level,
                "reason_code": policy.reason_code,
            },
            "preview": extract_preview(
                args=tool_call.args,
                fields=policy.preview_fields,
            ),
            "allowed_actions": policy.allowed_actions,
        },
    )
```

こうすれば、backend の agent loop は汎用のままです。tool が増えても YAML / metadata を増やすだけで済みます。

---

## 最終的な考え方

あなたの違和感を反映すると、設計はこうするのがよいです。

```text
backend:
  UI文言を作らない
  判断要求の意味情報だけを出す
  tool metadata / policy から汎用イベントを作る

frontend:
  tool_name / reason_code / allowed_actions を見て表示する
  toolごとのUIを自由に作る
  文言、多言語化、ボタン、レイアウトを担当する
```

なので、前の例は PoC としてはわかりやすいですが、汎用エージェント基盤としては少し backend に寄りすぎです。実装するなら、`message` や `label` を backend に直書きするのではなく、`interaction_type`、`tool_name`、`reason_code`、`allowed_actions`、`preview` を返す形に寄せた方がよいです。


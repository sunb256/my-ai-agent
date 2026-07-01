
  # LocalRuntime + HITL 向け API / React 実装方針

  ## Summary

  今の API は Data Stream Protocol 風に作られているが、HITL 必須なら assistant-ui の LocalRuntime に寄せる。
  backend は assistant-ui 固有 protocol を直接話さず、読みやすい 独自 NDJSON stream を返す。React 側の ChatModelAdapter がその NDJSON を assistant-ui の content / status に変
  換する。

  LocalRuntime は HTTP protocol ではなく、React 側で run() / async *run() を実装する方式。公式 docs でも custom backend 接続向けに ChatModelAdapter を1つ実装する形として説明さ
  れている。

  ## Protocol

  backend の wire protocol は application/x-ndjson にする。1行1 JSON。

  通常完了:

  {"type":"text_delta","text":"こんにちは"}
  {"type":"done","status":"complete"}

  HITL 発生:

  {"type":"tool_call_required","tool_call_id":"human_approval_<run_id>","tool_name":"human_approval","args":{"session_id":"s1","run_id":"r1","approvals":
  [{"tool_call_id":"tc1","tool_name":"delete_file","args":{"path":"/tmp/test.txt"},"confirm":"削除してよいですか？"}]}}
  {"type":"done","status":"requires_action"}

  エラー:

  {"type":"error","message":"..."}
  {"type":"done","status":"error"}

  resume request:

  {
    "confirm": [
      {
        "tool_call_id": "tc1",
        "approved": true,
        "modified_args": null
      }
    ]
  }

  ポイント:

  - 0:, 3:, d: は廃止する
  - X-vercel-ai-data-stream header は出さない
  - backend event は snake_case
  - React adapter が assistant-ui の camelCase toolCallId, toolName, argsText に変換する
  - human_approval は assistant-ui 側では human tool として扱い、unstable_humanToolNames: ["human_approval"] で pause させる

  ## Backend Implementation

  src/api/stream_events.py は Data Stream 用ではなく NDJSON builder にする。

  import json
  from typing import Any, Literal

  DoneStatus = Literal["complete", "requires_action", "error"]

  def event_line(payload: dict[str, Any]) -> str:
      return json.dumps(payload, ensure_ascii=False, default=str) + "\n"

  def text_delta(text: str) -> str:
      return event_line({"type": "text_delta", "text": text})

  def tool_call_required(tool_call_id: str, tool_name: str, args: dict[str, Any]) -> str:
      return event_line(
          {
              "type": "tool_call_required",
              "tool_call_id": tool_call_id,
              "tool_name": tool_name,
              "args": args,
          }
      )

  def error(message: str) -> str:
      return event_line({"type": "error", "message": message})

  def done(status: DoneStatus) -> str:
      return event_line({"type": "done", "status": status})

  src/api/schemas.py は threadId を session として受けられるようにする。

  from typing import Any
  from pydantic import AliasChoices, BaseModel, ConfigDict, Field

  class ToolConfirmPayload(BaseModel):
      model_config = ConfigDict(populate_by_name=True)

      tool_call_id: str = Field(validation_alias=AliasChoices("tool_call_id", "id"))
      approved: bool
      modified_args: dict[str, Any] | None = None

  class ChatRunRequest(BaseModel):
      model_config = ConfigDict(extra="allow", populate_by_name=True)

      messages: list[dict[str, Any]] = Field(default_factory=list)
      prompt: str | None = None
      session_id: str | None = None
      thread_id: str | None = Field(
          default=None,
          validation_alias=AliasChoices("threadId", "thread_id"),
      )
      verbose: bool = False

  class ResumeRunRequest(BaseModel):
      confirm: list[ToolConfirmPayload] = Field(min_length=1)
      verbose: bool = False

  src/api/main.py は NDJSON として返す。

  return StreamingResponse(
      _get_service().stream_chat(body, sid),
      media_type="application/x-ndjson",
      headers={
          "Cache-Control": "no-cache",
          "Connection": "keep-alive",
          "X-Accel-Buffering": "no",
      },
  )

  session 解決順:

  sid = (
      body.session_id
      or body.thread_id
      or session_id
      or request.headers.get("x-session-id")
  )

  src/api/service.py の変換はこうする。

  if result.status == "pending":
      await self._save_pending_run_id(session_id, run_id)

      args = {
          "session_id": session_id,
          "run_id": run_id,
          "approvals": self._pending_payload(result.pending_tc),
      }

      yield tool_call_required(
          tool_call_id=f"human_approval_{run_id}",
          tool_name="human_approval",
          args=args,
      )
      yield done("requires_action")
      return

  if result.output is not None:
      yield text_delta(self._output_text(result.output))
      yield done("complete")
      return

  yield error("agent_finished_without_output")
  yield done("error")

  _pending_payload() は backend tool call をそのまま保持する。

  def _pending_payload(self, pending_tc: list[Any]) -> list[dict[str, Any]]:
      return [
          {
              "tool_call_id": pending.tool_call.tool_call_id,
              "tool_name": pending.tool_call.name,
              "args": pending.tool_call.args,
              "confirm": pending.confirm,
          }
          for pending in pending_tc
      ]

  ## Frontend Implementation

  React 側は useLocalRuntime() を使う。

  NDJSON parser:

  type AgentEvent =
    | { type: "text_delta"; text: string }
    | {
        type: "tool_call_required";
        tool_call_id: string;
        tool_name: "human_approval";
        args: HumanApprovalArgs;
      }
    | { type: "done"; status: "complete" | "requires_action" | "error" }
    | { type: "error"; message: string };

  async function* readNdjson(stream: ReadableStream<Uint8Array>) {
    const reader = stream.getReader();
    const decoder = new TextDecoder();
    let buffer = "";

    while (true) {
      const { value, done } = await reader.read();
      if (done) break;

      buffer += decoder.decode(value, { stream: true });
      const lines = buffer.split("\n");
      buffer = lines.pop() ?? "";

      for (const line of lines) {
        if (line.trim()) yield JSON.parse(line) as AgentEvent;
      }
    }

    if (buffer.trim()) yield JSON.parse(buffer) as AgentEvent;
  }

  LocalRuntime adapter:

  import {
    AssistantRuntimeProvider,
    useLocalRuntime,
    type ChatModelAdapter,
  } from "@assistant-ui/react";
  import { useMemo, type ReactNode } from "react";

  function createAdapter(defaultSessionId: string): ChatModelAdapter {
    return {
      async *run({ messages, abortSignal, unstable_threadId, unstable_getMessage }) {
        const sessionId = unstable_threadId ?? defaultSessionId;
        const currentMessage = unstable_getMessage?.();
        const confirms = extractHumanApprovalResults(currentMessage);

        const response = await fetch(
          confirms
            ? `/api/v1/sessions/${sessionId}/resume`
            : `/api/v1/chat`,
          {
            method: "POST",
            headers: { "Content-Type": "application/json" },
            signal: abortSignal,
            body: JSON.stringify(
              confirms
                ? { confirm: confirms }
                : { messages, session_id: sessionId },
            ),
          },
        );

        if (!response.ok || !response.body) {
          throw new Error(`API error: ${response.status}`);
        }

        let text = "";
        const toolCalls = new Map<string, any>();

        for await (const event of readNdjson(response.body)) {
          if (event.type === "text_delta") {
            text += event.text;
          }

          if (event.type === "tool_call_required") {
            toolCalls.set(event.tool_call_id, {
              type: "tool-call",
              toolCallId: event.tool_call_id,
              toolName: event.tool_name,
              args: event.args,
              argsText: JSON.stringify(event.args),
            });

            yield {
              content: [
                ...(text ? [{ type: "text" as const, text }] : []),
                ...Array.from(toolCalls.values()),
              ],
              status: { type: "requires-action", reason: "tool-calls" },
            };
            return;
          }

          if (event.type === "error") {
            throw new Error(event.message);
          }

          if (event.type === "done" && event.status === "complete") {
            yield {
              content: [
                ...(text ? [{ type: "text" as const, text }] : []),
                ...Array.from(toolCalls.values()),
              ],
            };
            return;
          }
        }
      },
    };
  }

  export function MyRuntimeProvider({ children }: { children: ReactNode }) {
    const defaultSessionId = useMemo(() => crypto.randomUUID(), []);
    const adapter = useMemo(() => createAdapter(defaultSessionId), [defaultSessionId]);

    const runtime = useLocalRuntime(adapter, {
      unstable_humanToolNames: ["human_approval"],
    });

    return (
      <AssistantRuntimeProvider runtime={runtime}>
        {children}
      </AssistantRuntimeProvider>
    );
  }

  HITL の結果抽出:

  function extractHumanApprovalResults(message: any) {
    const content = message?.content ?? [];

    const confirms = content
      .filter(
        (part: any) =>
          part.type === "tool-call" &&
          part.toolName === "human_approval" &&
          part.result?.confirm,
      )
      .flatMap((part: any) => part.result.confirm);

    return confirms.length > 0 ? confirms : null;
  }

  human approval UI:

  import { makeAssistantToolUI } from "@assistant-ui/react";

  type HumanApprovalArgs = {
    session_id: string;
    run_id: string;
    approvals: {
      tool_call_id: string;
      tool_name: string;
      args: Record<string, unknown>;
      confirm: string;
    }[];
  };

  export const HumanApprovalToolUI = makeAssistantToolUI<HumanApprovalArgs, any>({
    toolName: "human_approval",
    render: ({ args, result, status, addResult }) => {
      if (result) return <div>承認結果を送信しました</div>;

      if (status?.type !== "requires-action") {
        return <div>承認待ちです</div>;
      }

      return (
        <div>
          {args.approvals.map((item) => (
            <div key={item.tool_call_id}>
              <div>{item.confirm}</div>
              <pre>{JSON.stringify(item.args, null, 2)}</pre>
            </div>
          ))}

          <button
            onClick={() =>
              addResult?.({
                confirm: args.approvals.map((item) => ({
                  tool_call_id: item.tool_call_id,
                  approved: true,
                })),
              })
            }
          >
            Allow
          </button>

          <button
            onClick={() =>
              addResult?.({
                confirm: args.approvals.map((item) => ({
                  tool_call_id: item.tool_call_id,
                  approved: false,
                })),
              })
            }
          >
            Deny
          </button>
        </div>
      );
    },
  });

  root で登録する。

  <AssistantRuntimeProvider runtime={runtime}>
    <HumanApprovalToolUI />
    <Thread />
  </AssistantRuntimeProvider>

  ## Flow

  通常 chat:

  Thread
    -> LocalRuntime adapter
    -> POST /api/v1/chat
    -> backend returns text_delta + done.complete
    -> adapter yields cumulative text
    -> assistant-ui displays assistant message

  HITL:

  Thread
    -> adapter calls /api/v1/chat
    -> backend returns tool_call_required + done.requires_action
    -> adapter yields tool-call + requires-action
    -> HumanApprovalToolUI shows Allow / Deny
    -> addResult stores approval result
    -> LocalRuntime calls adapter again
    -> adapter detects result from unstable_getMessage()
    -> POST /api/v1/sessions/{session_id}/resume
    -> backend executes or denies tool
    -> backend returns text_delta + done.complete
    -> adapter appends final text to same assistant message

  ## Test Plan

  backend:

  uv run ruff check src/api src/agent/init.py
  uv run pytest

  追加したいテスト:

  - complete result: text_delta + done.complete
  - pending result: tool_call_required + done.requires_action
  - pending 時に session state に pending_run_id が入る
  - resume request が ToolConfirm(tool_call_id=..., approved=...) に変換される
  - deny 時も resume が完了する
  - session_id が session_id, threadId, query, header の順で解決される

  frontend:

  - readNdjson() が複数 chunk / 行途中分割を parse できる
  - text_delta を累積 text として yield する
  - tool_call_required で requires-action を返す
  - addResult() 後に resume API が呼ばれる
  - Allow / Deny が正しい confirm payload になる

  ## Assumptions

  - HITL は必須なので、Data Stream Protocol 準拠より LocalRuntime の保守性を優先する。
  - backend は assistant-ui に直接依存しない。
  - assistant-ui 変換は frontend adapter の責務にする。
  - 最初は token-level streaming ではなく、Agent 完了後に text_delta を1回返すだけでよい。
  - refresh 復元や永続 session は別フェーズ。今の InMemorySessionManager ではプロセス再起動で pending は消える。

  Sources:

  - https://www.assistant-ui.com/docs/runtimes/custom/local-runtime
  - https://www.assistant-ui.com/docs/runtimes/custom/data-stream
  - https://www.assistant-ui.com/docs/copilots/make-assistant-tool-ui
  - https://www.assistant-ui.com/docs/guides/tools

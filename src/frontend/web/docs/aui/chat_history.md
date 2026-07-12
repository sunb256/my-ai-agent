はい。採用する方式は、**`thread_id`単位でバックエンドAgentのセッション状態をSQLiteへ永続化し、会話を開いたときにバックエンドのAgentセッションとassistant-uiの表示履歴を、それぞれ同じ`thread_id`から復元する構成**です。

ただし、AgentインスタンスやPythonオブジェクトをそのまま保存するのではなく、**会話履歴、要約、作業メモリ、保留中のTool Callなど、再開に必要な状態を明示的なJSONとして保存**します。

# assistant-ui＋AG-UI＋SQLiteによる会話履歴・Agentセッション永続化設計

## 1. 採用する方式

会話の継続には、次の2種類の復元が必要です。

```text
バックエンドの復元
    Agentが過去の文脈・内部状態を引き継ぐ

フロントエンドの復元
    過去のメッセージ、Tool Call、Tool Resultなどを画面に表示する
```

このうち、本当の意味で会話を継続させるのはバックエンドです。

assistant-uiに過去メッセージが表示されていても、バックエンドAgentのセッションが復元されていなければ、Agentにとっては新しい会話です。

したがって、次の関係にします。

```text
thread_id
  ├─ AgentSession
  │    ├─ 会話コンテキスト
  │    ├─ 要約
  │    ├─ 作業メモリ
  │    ├─ Tool実行状態
  │    └─ HITL待機状態
  │
  └─ assistant-ui表示履歴
       ├─ user message
       ├─ assistant message
       ├─ tool call
       ├─ tool result
       └─ interrupt
```

どちらも同じ`thread_id`にひも付けます。

---

## 2. 全体構成

```text
React
  ├─ ConversationSidebar
  │    └─ 会話一覧、作成、選択、削除
  │
  ├─ React Router
  │    └─ /chat/{thread_id}
  │
  └─ assistant-ui
       ├─ HttpAgent
       ├─ useAgUiRuntime
       ├─ history adapter
       └─ <Thread />

               │ AG-UI
               ▼

FastAPI
  ├─ Threads API
  ├─ Agent Stream API
  ├─ AgentApiService
  ├─ Agent
  └─ SqliteSessionManager

               │
               ▼

SQLite
  ├─ chat_threads
  ├─ chat_messages
  ├─ agent_sessions
  └─ agent_runs
```

AG-UIの`RunAgentInput`には、`thread_id`、`run_id`、現在の`state`、`messages`などが含まれます。今回の構成では、`thread_id`をバックエンドの永続セッションを特定する主キーとして使用します。([Agent User Interaction Protocol][1])

---

## 3. SQLiteの役割

SQLiteには、少なくとも次の4種類を保存します。

### chat_threads

サイドバーに表示する会話単位です。

```sql
CREATE TABLE chat_threads (
    id TEXT PRIMARY KEY,
    user_id TEXT NOT NULL,
    title TEXT NOT NULL,
    status TEXT NOT NULL DEFAULT 'active',
    created_at TEXT NOT NULL,
    updated_at TEXT NOT NULL,
    deleted_at TEXT
);

CREATE INDEX idx_chat_threads_user_updated
ON chat_threads(user_id, updated_at DESC);
```

### chat_messages

assistant-uiに表示する完全な会話履歴です。

```sql
CREATE TABLE chat_messages (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    run_id TEXT,
    sequence_no INTEGER NOT NULL,
    role TEXT NOT NULL,
    content_json TEXT NOT NULL,
    metadata_json TEXT,
    created_at TEXT NOT NULL,

    FOREIGN KEY(thread_id)
        REFERENCES chat_threads(id)
        ON DELETE CASCADE
);

CREATE UNIQUE INDEX idx_chat_messages_sequence
ON chat_messages(thread_id, sequence_no);
```

`content_json`には、単なる本文だけでなく、Tool CallやTool Resultを構造化した状態で保存します。

```json
{
  "id": "msg-101",
  "role": "assistant",
  "content": "設備履歴を確認します。",
  "toolCalls": [
    {
      "id": "call-201",
      "type": "function",
      "function": {
        "name": "search_machine_history",
        "arguments": "{\"machine_id\":\"A-01\"}"
      }
    }
  ]
}
```

### agent_sessions

バックエンドAgentの現在のセッション状態です。

```sql
CREATE TABLE agent_sessions (
    thread_id TEXT PRIMARY KEY,
    schema_version INTEGER NOT NULL,
    revision INTEGER NOT NULL DEFAULT 0,
    status TEXT NOT NULL,
    state_json TEXT NOT NULL,
    last_run_id TEXT,
    updated_at TEXT NOT NULL,

    FOREIGN KEY(thread_id)
        REFERENCES chat_threads(id)
        ON DELETE CASCADE
);
```

### agent_runs

1回のAgent実行を管理します。

```sql
CREATE TABLE agent_runs (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    status TEXT NOT NULL,
    started_at TEXT NOT NULL,
    finished_at TEXT,
    error_message TEXT,
    interrupt_json TEXT,

    FOREIGN KEY(thread_id)
        REFERENCES chat_threads(id)
        ON DELETE CASCADE
);
```

---

## 4. Agentセッションに保存する内容

Agentセッションは、Pythonオブジェクトをpickleでそのまま保存するのではなく、Pydanticで定義したJSON保存可能な状態にします。

```python
from typing import Any, Literal
from pydantic import BaseModel, Field


class PendingExecution(BaseModel):
    kind: Literal["tool_approval", "user_input", "tool_execution"]
    step_name: str
    tool_call_id: str | None = None
    tool_name: str | None = None
    tool_args: dict[str, Any] = Field(default_factory=dict)
    interrupt_id: str | None = None


class AgentSessionState(BaseModel):
    schema_version: int = 1
    thread_id: str

    summary: str | None = None
    working_memory: dict[str, Any] = Field(default_factory=dict)

    pending_execution: PendingExecution | None = None

    last_message_sequence: int = 0
    last_run_id: str | None = None
    revision: int = 0
```

保存するのは、次のような情報です。

```text
保存する
    会話の要約
    Agentの作業メモリ
    参照中のファイルや成果物ID
    現在の処理ステップ
    保留中のTool Call
    HITLのinterrupt ID
    compaction済みのコンテキスト情報

保存しない
    DBコネクション
    HTTPクライアント
    LLMクライアント
    Python関数
    コールバック
    asyncio Task
    実行中のgenerator
```

Agentの実行基盤そのものは、FastAPI起動時に毎回構築します。

```python
agent = get_agent(
    config=config,
    client=client,
    session_manager=SqliteSessionManager(...),
)
```

そのうえで、実行ごとに`thread_id`からセッションを読み込みます。

---

## 5. SessionManagerの構成

現在の`InMemorySessionManager`を、SQLite実装へ置き換えます。

```python
from typing import Protocol


class SessionManager(Protocol):
    async def load(
        self,
        thread_id: str,
    ) -> AgentSessionState | None:
        ...

    async def create(
        self,
        thread_id: str,
    ) -> AgentSessionState:
        ...

    async def save(
        self,
        session: AgentSessionState,
        expected_revision: int,
    ) -> AgentSessionState:
        ...
```

SQLite実装の概念例です。

```python
class SqliteSessionManager:
    def __init__(self, repository: AgentSessionRepository):
        self._repository = repository

    async def load(
        self,
        thread_id: str,
    ) -> AgentSessionState | None:
        row = await self._repository.find(thread_id)

        if row is None:
            return None

        return AgentSessionState.model_validate_json(
            row.state_json
        )

    async def create(
        self,
        thread_id: str,
    ) -> AgentSessionState:
        session = AgentSessionState(
            thread_id=thread_id,
        )

        await self._repository.insert(
            thread_id=thread_id,
            state_json=session.model_dump_json(),
            revision=0,
        )

        return session

    async def save(
        self,
        session: AgentSessionState,
        expected_revision: int,
    ) -> AgentSessionState:
        next_revision = expected_revision + 1
        session.revision = next_revision

        updated = await self._repository.update_if_revision_matches(
            thread_id=session.thread_id,
            expected_revision=expected_revision,
            next_revision=next_revision,
            state_json=session.model_dump_json(),
        )

        if not updated:
            raise SessionConflictError(
                "セッションが別の処理によって更新されています"
            )

        return session
```

`revision`を使う理由は、同じ会話を複数タブから同時送信した場合の上書きを防ぐためです。

基本的には、同じ`thread_id`ではAgent実行を1つに制限します。

---

## 6. Agent実行時の流れ

ユーザーが新しいメッセージを送信した場合、次の順番で処理します。

```text
assistant-ui
    ↓
RunAgentInput
    thread_id
    run_id
    new user message
    ↓
FastAPI
    ↓
SqliteSessionManager.load(thread_id)
    ↓
AgentSession復元
    ↓
新しいユーザーメッセージを追加
    ↓
Agent実行
    ↓
AG-UIイベントをストリーミング
    ↓
セッション状態と表示履歴をSQLiteへ保存
```

実装の中心は次のようになります。

```python
async def stream_agent(
    self,
    input_: RunAgentInput,
    accept: str | None,
) -> AsyncIterator[str]:
    encoder = EventEncoder(accept=accept)

    async with self._thread_lock.acquire(input_.thread_id):
        session = await self._session_manager.load(
            input_.thread_id
        )

        if session is None:
            session = await self._session_manager.create(
                input_.thread_id
            )

        expected_revision = session.revision

        new_messages = self._find_new_messages(
            session=session,
            incoming_messages=input_.messages,
        )

        await self._message_repository.append_many(
            thread_id=input_.thread_id,
            run_id=input_.run_id,
            messages=new_messages,
        )

        async for event in self._agent.run(
            session=session,
            new_messages=new_messages,
            resume=getattr(input_, "resume", None),
        ):
            self._apply_event_to_session(
                session=session,
                event=event,
            )

            await self._persist_event_if_needed(
                thread_id=input_.thread_id,
                run_id=input_.run_id,
                event=event,
            )

            if self._requires_checkpoint(event):
                session = await self._session_manager.save(
                    session=session,
                    expected_revision=expected_revision,
                )
                expected_revision = session.revision

            yield encoder.encode(event)
```

ポイントは、フロントエンドから送られてきた会話履歴だけをAgentコンテキストとして使用しないことです。

```text
フロントエンドのmessages
    新規入力の検出、UIとの同期に使用

バックエンドのAgentSession
    Agentの正式な継続状態として使用
```

メッセージIDで重複を確認し、まだ保存されていないユーザーメッセージだけをセッションへ追加します。

---

## 7. Agentへ渡すコンテキスト

Agent実行時には、復元したセッションからLLM入力を作ります。

```python
async def build_agent_context(
    thread_id: str,
    session: AgentSessionState,
) -> list[dict]:
    recent_messages = (
        await message_repository.list_recent_for_agent(
            thread_id=thread_id,
            limit=20,
        )
    )

    messages: list[dict] = []

    if session.summary:
        messages.append(
            {
                "role": "system",
                "content": (
                    "これまでの会話の要約:\n"
                    + session.summary
                ),
            }
        )

    messages.extend(
        to_llm_messages(recent_messages)
    )

    return messages
```

DBには完全な履歴を残しますが、LLMへ毎回全履歴を送る必要はありません。

```text
SQLite
    完全なuser / assistant / tool履歴

AgentSession
    要約、作業メモリ、現在の状態

LLM入力
    要約＋直近メッセージ＋必要なTool結果
```

以前実装していたsliding windowやcompactionは、この`build_agent_context`で使用します。

---

## 8. セッションを保存するタイミング

ストリーミングの1トークンごとにSQLiteへ書き込む必要はありません。

次のタイミングで保存します。

```text
ユーザーメッセージを受け付けた直後
Tool Callが確定した後
Tool Resultを取得した後
HITLで停止する直前
最終回答が完成した後
エラー発生時
```

特にTool CallやHITLの直前・直後では、チェックポイントを保存します。

```python
def _requires_checkpoint(
    self,
    event: BaseEvent,
) -> bool:
    return event.type in {
        EventType.TOOL_CALL_END,
        EventType.TOOL_CALL_RESULT,
        EventType.RUN_FINISHED,
        EventType.RUN_ERROR,
        EventType.STATE_SNAPSHOT,
    }
```

AG-UIには、状態全体を通知する`STATE_SNAPSHOT`、差分を通知する`STATE_DELTA`、メッセージ全体を通知する`MESSAGES_SNAPSHOT`があります。バックエンドで更新した状態をフロントにも同期する場合に利用できます。([Agent User Interaction Protocol][2])

---

## 9. assistant-uiでの会話履歴復元

assistant-ui側は、Agentセッションそのものを復元する必要はありません。

assistant-uiが復元するのは、主に画面表示用のAG-UIメッセージです。

```text
Backend AgentSession
    バックエンドだけが使用する正式な実行状態

assistant-ui Runtime
    UI表示用のメッセージと状態
```

assistant-uiのAG-UI Runtimeでは、バックエンドから取得したAG-UIメッセージを`fromAgUiMessages`で変換し、history adapterから返すことで会話履歴を復元できます。([assistant-ui][3])

### 推奨するフロントエンド構成

現在独自のshadcnサイドバーを作っているため、サイドバーの会話一覧はassistant-uiに管理させず、通常のReactコンポーネントとして管理します。

```text
ConversationSidebar
    ↓
navigate("/chat/thread-001")
    ↓
ChatPage
    ↓
thread_idをキーにRuntimeを作り直す
    ↓
history adapterが履歴を取得
    ↓
<Thread />が表示
```

assistant-uiのAG-UI用`threadList` adapterも存在しますが、現時点ではexperimentalです。独自サイドバーを持つ構成では、必須ではありません。([assistant-ui][3])

### ChatPage

```tsx
import { useParams } from "react-router";

export function ChatPage() {
  const { threadId } = useParams<{
    threadId: string;
  }>();

  if (!threadId) {
    return null;
  }

  return (
    <AgentRuntimeProvider
      key={threadId}
      threadId={threadId}
    >
      <Thread />
    </AgentRuntimeProvider>
  );
}
```

`key={threadId}`を指定することで、会話を切り替えたときにRuntimeを新しいスレッド用として作り直します。

### AgentRuntimeProvider

```tsx
import { useMemo } from "react";
import {
  AssistantRuntimeProvider,
  ExportedMessageRepository,
} from "@assistant-ui/react";
import {
  fromAgUiMessages,
  useAgUiRuntime,
} from "@assistant-ui/react-ag-ui";
import { HttpAgent } from "@ag-ui/client";

type Props = {
  threadId: string;
  children: React.ReactNode;
};

export function AgentRuntimeProvider({
  threadId,
  children,
}: Props) {
  const agent = useMemo(
    () =>
      new HttpAgent({
        url: "/api/agent/run",
        agentId: "main-agent",
        threadId,
      }),
    [threadId],
  );

  const history = useMemo(
    () => ({
      async load() {
        const response = await fetch(
          `/api/threads/${threadId}/state`,
        );

        if (!response.ok) {
          throw new Error(
            "会話履歴を読み込めませんでした",
          );
        }

        const data = await response.json();

        const messages = fromAgUiMessages(
          data.messages,
        );

        return ExportedMessageRepository.fromArray(
          messages,
        );
      },

      async append() {
        /*
         * メッセージ保存はバックエンドの
         * Agent APIが一元的に行うため、
         * フロントからは保存しない。
         */
      },
    }),
    [threadId],
  );

  const runtime = useAgUiRuntime({
    agent,
    adapters: {
      history,
    },
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
```

history adapterの`append`を空にしてよいのは、バックエンドがメッセージを確実に永続化している場合だけです。assistant-uiの公式ドキュメントでも、その場合はバックエンド側の保存を正本にできると説明されています。([assistant-ui][3])

---

## 10. 履歴取得API

assistant-uiが会話を開いたとき、次のAPIを呼びます。

```http
GET /api/threads/{thread_id}/state
```

レスポンス例です。

```json
{
  "thread": {
    "id": "thread-001",
    "title": "設備Aの故障分析"
  },
  "messages": [
    {
      "id": "msg-001",
      "role": "user",
      "content": "設備Aを分析してください"
    },
    {
      "id": "msg-002",
      "role": "assistant",
      "content": "履歴を確認します。",
      "toolCalls": [
        {
          "id": "call-001",
          "type": "function",
          "function": {
            "name": "search_history",
            "arguments": "{\"machine_id\":\"A\"}"
          }
        }
      ]
    },
    {
      "id": "msg-003",
      "role": "tool",
      "toolCallId": "call-001",
      "content": "{\"failure_count\":12}"
    }
  ],
  "uiState": {}
}
```

このAPIはバックエンドAgentの内部状態をすべて返すものではありません。

```text
返す
    UI表示に必要なメッセージ
    Tool Call
    Tool Result
    interrupt情報
    必要なUI状態

返さない
    Agentの内部要約
    秘密情報
    内部作業メモリ
    ツール認証情報
    再開用の内部ステップ情報
```

バックエンドAgentの`state_json`は、バックエンド内だけで使用します。

---

## 11. 復元した会話から新しいメッセージを送る場合

過去の会話を開いた後、ユーザーが新しいメッセージを送ると、assistant-uiの`HttpAgent`は同じ`thread_id`でAgent APIを呼び出します。

```text
thread_id = thread-001

ユーザー:
    「設備Bと比較してください」
```

バックエンドでは次の処理を行います。

```text
1. thread-001のAgentSessionをSQLiteから取得
2. 保存済みの要約・作業メモリ・Tool状態を復元
3. 新しいユーザーメッセージを追加
4. LLMコンテキストを構築
5. Agentを実行
6. assistant-uiへAG-UIイベントを送信
7. 更新後のセッションをSQLiteへ保存
```

つまり、ブラウザから送られてくる過去メッセージだけを頼りにせず、バックエンドがSQLiteから正式なセッションを復元します。

---

## 12. HITLの復元と再開

通常の会話継続だけなら、過去コンテキストと新しいユーザー入力があれば再開できます。

一方、Tool実行前の承認待ちなど、Agent処理の途中から再開する場合は、セッション内に保留状態を保存します。

```json
{
  "schema_version": 1,
  "thread_id": "thread-001",
  "pending_execution": {
    "kind": "tool_approval",
    "step_name": "before_tool_execution",
    "tool_call_id": "call-001",
    "tool_name": "send_email",
    "tool_args": {
      "to": "customer@example.com",
      "subject": "報告書"
    },
    "interrupt_id": "interrupt-001"
  }
}
```

承認待ちになった時点で、次の両方を保存します。

```text
agent_sessions
    Agentがどこから再開するか

chat_messages
    assistant-uiが承認UIを再表示するためのinterrupt情報
```

assistant-uiでは、interruptをassistantメッセージの`metadata.custom.agui.interrupts`に保存しておくと、`fromAgUiMessages`による履歴読み込み時に、操作可能な承認待ち状態を再構築できます。([assistant-ui][3])

ユーザーが承認すると、同じ`thread_id`と対応する`interrupt_id`を使って再開します。AG-UIのinterrupt仕様でも、再開は中断時と同じ`threadId`を使用し、未解決interruptに対応するresume情報を送る必要があります。([Agent User Interaction Protocol][4])

バックエンドでは次のように処理します。

```python
async def resume_agent(
    input_: RunAgentInput,
) -> AsyncIterator[BaseEvent]:
    session = await session_manager.load(
        input_.thread_id
    )

    pending = session.pending_execution

    if pending is None:
        raise InvalidResumeError(
            "再開待ちの処理がありません"
        )

    validate_resume(
        pending=pending,
        resume=input_.resume,
    )

    async for event in agent.resume(
        session=session,
        pending=pending,
        response=input_.resume,
    ):
        yield event
```

Pythonのgeneratorや停止中のコルーチンそのものを保存する必要はありません。

```text
保存する
    再開するステップ名
    Tool Call ID
    Tool名と引数
    途中結果
    ユーザーに求めた入力
    interrupt ID

復元後
    保存した状態からAgentの次の処理を呼び出す
```

このように、Agentを明示的な状態遷移として実装します。

---

## 13. 新しい会話の作成

新しい会話では、まずバックエンドで`thread_id`と空のAgentSessionを作成します。

```http
POST /api/threads
```

```json
{
  "id": "thread-002",
  "title": "新しい会話"
}
```

バックエンドでは、同じトランザクションで次を作成します。

```text
chat_threads
    thread-002

agent_sessions
    thread-002の空セッション
```

その後、フロントエンドは次へ遷移します。

```tsx
navigate(`/chat/${thread.id}`);
```

最初のメッセージ送信時も、すでに`thread_id`に対応するAgentSessionが存在するため、通常の会話と同じ経路で処理できます。

---

## 14. サイドバーで会話を選択したときの全体シーケンス

```text
ユーザー
    サイドバーの「設備Aの故障分析」をクリック
        ↓
React Router
    /chat/thread-001 に遷移
        ↓
AgentRuntimeProvider
    thread-001用のHttpAgentを作成
        ↓
history.load()
    GET /api/threads/thread-001/state
        ↓
FastAPI
    chat_messagesをSQLiteから取得
        ↓
assistant-ui
    fromAgUiMessagesで変換
        ↓
<Thread />
    過去の会話を表示
        ↓
ユーザー
    新しいメッセージを送信
        ↓
POST /api/agent/run
    thread_id = thread-001
        ↓
FastAPI
    agent_sessionsからセッションを復元
        ↓
Agent
    過去の状態を引き継いで実行
        ↓
AG-UIイベント
    assistant-uiへストリーミング
        ↓
SQLite
    メッセージとAgentSessionを更新
```

---

## 15. 保存処理の責任分担

保存責任はバックエンドに統一します。

```text
assistant-ui
    画面表示
    ユーザー入力
    Tool/HITL UI
    AG-UIイベントの受信

FastAPI / AgentApiService
    新規メッセージの判定
    Agent実行
    メッセージ保存
    Run状態保存
    セッションチェックポイント保存

SqliteSessionManager
    AgentSessionのロード
    AgentSessionの保存
    revisionによる競合検出
```

フロントエンドとバックエンドの両方が同じメッセージを独立して保存すると、重複や保存順の不整合が起こりやすくなります。

そのため、assistant-uiのhistory adapterは読み込みに使用し、書き込みはAgent API側に集約します。

---

## 16. 最終的な採用構成

```text
会話の識別子
    thread_id

Agentの継続
    SqliteSessionManagerがagent_sessionsを復元

会話コンテキスト
    AgentSessionの要約・メモリ
    ＋chat_messagesの直近履歴

UIの復元
    history adapter
    ＋fromAgUiMessages
    ＋<Thread />

Tool履歴
    chat_messagesに構造化保存

HITLの再開
    AgentSessionにpending_executionを保存
    assistantメッセージにinterrupt情報を保存

Agent実行履歴
    agent_runsで管理

サイドバー
    独自React UI＋React Router

保存責任
    バックエンドへ一元化
```

この構成では、バックエンドを再起動しても、ブラウザを閉じても、別の端末から同じ会話を開いても、`thread_id`からAgentセッションと画面履歴を復元できます。

また、Agentの内部実装とassistant-uiの表示形式を分離しているため、将来assistant-uiやAG-UIの形式が変わっても、変換層を修正することで対応できます。

実装は、最初に`SqliteSessionManager`、`chat_messages`保存処理、`GET /api/threads/{thread_id}/state`、assistant-uiのhistory adapterの順で追加すると、通常会話の復元と継続を先に完成させられます。

[1]: https://docs.ag-ui.com/sdk/python/core/types "Types - Agent User Interaction Protocol"
[2]: https://docs.ag-ui.com/concepts/architecture "Core architecture - Agent User Interaction Protocol"
[3]: https://www.assistant-ui.com/docs/runtimes/ag-ui/runtime-options "Runtime options — assistant-ui"
[4]: https://docs.ag-ui.com/concepts/interrupts "Interrupts - Agent User Interaction Protocol"

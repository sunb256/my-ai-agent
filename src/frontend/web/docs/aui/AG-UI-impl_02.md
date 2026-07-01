
## 4. AG UI Runtime Provider を作る

src/runtime/MyRuntimeProvider.tsx
```ts
import { useMemo, type ReactNode } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { HttpAgent } from "@ag-ui/client";

type Props = {
  children: ReactNode;
};

export function MyRuntimeProvider({ children }: Props) {
  const agent = useMemo(() => {
    return new HttpAgent({
      url: import.meta.env.VITE_AG_UI_URL ?? "http://localhost:8000/agent",
    });
  }, []);

  const runtime = useAgUiRuntime({
    agent,
    showThinking: false,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
```

.env.local:
```bash
VITE_AG_UI_URL=http://localhost:8000/agent
```

## 5. App に Thread を表示する

src/App.tsx:

```ts
import { Thread } from "@/components/assistant-ui/thread";
import { MyRuntimeProvider } from "@/runtime/MyRuntimeProvider";

export default function App() {
  return (
    <MyRuntimeProvider>
      <main className="h-dvh">
        <Thread />
      </main>
    </MyRuntimeProvider>
  );
}
```

src/main.tsx (通常の Vite のまま)
```ts
import { StrictMode } from "react";
import { createRoot } from "react-dom/client";
import "./index.css";
import App from "./App";

createRoot(document.getElementById("root")!).render(
  <StrictMode>
    <App />
  </StrictMode>,
);
```


## 6. 起動確認

```bash
cd src/frontend/web
npm run dev
```

ブラウザで:

http://localhost:5173

この時点で Thread UI が表示されれば frontend 側の assistant-ui 構築は OK です。

ただし backend の AG-UI endpoint /agent がまだない場合、メッセージ送信時は失敗します。
最初の確認は「画面が表示されること」までで十分です。

## 7. 今はやらないこと

この段階では以下はまだ不要です。

- @assistant-ui/react-data-stream
- useDataStreamRuntime
- LocalRuntime adapter
- 独自 NDJSON parser
- HITL UI
- tool approval UI

AG UI を使うなら、frontend はまず HttpAgent + useAgUiRuntime + Thread の最小構成でよいです。
次の段階で backend に AG-UI endpoint を作り、RUN_STARTED, TEXT_MESSAGE_*, TOOL_CALL_*, RUN_FINISHED などを返す形に寄せます。


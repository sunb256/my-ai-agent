
作る/変えるファイルは2つです。

src/frontend/web/src/components/AgUiInterruptCard.tsx   新規
src/frontend/web/src/components/assistant-ui/thread.tsx  最小変更

今の右下用 AgUiInterruptPanel.tsx は使わなくなります。すぐ消してもいいですが、まずは未使用にしておくだけでもよいです。

1. 新規: AgUiInterruptCard.tsx

```tsx
import {
  useAgUiInterrupts,
  useAgUiSubmitInterruptResponses,
} from "@assistant-ui/react-ag-ui";
import { useAuiState } from "@assistant-ui/react";
import { Button } from "@/components/ui/button";

export function AgUiInterruptCard() {
  const status = useAuiState((s) => s.message.status);
  const interrupts = useAgUiInterrupts();
  const submit = useAgUiSubmitInterruptResponses();

  if (status?.type !== "requires-action" || status.reason !== "interrupt") {
    return null;
  }

  if (interrupts.length === 0) {
    return null;
  }

  return (
    <div className="mt-3 rounded-lg border border-border bg-background p-4 text-foreground shadow-sm">
      <div className="mb-3 text-sm font-medium">Tool confirmation</div>

      {interrupts.map((interrupt) => (
        <div key={interrupt.id}>
          <div className="mb-3 text-sm">{interrupt.message}</div>

          <div className="flex justify-end gap-2">
            <Button
              variant="outline"
              onClick={() =>
                submit([
                  {
                    interruptId: interrupt.id,
                    status: "cancelled",
                  },
                ])
              }
            >
              Deny
            </Button>

            <Button
              onClick={() =>
                submit([
                  {
                    interruptId: interrupt.id,
                    status: "resolved",
                    payload: { approved: true },
                  },
                ])
              }
            >
              Approve
            </Button>
          </div>
        </div>
      ))}
    </div>
  );
}
```

2. thread.tsx にimport追加

上のimport群付近に追加します。
```tsx
import { AgUiInterruptCard } from "@/components/AgUiInterruptCard";
```

3. AssistantMessage 内に1行追加

MessagePrimitive.GroupedParts の直後、MessageError の前がよいです。

今の構造はこうです。

<MessagePrimitive.GroupedParts>
  ...
</MessagePrimitive.GroupedParts>
<MessageError />

これをこうします。

<MessagePrimitive.GroupedParts>
  ...
</MessagePrimitive.GroupedParts>

<AgUiInterruptCard />

<MessageError />

この位置なら、assistant messageの本文領域内に確認カードが出ます。

4. App.tsx から右下パネルを外す

今こうなら:

import { AgUiInterruptPanel } from "@/components/AgUiInterruptPanel";

削除します。

JSXも削除します。

<AgUiInterruptPanel />

最終的に:

<MyRuntimeProvider>
  <main className="h-dvh">
    <Thread />
  </main>
</MyRuntimeProvider>

変更量

新規コンポーネント: 1ファイル
thread.tsx: import 1行 + JSX 1行
App.tsx: import削除 + JSX削除

この形なら thread.tsx へのアプリ固有変更は最小です。ロジックは全部 AgUiInterruptCard.tsx に閉じ込められます。
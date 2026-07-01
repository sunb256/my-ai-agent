たたき台としては、**assistant-ui の `Thread` はチャット本体として残し、外側を shadcn の `SidebarProvider` / `SidebarInset` でアプリレイアウト化する**のが一番きれいです。AG-UI 側は `HttpAgent` + `useAgUiRuntime` + `AssistantRuntimeProvider` で包む形が公式の最小構成です。assistant-ui の AG-UI Runtime は AG-UI 準拠バックエンドと接続するための runtime adapter で、streaming、tool call、state snapshot などを扱えます。([assistant-ui][1]) assistant-ui の `Thread` は message list、composer、auto-scroll などを含むチャットコンテナなので、まずはここを中央領域に置けばよいです。([assistant-ui][2]) shadcn の sidebar は `SidebarProvider`、`Sidebar`、`SidebarInset`、`SidebarTrigger` で構成するのが基本です。([ui.shadcn.com][3])

```txt
src/
  App.tsx
  runtime/
    ag-ui-runtime-provider.tsx
  components/
    layout/
      app-layout.tsx
      app-sidebar.tsx
      app-header.tsx
    assistant-ui/
      thread.tsx        // 既に作成済み or shadcn registry で追加したもの
```

必要なら追加するものはこのあたりです。

```bash
cd src/frontend/web
npm add @assistant-ui/react @assistant-ui/react-ag-ui @ag-ui/client lucide-react

npx shadcn@latest add sidebar button separator badge dropdown-menu avatar
npx shadcn@latest add https://r.assistant-ui.com/thread.json
```

`src/runtime/ag-ui-runtime-provider.tsx`

```tsx
import { PropsWithChildren, useMemo } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { HttpAgent } from "@ag-ui/client";

const AG_UI_URL =
  import.meta.env.VITE_AG_UI_URL ?? "http://localhost:8000/agent";

export function AgUiRuntimeProvider({ children }: PropsWithChildren) {
  const agent = useMemo(() => {
    return new HttpAgent({
      url: AG_UI_URL,
    });
  }, []);

  const runtime = useAgUiRuntime({
    agent,
    showThinking: true,
  });

  return (
    <AssistantRuntimeProvider runtime={runtime}>
      {children}
    </AssistantRuntimeProvider>
  );
}
```

`src/components/layout/app-layout.tsx`

```tsx
import type { PropsWithChildren } from "react";
import {
  SidebarInset,
  SidebarProvider,
} from "@/components/ui/sidebar";
import { AppHeader } from "./app-header";
import { AppSidebar } from "./app-sidebar";

export function AppLayout({ children }: PropsWithChildren) {
  return (
    <SidebarProvider>
      <AppSidebar />

      <SidebarInset>
        <div className="flex h-svh flex-col bg-background">
          <AppHeader />

          <main className="min-h-0 flex-1 overflow-hidden">
            {children}
          </main>
        </div>
      </SidebarInset>
    </SidebarProvider>
  );
}
```

`src/components/layout/app-sidebar.tsx`

```tsx
import {
  Bot,
  FileText,
  History,
  MessageSquare,
  Settings,
  SlidersHorizontal,
  Wrench,
} from "lucide-react";

import {
  Sidebar,
  SidebarContent,
  SidebarFooter,
  SidebarGroup,
  SidebarGroupContent,
  SidebarGroupLabel,
  SidebarHeader,
  SidebarMenu,
  SidebarMenuButton,
  SidebarMenuItem,
  SidebarRail,
} from "@/components/ui/sidebar";
import { Badge } from "@/components/ui/badge";

const mainItems = [
  { title: "Chat", icon: MessageSquare, href: "#" },
  { title: "Runs", icon: History, href: "#" },
  { title: "Files", icon: FileText, href: "#" },
];

const configItems = [
  { title: "Agent Settings", icon: SlidersHorizontal, href: "#" },
  { title: "Tools", icon: Wrench, href: "#" },
  { title: "Settings", icon: Settings, href: "#" },
];

export function AppSidebar() {
  return (
    <Sidebar collapsible="icon">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg">
              <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                <Bot className="size-4" />
              </div>

              <div className="grid flex-1 text-left text-sm leading-tight">
                <span className="truncate font-semibold">
                  Agent Console
                </span>
                <span className="truncate text-xs text-muted-foreground">
                  assistant-ui + AG-UI
                </span>
              </div>
            </SidebarMenuButton>
          </SidebarMenuItem>
        </SidebarMenu>
      </SidebarHeader>

      <SidebarContent>
        <SidebarGroup>
          <SidebarGroupLabel>Main</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {mainItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild tooltip={item.title}>
                    <a href={item.href}>
                      <item.icon />
                      <span>{item.title}</span>
                    </a>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>

        <SidebarGroup>
          <SidebarGroupLabel>Config</SidebarGroupLabel>
          <SidebarGroupContent>
            <SidebarMenu>
              {configItems.map((item) => (
                <SidebarMenuItem key={item.title}>
                  <SidebarMenuButton asChild tooltip={item.title}>
                    <a href={item.href}>
                      <item.icon />
                      <span>{item.title}</span>
                    </a>
                  </SidebarMenuButton>
                </SidebarMenuItem>
              ))}
            </SidebarMenu>
          </SidebarGroupContent>
        </SidebarGroup>
      </SidebarContent>

      <SidebarFooter>
        <div className="px-2 py-2">
          <Badge variant="outline" className="w-full justify-center">
            local
          </Badge>
        </div>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
```

`src/components/layout/app-header.tsx`

```tsx
import { Plus, Settings2 } from "lucide-react";

import { Button } from "@/components/ui/button";
import { Separator } from "@/components/ui/separator";
import { SidebarTrigger } from "@/components/ui/sidebar";

export function AppHeader() {
  return (
    <header className="flex h-14 shrink-0 items-center gap-3 border-b bg-background px-4">
      <SidebarTrigger />

      <Separator orientation="vertical" className="h-5" />

      <div className="min-w-0 flex-1">
        <h1 className="truncate text-sm font-medium">
          Chat
        </h1>
        <p className="truncate text-xs text-muted-foreground">
          AG-UI backend に接続中
        </p>
      </div>

      <div className="flex items-center gap-2">
        <Button variant="outline" size="sm">
          <Plus className="mr-2 size-4" />
          New Chat
        </Button>

        <Button variant="ghost" size="icon">
          <Settings2 className="size-4" />
        </Button>
      </div>
    </header>
  );
}
```

`src/App.tsx`

```tsx
import { Thread } from "@/components/assistant-ui/thread";
import { AppLayout } from "@/components/layout/app-layout";
import { AgUiRuntimeProvider } from "@/runtime/ag-ui-runtime-provider";

export default function App() {
  return (
    <AgUiRuntimeProvider>
      <AppLayout>
        <div className="h-full">
          <Thread />
        </div>
      </AppLayout>
    </AgUiRuntimeProvider>
  );
}
```

ポイントは、`Thread` の中身を最初から大きく改造しないことです。まずは外枠だけを `AppLayout` として作り、左サイドバーには `Chat / Runs / Files / Agent Settings / Tools / Settings` くらいを置く。次に `Agent Settings` や `Tools` を本物の画面に分離して、React Router を入れる、という順序が扱いやすいです。

この構成だと後から、ヘッダに「選択中のプロファイル」「モデル名」「実行状態」、サイドバーに「スレッド履歴」「ツールON/OFF」「config profile」を追加できます。今の段階では、チャット本体とアプリ管理UIを分ける境界としてちょうどよいです。

[1]: https://www.assistant-ui.com/docs/runtimes/ag-ui/overview "AG-UI Agent Runtime — assistant-ui"
[2]: https://www.assistant-ui.com/docs/ui/thread "Thread Component — assistant-ui"
[3]: https://ui.shadcn.com/docs/components/radix/sidebar "Sidebar - shadcn/ui"

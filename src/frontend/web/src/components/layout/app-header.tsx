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
        <h1 className="truncate text-sm font-medium">Chat</h1>
        <p className="truncate text-xs text-muted-foreground">AG-UI backendに接続中 ...</p>
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
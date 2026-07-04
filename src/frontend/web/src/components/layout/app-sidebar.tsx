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

const mainItems = [
  { title: "Chat", icon: MessageSquare, href: "#" },
  { title: "Runs", icon: History, href: "#" },
  { title: "Files", icon: FileText, href: "#" },
]

const configItems = [
  { title: "Agent Settings", icon: SlidersHorizontal, href: "#" },
  { title: "Tools", icon: Wrench, href: "#" },
  { title: "Settings", icon: Settings, href: "#" },
]

export function AppSidebar() {
  return (
    <Sidebar collapsible="icon" className="bg-gray-100">
      <SidebarHeader>
        <SidebarMenu>
          <SidebarMenuItem>
            <SidebarMenuButton size="lg">
              <div className="flex size-8 items-center justify-center rounded-md bg-primary text-primary-foreground">
                {/* <span className="text-red-400">F</span> */}
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
                  <SidebarMenuButton asChild>
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

      <SidebarGroup>
        <SidebarGroupLabel>Config</SidebarGroupLabel>
        <SidebarGroupContent>
          <SidebarMenu>
            {configItems.map((item) => (
              <SidebarMenuItem key={item.title}>
                <SidebarMenuButton asChild>
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

      <SidebarFooter>
        <div className="px-2 py-2">
        </div>
      </SidebarFooter>

      <SidebarRail />
    </Sidebar>
  );
}
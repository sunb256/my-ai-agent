import { useMemo, type ReactNode } from "react";
import { AssistantRuntimeProvider } from "@assistant-ui/react";
import { useAgUiRuntime } from "@assistant-ui/react-ag-ui";
import { HttpAgent } from "@ag-ui/client";

type Props = {
  children: ReactNode;
}

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
  )
}
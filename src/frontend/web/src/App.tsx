// import './App.css'
import { Thread } from "@/components/assistant-ui/thread";
import { AppLayout } from "@/components/layout/app-layout";
import { MyRuntimeProvider } from "@/runtime/MyRuntimeProvider";
import { TooltipProvider } from "@/components/ui/tooltip";

export default function App() {
  return (
    <MyRuntimeProvider>
      <TooltipProvider delayDuration={0}>
        <AppLayout>
          <main className="h-full">
            <Thread />
          </main>
        </AppLayout>
      </TooltipProvider>
    </MyRuntimeProvider>
  );
}
// import './App.css'
import { Thread } from "@/components/assistant-ui/thread";
import { AppLayout } from "@/components/layout/app-layout";
import { MyRuntimeProvider } from "@/runtime/MyRuntimeProvider";

export default function App() {
  return (
    <MyRuntimeProvider>
      <AppLayout>
        <main className="h-full">
          <Thread />
        </main>
      </AppLayout>
    </MyRuntimeProvider>
  )
}

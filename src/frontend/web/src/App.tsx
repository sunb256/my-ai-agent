// import './App.css'
import { Thread } from "@/components/assistant-ui/thread"
import { MyRuntimeProvider } from "@/runtime/MyRuntimeProvider"
import { AgUiInterruptPanel } from "@/components/AgUiInterruptPanel"

export default function App() {
  return (
    <MyRuntimeProvider>
      <main className="h-dvh">
        <Thread />
        <AgUiInterruptPanel />
      </main>
    </MyRuntimeProvider>
  )
}

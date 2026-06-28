// import './App.css'
import { Thread } from "@/components/assistant-ui/thread"
import { MyRuntimeProvider } from "@/runtime/MyRuntimeProvider"

export default function App() {
  return (
    <MyRuntimeProvider>
      <main className="h-dvh">
        <Thread />
      </main>
    </MyRuntimeProvider>
  )
}

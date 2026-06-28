
# src/frontend/web に assistant-ui + AG UI を構築する手順

## 前提

AG UI 構成では、frontend は HttpAgent で backend の AG-UI endpoint を叩き、
useAgUiRuntime で assistant-ui に接続します。


## 1. Vite + React + TS を作る

```bash
mkdir -p src/frontend
cd src/frontend

npm create vite@latest web -- --template react-ts
cd web

npm install
```

## 2. assistant-ui / AG UI を入れる


1. Tailwind 関連を入れる

Tailwind v4 前提

```bash
npm install tailwindcss @tailwindcss/vite tw-animate-css
```

2. CSS に Tailwind を読み込む

src/index.css の先頭にこれを入れます。
```css
@import "tailwindcss";
@import "tw-animate-css";
```

3. aliasの処理  

@types/node install

```bash
npm install -D @types/node
```

vite.config.ts
```ts
import path from "node:path";
import tailwindcss from "@tailwindcss/vite";
import react from "@vitejs/plugin-react";
import { defineConfig } from "vite";

export default defineConfig({
  plugins: [react(), tailwindcss()],
  resolve: {
    alias: {
      "@": path.resolve(__dirname, "./src"),
    },
  },
});
```

src/frontend/web/tsconfig.json
```json
{
  "files": [],
  "references": [
    { "path": "./tsconfig.app.json" },
    { "path": "./tsconfig.node.json" }
  ],
  "compilerOptions": {
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

src/frontend/web/tsconfig.app.json
```json
{
  "compilerOptions": {

    /* tsconfig に alias  */
    "paths": {
      "@/*": ["./src/*"]
    }
  }
}
```

4. cn helper を作る

```bash
npm install clsx tailwind-merge lucide-react
mkdir -p src/lib
```

src/lib/utils.ts:
```ts
import { type ClassValue, clsx } from "clsx";
import { twMerge } from "tailwind-merge";

export function cn(...inputs: ClassValue[]) {
  return twMerge(clsx(inputs));
}
```

5. 初期化

```bash
npx assistant-ui@latest init

Initializing assistant-ui in existing project...

✔ You need to create a components.json file to add components. Proceed? … yes
✔ Select a component library › Radix
✔ Which preset would you like to use? › Nova
✔ Preflight checks.
✔ Verifying framework. Found Vite.
✔ Validating Tailwind CSS. Found v4.
✔ Validating import alias.
✔ Writing components.json.
✔ Checking registry.
✔ Installing dependencies.
✔ Created 13 files:
  - @/lib/utils.ts
  - @/components/ui/button.tsx
  - @/components/ui/tooltip.tsx
  - @/components/ui/avatar.tsx
  - @/components/ui/collapsible.tsx
  - @/components/ui/dialog.tsx
  - @/components/assistant-ui/tooltip-icon-button.tsx
  - @/components/assistant-ui/tool-fallback.tsx
  - @/components/assistant-ui/tool-group.tsx
  - @/components/assistant-ui/attachment.tsx
  - @/components/assistant-ui/markdown-text.tsx
  - @/components/assistant-ui/reasoning.tsx
  - @/components/assistant-ui/thread.tsx
✔ Updating src/index.css
The `tooltip` component has been added. Remember to wrap your app with the `TooltipProvider` component.

title="app/layout.tsx"
----
import { TooltipProvider } from "@/components/ui/tooltip"

export default function RootLayout({ children }: { children: React.ReactNode }) {
  return (
    <html lang="en">
      <body>
        <TooltipProvider>{children}</TooltipProvider>
      </body>
    </html>
  )
}
----

✓ Project initialized successfully!
```

これで通常は src/components/assistant-ui/thread.tsx などが生成されます。


6. AG UI runtime install

```bash
npm install @assistant-ui/react-ag-ui @ag-ui/client
```



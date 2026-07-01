
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
viteの初期設定を含んでいるので以下に置き換える
```css
@import "tailwindcss";
@import "tw-animate-css";
@import "shadcn/tailwind.css";
@import "tw-shimmer";
@import "@fontsource-variable/geist";

@custom-variant dark (&:is(.dark *));

:root {
  --background: oklch(1 0 0);
  --foreground: oklch(0.145 0 0);

  --card: oklch(1 0 0);
  --card-foreground: oklch(0.145 0 0);

  --popover: oklch(1 0 0);
  --popover-foreground: oklch(0.145 0 0);

  --primary: oklch(0.205 0 0);
  --primary-foreground: oklch(0.985 0 0);

  --secondary: oklch(0.97 0 0);
  --secondary-foreground: oklch(0.205 0 0);

  --muted: oklch(0.97 0 0);
  --muted-foreground: oklch(0.556 0 0);

  --accent: oklch(0.97 0 0);
  --accent-foreground: oklch(0.205 0 0);

  --destructive: oklch(0.577 0.245 27.325);

  --border: oklch(0.922 0 0);
  --input: oklch(0.922 0 0);
  --ring: oklch(0.708 0 0);

  --radius: 0.625rem;
}

.dark {
  --background: oklch(0.145 0 0);
  --foreground: oklch(0.985 0 0);

  --card: oklch(0.205 0 0);
  --card-foreground: oklch(0.985 0 0);

  --popover: oklch(0.205 0 0);
  --popover-foreground: oklch(0.985 0 0);

  --primary: oklch(0.922 0 0);
  --primary-foreground: oklch(0.205 0 0);

  --secondary: oklch(0.269 0 0);
  --secondary-foreground: oklch(0.985 0 0);

  --muted: oklch(0.269 0 0);
  --muted-foreground: oklch(0.708 0 0);

  --accent: oklch(0.269 0 0);
  --accent-foreground: oklch(0.985 0 0);

  --destructive: oklch(0.704 0.191 22.216);

  --border: oklch(1 0 0 / 10%);
  --input: oklch(1 0 0 / 15%);
  --ring: oklch(0.556 0 0);
}

@theme inline {
  --font-sans: "Geist Variable", sans-serif;

  --color-background: var(--background);
  --color-foreground: var(--foreground);
  --color-card: var(--card);
  --color-card-foreground: var(--card-foreground);
  --color-popover: var(--popover);
  --color-popover-foreground: var(--popover-foreground);
  --color-primary: var(--primary);
  --color-primary-foreground: var(--primary-foreground);
  --color-secondary: var(--secondary);
  --color-secondary-foreground: var(--secondary-foreground);
  --color-muted: var(--muted);
  --color-muted-foreground: var(--muted-foreground);
  --color-accent: var(--accent);
  --color-accent-foreground: var(--accent-foreground);
  --color-destructive: var(--destructive);
  --color-border: var(--border);
  --color-input: var(--input);
  --color-ring: var(--ring);

  --radius-sm: calc(var(--radius) * 0.6);
  --radius-md: calc(var(--radius) * 0.8);
  --radius-lg: var(--radius);
  --radius-xl: calc(var(--radius) * 1.4);
  --radius-2xl: calc(var(--radius) * 1.8);
}

html,
body,
#root {
  min-height: 100%;
}

body {
  margin: 0;
  background: var(--background);
  color: var(--foreground);
  font-family: var(--font-sans);
}

#root {
  min-height: 100svh;
}
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



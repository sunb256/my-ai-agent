import Editor from "@monaco-editor/react";
import { cn } from "@/lib/utils";

const CODE_VIEWER_LINE_HEIGHT = 17.2;
const CODE_VIEWER_LINE_HEIGHT2 = 22;
const CODE_VIEWER_MIN_HEIGHT = 56;
const CODE_VIEWER_MAX_HEIGHT = 560;
const CODE_VIEWER_CHARS_PER_LINE = 100;

const languageAliases: Record<string, string> = {
  "": "plaintext",
  unknown: "plaintext",
  text: "plaintext",
  txt: "plaintext",
  plain: "plaintext",
  py: "python",
  js: "javascript",
  jsx: "javascript",
  ts: "typescript",
  tsx: "typescript",
  sh: "shell",
  bash: "shell",
  zsh: "shell",
  yml: "yaml",
  md: "markdown",
};

function normalizeMonacoLanguage(language?: string) {
  const key = (language ?? "").trim().toLowerCase();
  return languageAliases[key] ?? key;
}

function codeViewerHeight(value: string) {
  const lines = value.trimEnd().split("\n");

  const visualLines = lines.reduce((sum, line) => {
    return sum + Math.max(1, Math.ceil(line.length / CODE_VIEWER_CHARS_PER_LINE));
  }, 0);

  return `${Math.min(
    CODE_VIEWER_MAX_HEIGHT,
    Math.max(CODE_VIEWER_MIN_HEIGHT, visualLines * CODE_VIEWER_LINE_HEIGHT2),
  )}px`;
}

export function MonacoCodeViewer({
  value,
  language,
  className,
}: {
  value: string;
  language?: string;
  className?: string;
}) {
  return (
    <div className={cn("overflow-hidden border rounded-sm border-gray-200 bg-muted/50", className)}>
      {/* <Editor
        height={codeViewerHeight(value)}
        language={normalizeMonacoLanguage(language)}
        value={value}
        theme="vs-light"
        options={{
          readOnly: true,
          minimap: { enabled: false },
          lineNumbers: "on",
          wordWrap: "off",
          scrollBeyondLastLine: false,
          folding: false,
          renderLineHighlight: "none",
          automaticLayout: true,
          lineHeight: CODE_VIEWER_LINE_HEIGHT,
          padding: {
            top: 7,
            bottom: 7,
          },
        }}
      /> */}
      <Editor
        height={codeViewerHeight(value)}
        language={normalizeMonacoLanguage(language)}
        value={value}
        theme="vs-light"
        options={{
          // 読み取り専用
          readOnly: true,
          domReadOnly: true,

          // 見た目
          minimap: { enabled: false },
          lineNumbers: "on",
          // lineNumbersMinChars: 3,
          glyphMargin: false,
          folding: false,
          renderLineHighlight: "none",
          renderValidationDecorations: "off",
          overviewRulerLanes: 0,
          hideCursorInOverviewRuler: true,

          // 折り返し
          wordWrap: "off",

          // スクロール
          scrollBeyondLastLine: false,
          scrollBeyondLastColumn: 2,
          scrollbar: {
            vertical: "auto",
            horizontal: "auto",
            useShadows: false,
            verticalScrollbarSize: 10,
            horizontalScrollbarSize: 10,
            alwaysConsumeMouseWheel: false,
          },

          stickyScroll: {
            enabled: false,
          },

          // レイアウト
          automaticLayout: true,
          lineHeight: CODE_VIEWER_LINE_HEIGHT,
          padding: {
            top: 7,
            bottom: 7,
          },

          // viewer として不要そうな機能を抑える
          contextmenu: true,
          hover: { enabled: false },
          links: false,
          quickSuggestions: false,
          suggestOnTriggerCharacters: false,
          parameterHints: { enabled: false },
          codeLens: false,
          // lightbulb: { enabled: false },

          // 長い行・大きめコード対策
          stopRenderingLineAfter: 2000,

        }}
      />
    </div>
  );
}

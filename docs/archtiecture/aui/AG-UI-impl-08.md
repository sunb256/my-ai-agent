
## 設定ファイル構成

はい、構成としてはできます。**assistant-ui側にサイドバーやヘッダを足して設定画面を作り、FastAPI経由で `agent_config.yml` を読み書きする構成は自然です。** ただし「簡単」と言えるのはUIとAPIの箱までで、実運用では **バリデーション、秘匿項目の扱い、実行中Agentへの反映方法** を少し丁寧に設計した方がよいです。

assistant-uiはReactのUIコンポーネント、runtime、primitivesを使ってAIチャットUIを組み立てるライブラリなので、チャット画面の外側に自前のヘッダ、サイドバー、設定ページを置くのは普通のReact実装としてできます。公式ドキュメントでも、assistant-uiはReact向けのコンポーネント、runtime、primitivesを提供し、カスタマイズ可能なAIチャットUIを作る用途として説明されています。([assistant-ui][1]) また、ThreadListSidebarやAssistantSidebarのようなサイドバー系コンポーネントも用意されており、独自レイアウトに組み込む前提の説明があります。([assistant-ui][2])

おすすめの構成はこうです。

```text
frontend
  ├─ ChatPage
  │   └─ assistant-ui Thread
  ├─ Header
  │   └─ model / profile / settings button
  └─ ConfigPage or ConfigDrawer
      └─ GET /api/agent-config
      └─ PUT /api/agent-config

backend
  ├─ FastAPI
  ├─ agent_config.yml
  ├─ Pydantic Config Model
  ├─ AgentFactory
  └─ AG-UI stream endpoint
```

大事なのは、**frontendから直接YAMLを編集させるのではなく、FastAPIが「編集可能な設定だけ」をJSONとして出し入れすること**です。frontendはJSONフォームを編集し、backendがPydanticで検証してからYAMLに保存します。FastAPIはPydanticモデルによる検証やJSON Schema生成と相性がよく、設定管理にはPydantic Settingsも公式に案内されています。([FastAPI][3])

たとえばAPIはこのくらいで十分です。

```text
GET  /api/agent-config
PUT  /api/agent-config
POST /api/agent-config/reload
```

`GET` は現在の設定を返す。`PUT` は保存する。`reload` はAgentに反映する、という分離です。

backend側のイメージはこうです。

```python
from pathlib import Path
from typing import Literal

import yaml
from fastapi import APIRouter, HTTPException
from pydantic import BaseModel, Field

router = APIRouter()

CONFIG_PATH = Path("config/agent_config.yml")


class LlmConfig(BaseModel):
    provider: Literal["openai", "litellm", "ollama"]
    model: str
    temperature: float = Field(ge=0.0, le=2.0)


class AgentConfig(BaseModel):
    llm: LlmConfig
    max_steps: int = Field(ge=1, le=50)
    enabled_tools: list[str] = Field(default_factory=list)
    system_profile: str = "default"


def load_agent_config() -> AgentConfig:
    if not CONFIG_PATH.exists():
        raise HTTPException(status_code=404, detail="config not found")

    data = yaml.safe_load(CONFIG_PATH.read_text(encoding="utf-8")) or {}
    return AgentConfig.model_validate(data)


def save_agent_config(config: AgentConfig) -> None:
    tmp_path = CONFIG_PATH.with_suffix(".yml.tmp")

    text = yaml.safe_dump(
        config.model_dump(),
        allow_unicode=True,
        sort_keys=False,
    )

    tmp_path.write_text(text, encoding="utf-8")
    tmp_path.replace(CONFIG_PATH)


@router.get("/api/agent-config", response_model=AgentConfig)
async def get_agent_config() -> AgentConfig:
    return load_agent_config()


@router.put("/api/agent-config", response_model=AgentConfig)
async def update_agent_config(config: AgentConfig) -> AgentConfig:
    save_agent_config(config)
    return config
```

frontend側は普通のReactフォームで十分です。

```tsx
import { useEffect, useState } from "react";

type AgentConfig = {
  llm: {
    provider: "openai" | "litellm" | "ollama";
    model: string;
    temperature: number;
  };
  max_steps: number;
  enabled_tools: string[];
  system_profile: string;
};

export function AgentConfigPanel() {
  const [config, setConfig] = useState<AgentConfig | null>(null);

  useEffect(() => {
    fetch("/api/agent-config")
      .then((res) => res.json())
      .then(setConfig);
  }, []);

  if (!config) return <div>Loading...</div>;

  async function save() {
    await fetch("/api/agent-config", {
      method: "PUT",
      headers: { "Content-Type": "application/json" },
      body: JSON.stringify(config),
    });
  }

  return (
    <div>
      <label>
        Model
        <input
          value={config.llm.model}
          onChange={(e) =>
            setConfig({
              ...config,
              llm: { ...config.llm, model: e.target.value },
            })
          }
        />
      </label>

      <label>
        Temperature
        <input
          type="number"
          min={0}
          max={2}
          step={0.1}
          value={config.llm.temperature}
          onChange={(e) =>
            setConfig({
              ...config,
              llm: {
                ...config.llm,
                temperature: Number(e.target.value),
              },
            })
          }
        />
      </label>

      <button onClick={save}>Save</button>
    </div>
  );
}
```

ただし、ここは注意した方がいいです。**`agent_config.yml` を全部そのままfrontendに返さない方がいい**です。特に以下はfrontendに出さない方が安全です。

```text
LLM API key
system prompt全文
内部toolの詳細定義
顧客別ライセンス条件
RAG接続情報
DB接続文字列
外部API token
承認ルールの詳細
```

frontendから編集できるのは、たとえばこの程度に絞るのがよいです。

```text
使用モデル
temperature
max_steps
有効化するtoolのON/OFF
プロンプトプロファイル名
表示名
ログ出力レベル
添付ファイル許可
```

設計としては、内部設定と公開設定を分けるのが安全です。

```text
agent_config.yml
  backend内部用
  秘匿情報や詳細設定を含む

agent_public_config
  frontend編集用
  UIから変更してよい項目だけ
```

YAMLファイルを直接更新する場合の実務上の注意点は3つあります。

1つ目は、**保存前に必ずPydanticで検証すること**です。これをやらないと、UIから変な値が入ってAgentが起動不能になります。

2つ目は、**実行中のrunには途中反映しないこと**です。ユーザーAがチャット中に、ユーザーBがmodel設定を変えると、途中から挙動が変わって事故ります。基本は「run開始時にconfig snapshotを作る」が安全です。

```python
config = config_store.get_snapshot()
agent = agent_factory.create(config=config)
```

3つ目は、**ファイル保存はatomicにすること**です。直接 `agent_config.yml` に上書きすると、保存途中でプロセスが落ちたときに壊れます。上の例のように一度 `.tmp` に書いてから `replace()` する方が安全です。

最終的には、こういう責務分離がよいです。

```text
assistant-ui / React
  設定画面を表示する
  編集可能な項目だけ送る
  YAML構造は知らない

FastAPI
  設定JSONを受け取る
  Pydanticで検証する
  YAMLへ保存する
  必要ならAgentへreload通知する

Agent Core
  config snapshotを受け取って実行する
  frontendの存在を知らない
```

なので、方向性は合っています。
**UI設定画面をassistant-uiの周辺に作るのは簡単です。FastAPI経由で `agent_config.yml` を変更するのもできます。ただし、YAMLをそのまま編集APIにするのではなく、「公開してよい設定だけをPydanticモデル化して読み書きする」形にした方が、長期的に壊れにくいです。**

[1]: https://www.assistant-ui.com/docs "https://www.assistant-ui.com/docs"
[2]: https://www.assistant-ui.com/docs/ui/assistant-sidebar "https://www.assistant-ui.com/docs/ui/assistant-sidebar"
[3]: https://fastapi.tiangolo.com/advanced/settings/ "https://fastapi.tiangolo.com/advanced/settings/"

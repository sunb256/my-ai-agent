
## 技術スタック

```
frontend/
  Vite
  React
  TypeScript
  Tailwind CSS
  assistant-ui
  React Router
```

## 構成

```
1. Agent Backend
   - エージェント実行
   - prompt管理
   - tool管理
   - 設定管理
   - イベント配信
   - OpenAI互換APIも任意で提供

2. Standard Web Console
   - assistant-uiでChat画面
   - Reactで設定画面
   - capabilities/schemaを読んで動的フォーム生成
   - 顧客はブラウザで設定するだけ

3. CLI
   - 同じBackend APIを叩く
   - 開発者・運用者向け

assistant-uiが担当しやすい部分
  ├─ メッセージ一覧
  ├─ 入力欄
  ├─ ストリーミング表示
  ├─ tool callの表示
  ├─ 添付ファイル表示
  ├─ スレッド表示
  └─ 実行中キャンセル
  
自作する標準Console部分
  ├─ LLM接続設定
  ├─ Agent作成
  ├─ prompt profile選択
  ├─ tool有効/無効
  ├─ approval policy設定
  ├─ max_stepsなどの実行設定
  ├─ ユーザー管理
  └─ 実行ログ確認

backend
  ├─ /chat
  ├─ /runs
  ├─ /events
  ├─ /agents
  ├─ /prompt-profiles
  ├─ /tools
  ├─ /capabilities
  └─ /settings

cli
  └─ backendの同じAPIを叩く
```


## 動作フロー

agent_id
  ↓
prompt_profile
  ↓
system prompt
  ↓
allowed tools
  ↓
approval policy
  ↓
max_steps
  ↓
agent実行



## 構築

docker compose up -d
↓
http://localhost:xxxx にアクセス
↓
管理者アカウント作成
↓
LLM接続設定
↓
Agent作成
↓
Prompt Profileを選択
↓
利用ToolをON/OFF
↓
Chat画面で利用開始



## 秘匿化

```
services:
  backend:
    image: your-agent-backend:latest
    environment:
      EDITION: minimum
      LICENSE_KEY: xxxx

same image
  ├─ Aさん: EDITION=minimum
  └─ Bさん: EDITION=full


1. マルチステージビルド
2. builderにはソースをCOPY
3. uv sync --locked --no-editable
4. finalには .venv だけCOPY
5. finalには uv もソースツリーも入れない
6. system promptやAPIキーはイメージに入れずDB/env/secretで渡す

- 最終Dockerイメージにソースを入れない
- PythonならNuitka/Cython/PyInstallerなどを検討
- APIキーや秘密情報はイメージに入れず環境変数/secretで渡す
- ライセンスキー方式を入れる
- private registryで配布する
- 利用規約・契約で再配布/解析を禁止する
```





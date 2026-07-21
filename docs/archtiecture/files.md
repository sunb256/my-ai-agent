## 結論

現在のテキスト出力はそのまま残し、別経路として **Artifact（成果物）** を追加するのがよいです。

```text
LLMの回答
├─ テキストメッセージ
├─ Tool Call
└─ Artifact参照
    ├─ report.pdf
    ├─ analysis.xlsx
    └─ result.csv
```

ファイル本体をLLMの回答やAG-UIイベントに埋め込むのではなく、バックエンドのストレージに保存し、チャットにはファイルIDやメタデータだけを送ります。

---

## 推奨する全体構成

```text
User
  │ 「添付したCSVから報告書を作って」
  ▼
Agent
  │
  ├─ read_attachment(...)
  ├─ execute_python(...)       作業ディレクトリにファイル生成
  └─ publish_artifact(...)     成果物として公開
          │
          ▼
ArtifactService
  ├─ ファイル検証
  ├─ 永続ストレージへ移動
  ├─ DBへメタデータ登録
  └─ artifact.createdイベント発行
          │
          ▼
AG-UI
  ├─ TOOL_CALL_RESULT
  ├─ CUSTOM: artifact.created
  └─ TEXT_MESSAGE: 「報告書を作成しました」
          │
          ▼
assistant-ui
  ├─ チャット内 ArtifactCard
  └─ サイドバー Files
```

AG-UIにはアプリ独自のデータを送るための `CustomEvent` があり、`name` と `value` で独自イベントを定義できます。成果物通知にはこれを使うのが自然です。([Agent User Interaction Protocol][1])

---

# 1. ファイル生成と成果物公開を分離する

エージェントに最初から永続保存先へ直接書かせるのではなく、Runごとの作業ディレクトリを用意します。

```text
/workspaces/
  run-abc123/
    input/
      sales.csv
    work/
      chart.png
      summary.md
      report.pdf
```

このうちユーザーに見せるのは、`publish_artifact` が明示的に公開したものだけです。

```python
publish_artifact(
    path="work/report.pdf",
    title="売上分析レポート",
    description="添付CSVを集計したPDFレポート",
)
```

こうすると、Pythonスクリプト、一時CSV、中間画像などを誤ってユーザーに公開することがありません。

---

# 2. Artifactのデータモデル

最低限、次の情報を持たせます。

```python
from datetime import datetime
from pydantic import BaseModel


class ArtifactRecord(BaseModel):
    id: str
    thread_id: str
    run_id: str
    user_id: str

    filename: str
    title: str
    description: str | None = None

    media_type: str
    size_bytes: int
    sha256: str

    storage_key: str
    status: str = "ready"

    tool_call_id: str | None = None
    source_artifact_ids: list[str] = []

    created_at: datetime
    expires_at: datetime | None = None
```

DBにはファイル本体ではなく、メタデータと保存場所だけを入れます。

```sql
CREATE TABLE artifacts (
    id TEXT PRIMARY KEY,
    thread_id TEXT NOT NULL,
    run_id TEXT NOT NULL,
    user_id TEXT NOT NULL,

    filename TEXT NOT NULL,
    title TEXT NOT NULL,
    description TEXT,

    media_type TEXT NOT NULL,
    size_bytes INTEGER NOT NULL,
    sha256 TEXT NOT NULL,

    storage_key TEXT NOT NULL,
    status TEXT NOT NULL,

    tool_call_id TEXT,
    source_artifact_ids_json TEXT NOT NULL DEFAULT '[]',

    created_at TEXT NOT NULL,
    expires_at TEXT
);

CREATE INDEX idx_artifacts_thread
    ON artifacts(thread_id, created_at DESC);

CREATE INDEX idx_artifacts_user
    ON artifacts(user_id, created_at DESC);
```

単一サーバ構成なら、保存先は次のようなローカルディスクで十分です。

```text
/data/artifacts/
  <user-id>/
    <artifact-id>/
      report.pdf
```

将来複数サーバにするときは、`ArtifactStorage` の実装だけをS3互換ストレージへ交換します。

---

# 3. Toolは2段階にする

## 作業用Tool

```text
write_file
execute_python
render_markdown
create_docx
create_xlsx
create_pdf
```

これらは作業ディレクトリにファイルを作るだけです。

## 公開用Tool

```text
publish_artifact
```

このToolだけが、ユーザーに渡す成果物を登録します。

```python
class PublishArtifactArgs(BaseModel):
    path: str
    title: str
    description: str | None = None
    filename: str | None = None
```

エージェントに渡す説明は、例えば次のようにします。

```python
description = """
Publish a completed file as a user-visible artifact.

Only publish final files that the user should be able to download.
Do not publish temporary files, scripts, caches, or intermediate data.
The path must refer to a file inside the current run workspace.
"""
```

この方式なら、Word、Excel、PDF、CSV、画像、ZIPなど、ファイル形式ごとにエージェント全体の仕組みを変更する必要がありません。

---

# 4. ArtifactServiceの実装例

```python
from __future__ import annotations

import hashlib
import mimetypes
import shutil
from pathlib import Path
from uuid import uuid4


class ArtifactError(Exception):
    pass


class ArtifactService:
    def __init__(
        self,
        artifact_root: Path,
        repository,
        max_size_bytes: int = 100 * 1024 * 1024,
    ):
        self._artifact_root = artifact_root.resolve()
        self._repository = repository
        self._max_size_bytes = max_size_bytes

    def publish(
        self,
        *,
        workspace_root: Path,
        relative_path: str,
        user_id: str,
        thread_id: str,
        run_id: str,
        title: str,
        description: str | None,
        filename: str | None = None,
        tool_call_id: str | None = None,
    ) -> ArtifactRecord:
        workspace_root = workspace_root.resolve()
        source = (workspace_root / relative_path).resolve()

        # workspace外へのパストラバーサル防止
        if not source.is_relative_to(workspace_root):
            raise ArtifactError("Path is outside the run workspace")

        if not source.is_file():
            raise ArtifactError("Artifact file does not exist")

        if source.is_symlink():
            raise ArtifactError("Symbolic links cannot be published")

        size = source.stat().st_size
        if size > self._max_size_bytes:
            raise ArtifactError("Artifact exceeds the size limit")

        artifact_id = str(uuid4())
        output_name = Path(filename or source.name).name

        destination_dir = (
            self._artifact_root / user_id / artifact_id
        ).resolve()
        destination_dir.mkdir(parents=True, exist_ok=False)

        destination = destination_dir / output_name
        shutil.copy2(source, destination)

        media_type = (
            mimetypes.guess_type(output_name)[0]
            or "application/octet-stream"
        )

        sha256 = self._calculate_sha256(destination)

        artifact = ArtifactRecord(
            id=artifact_id,
            thread_id=thread_id,
            run_id=run_id,
            user_id=user_id,
            filename=output_name,
            title=title,
            description=description,
            media_type=media_type,
            size_bytes=size,
            sha256=sha256,
            storage_key=str(destination.relative_to(self._artifact_root)),
            tool_call_id=tool_call_id,
            source_artifact_ids=[],
            created_at=datetime.now(),
        )

        self._repository.insert(artifact)
        return artifact

    @staticmethod
    def _calculate_sha256(path: Path) -> str:
        digest = hashlib.sha256()

        with path.open("rb") as file:
            for chunk in iter(lambda: file.read(1024 * 1024), b""):
                digest.update(chunk)

        return digest.hexdigest()
```

実際には、ファイル拡張子だけでなく、必要に応じて実データからMIMEタイプを検証した方が安全です。

---

# 5. Tool結果にはファイル本体を入れない

Toolの返却値は次の程度で十分です。

```json
{
  "artifact_id": "64d1a4e8-...",
  "filename": "sales-report.pdf",
  "title": "売上分析レポート",
  "media_type": "application/pdf",
  "size_bytes": 284193,
  "status": "ready"
}
```

LLMにはこの情報を返します。

```text
Artifact published successfully:
artifact_id=64d1a4e8-...
filename=sales-report.pdf
```

PDFのバイナリやBase64をLLMコンテキストに戻してはいけません。トークンを消費するだけでなく、会話履歴やDBも膨らみます。

assistant-uiにはBase64のFile Message Partを表示する実装がありますが、小さな一時ファイルには便利でも、永続成果物ではURLまたはArtifact IDを使った独自カードの方が適しています。公式の標準File UIも、Base64データから `data:` URLを生成する構成です。([assistant-ui][2])

---

# 6. AG-UIへの流し方

通常のToolイベントはそのまま流します。

```text
TOOL_CALL_START
TOOL_CALL_ARGS
TOOL_CALL_END
TOOL_CALL_RESULT
```

Tool結果の後に、成果物専用のCustomEventを追加します。

```python
from ag_ui.core import CustomEvent, EventType


yield encoder.encode(
    CustomEvent(
        type=EventType.CUSTOM,
        name="artifact.created",
        value={
            "id": artifact.id,
            "threadId": artifact.thread_id,
            "runId": artifact.run_id,
            "title": artifact.title,
            "description": artifact.description,
            "filename": artifact.filename,
            "mediaType": artifact.media_type,
            "sizeBytes": artifact.size_bytes,
            "downloadUrl": f"/api/artifacts/{artifact.id}/download",
        },
    )
)
```

その後、通常のテキスト回答を送ります。

```text
売上データを集計し、PDFレポートを作成しました。
```

したがって最終出力は「テキストしかない」のではなく、次の組み合わせになります。

```text
AG-UI stream
├─ text message
├─ tool call result
└─ custom artifact event
```

AG-UIはイベント駆動で、テキスト、Tool Call、状態、独自イベントを同じストリームに載せる設計です。([Agent User Interaction Protocol][3])

---

# 7. ダウンロードAPI

ファイルシステム上のパスを直接公開してはいけません。必ずArtifact ID経由にします。

```python
from fastapi import APIRouter, Depends, HTTPException
from fastapi.responses import FileResponse

router = APIRouter()


@router.get("/api/artifacts/{artifact_id}/download")
async def download_artifact(
    artifact_id: str,
    current_user=Depends(require_user),
):
    artifact = artifact_repository.get(artifact_id)

    if artifact is None:
        raise HTTPException(status_code=404)

    if artifact.user_id != current_user.id:
        raise HTTPException(status_code=403)

    path = artifact_storage.resolve(artifact.storage_key)

    return FileResponse(
        path=path,
        media_type=artifact.media_type,
        filename=artifact.filename,
    )
```

必要なAPIは、まず次の3つです。

```text
GET /api/artifacts/{id}
GET /api/artifacts/{id}/download
GET /api/threads/{thread_id}/artifacts
```

Files画面を作るなら、追加で以下を用意します。

```text
GET    /api/artifacts
DELETE /api/artifacts/{id}
```

---

# 8. assistant-ui側の表示

表示場所は2つあると使いやすいです。

## チャット内

Tool UIとしてカードを出します。

```text
┌────────────────────────────────────┐
│ PDF  売上分析レポート              │
│ sales-report.pdf · 278 KB          │
│                                    │
│ [プレビュー]       [ダウンロード] │
└────────────────────────────────────┘
```

assistant-uiはTool Callに独自Reactコンポーネントを割り当て、実行中、完了、エラー、結果を表示できます。([assistant-ui][4])

概念的には次のような実装です。

```tsx
type ArtifactResult = {
  artifact_id: string;
  title: string;
  filename: string;
  media_type: string;
  size_bytes: number;
};

function PublishArtifactTool({
  result,
  status,
}: {
  result?: ArtifactResult;
  status: { type: string };
}) {
  if (status.type === "running") {
    return <div>成果物を保存しています...</div>;
  }

  if (!result) {
    return null;
  }

  return (
    <ArtifactCard
      title={result.title}
      filename={result.filename}
      mediaType={result.media_type}
      sizeBytes={result.size_bytes}
      downloadUrl={`/api/artifacts/${result.artifact_id}/download`}
    />
  );
}
```

## Filesサイドバー

チャット内カードとは別に、Thread単位の成果物を一覧表示します。

```text
Files
├─ sales-report.pdf
├─ sales-summary.xlsx
└─ chart.png
```

会話を再表示するときは、メッセージ履歴だけでなく、

```text
GET /api/threads/{thread_id}/artifacts
```

も呼んで成果物一覧を復元します。

AG-UIのイベント履歴自体も永続化できますが、ファイルの正本はArtifactテーブルで管理する方が明確です。AG-UIのシリアライズはチャット履歴やUI状態の復元に向いています。([Agent User Interaction Protocol][5])

---

# 9. ファイル形式別の作り方

形式ごとに、LLMが直接バイナリを作るわけではありません。

| 形式             | 生成方法                    |
| -------------- | ----------------------- |
| TXT / Markdown | `write_file`            |
| CSV / JSON     | Pythonまたは直接書き込み         |
| Excel          | `openpyxl`              |
| Word           | `python-docx`           |
| PDF            | HTML→PDF、ReportLabなど    |
| PowerPoint     | `python-pptx`           |
| PNG / SVG      | matplotlib、Pillow、SVG生成 |
| ZIP            | Python `zipfile`        |

おすすめは、LLMにライブラリを直接意識させすぎず、次のような専用Toolを用意する方式です。

```text
create_spreadsheet(spec)
create_document(spec)
create_pdf(spec)
create_presentation(spec)
```

内部ではPythonライブラリやテンプレートを使用します。

一方、自由度が必要な場合は、

```text
execute_python
publish_artifact
```

の組み合わせを使います。

両方を併用するとよいです。

```text
定型成果物   → create_documentなど
特殊な成果物 → execute_python + publish_artifact
```

---

# 10. 最初に実装する最小構成

現在の構成からなら、次の順番が現実的です。

1. `artifacts` テーブルとローカル保存領域を追加
2. `publish_artifact` Toolを追加
3. ダウンロードAPIを追加
4. Tool結果にArtifactメタデータを返す
5. assistant-uiにArtifactCardを追加
6. `artifact.created` CustomEventを追加
7. Filesサイドバーを追加

最初はCustomEventなしでも動かせます。`publish_artifact` のTool結果をTool UIでカード表示すれば、チャット内での生成とダウンロードまでは実現できます。

その後CustomEventを追加すると、Tool UIとは独立してFilesパネルへ即時反映できるようになります。

## 推奨する最終形

```text
Agent
├─ 入力ファイルを読む
├─ workspaceで処理する
├─ ファイルを生成する
├─ publish_artifactで成果物化する
└─ テキストで内容を説明する

Backend
├─ ArtifactService
├─ ArtifactRepository
├─ ArtifactStorage
├─ Download API
└─ AG-UI CustomEvent

Frontend
├─ Tool進捗表示
├─ ArtifactCard
├─ Preview
└─ Filesパネル
```

つまり、テキスト出力をファイル出力へ置き換えるのではありません。**テキスト回答に、永続化されたArtifact参照を加える**という拡張になります。これなら今あるTool Call、会話履歴、添付ファイル処理を壊さずに追加できます。

[1]: https://docs.ag-ui.com/concepts/events "Events - Agent User Interaction Protocol"
[2]: https://www.assistant-ui.com/docs/ui/file "File — assistant-ui"
[3]: https://docs.ag-ui.com/?utm_source=chatgpt.com "AG-UI Overview - Agent User Interaction Protocol"
[4]: https://www.assistant-ui.com/docs/tools/tool-ui "Tool UI — assistant-ui"
[5]: https://docs.ag-ui.com/concepts/serialization "Serialization - Agent User Interaction Protocol"



残し続ける設計にはしません。**一時ファイルは短時間で削除、Artifactは保存期限を持たせて削除**するのが基本です。

おすすめは次の分離です。

| 種別                  |     保存期間の目安 | 削除タイミング          |
| ------------------- | ----------: | ---------------- |
| Run中の一時ファイル         |     Run終了まで | 成功・失敗に関係なく終了時に削除 |
| 失敗調査用ファイル           |      数時間〜数日 | 定期クリーンアップ        |
| 通常Artifact          |      30〜90日 | 期限切れで削除          |
| ユーザーが保存指定したArtifact |    無期限または長期 | ユーザー削除・管理者方針     |
| 入力添付ファイル            | 会話保持期間に合わせる | 会話削除・期限切れ        |

## 1. 一時ファイル

一時ファイルはRunごとのディレクトリに置きます。

```text
/workspaces/
  run-123/
    input/
    work/
    output/
```

Run終了時に削除します。

```python
import shutil
from pathlib import Path


async def run_agent(run_id: str):
    workspace = Path("/data/workspaces") / run_id
    workspace.mkdir(parents=True)

    try:
        return await execute_agent(workspace)
    finally:
        shutil.rmtree(workspace, ignore_errors=True)
```

ただし、処理失敗時に調査したい場合は、即削除ではなく期限を設定します。

```text
成功Run    → 即削除
失敗Run    → 24時間保持
実行中断   → 24時間保持
```

重要なのは、`finally` だけに依存しないことです。プロセス強制終了やサーバ再起動では実行されないため、定期クリーンアップも必要です。

---

## 2. Artifact

Artifactには保存期限を持たせます。

```python
class ArtifactRecord(BaseModel):
    id: str
    storage_key: str
    created_at: datetime
    expires_at: datetime | None
    pinned: bool = False
    deleted_at: datetime | None = None
```

通常は次のようにします。

```text
通常作成      → 30日後に削除
ユーザー保存  → pinned = true
会話削除      → 関連Artifactも削除
```

UIでは、例えば次のように表示できます。

```text
売上レポート.pdf
有効期限: 2026-08-21
[保存する] [削除]
```

「保存する」を押したら、

```text
pinned = true
expires_at = null
```

にします。

ただし、社内システムなら完全無期限は避け、管理者側で最大保持期間を設定できる方が安全です。

---

## 3. 定期クリーンアップ処理

APSchedulerや既存Workerで1日1回実行すれば十分です。

```python
from datetime import datetime, timezone


def cleanup_expired_artifacts():
    now = datetime.now(timezone.utc)

    artifacts = repository.find_expired(
        now=now,
        limit=500,
    )

    for artifact in artifacts:
        try:
            storage.delete(artifact.storage_key)
            repository.mark_deleted(artifact.id)
        except Exception:
            logger.exception(
                "Failed to delete artifact: %s",
                artifact.id,
            )
```

一度に全件処理せず、500件などに分けます。

```text
毎日 03:00
  ├─ 期限切れArtifactを500件取得
  ├─ ファイル削除
  ├─ DB更新
  └─ 残っていれば次の500件
```

---

## 4. ファイル削除とDB削除の順序

いきなりDB行を削除するより、状態を持たせた方が安全です。

```text
ready
  ↓
deleting
  ↓
deleted
```

処理は次の順序です。

```text
1. DBをdeletingに更新
2. ストレージ上のファイルを削除
3. DBをdeletedに更新
4. 一定期間後にDB行自体を削除
```

ファイル削除に失敗しても、次回再試行できます。

DB行を先に完全削除すると、ストレージ上にファイルだけが残る孤児ファイルが発生します。

---

## 5. 孤児ファイル対策

実運用では次の2種類が発生します。

```text
DBにはあるがファイルがない
ファイルはあるがDBにはない
```

そのため、週1回程度の整合性チェックを入れます。

```text
Artifact DB
    ↕ 照合
Artifact Storage
```

特にArtifact作成途中でアプリが落ちると、DB未登録のファイルが残る可能性があります。

保存ディレクトリをArtifact ID単位にしておけば、照合しやすいです。

```text
/data/artifacts/
  user-1/
    artifact-id-1/
    artifact-id-2/
```

---

## 6. 容量上限も必要

期限だけでなく、ユーザー単位やシステム全体の容量制限も用意した方がよいです。

例:

```text
1ファイル最大          100 MB
1ユーザー合計          5 GB
システム全体           500 GB
通常保持期間           30日
保存指定Artifact上限   100件
```

上限超過時には、古い未保存Artifactから削除します。

```text
削除優先順位
1. 期限切れArtifact
2. 未保存で最も古いArtifact
3. 失敗Runの一時ファイル
4. 保存指定Artifactは自動削除しない
```

ディスク使用率でも制御します。

```text
70% → 警告
80% → 期限切れを即時削除
90% → 古い未保存Artifactを削除
95% → 新規ファイル生成を拒否
```

---

## 7. 入力添付ファイルとの関係

入力添付ファイルと出力Artifactは別管理がよいです。

```text
attachments
artifacts
```

ただし、同じファイルを複数箇所にコピーすると容量を消費します。

必要なら、実ファイルを共通のBlobとして管理できます。

```text
blobs
  sha256
  storage_key
  size
  reference_count

attachments
  blob_id

artifacts
  blob_id
```

同じファイル内容なら、同じBlobを参照します。

```text
attachment A ─┐
artifact B   ─┼─ blob xyz
artifact C   ─┘
```

参照がゼロになったBlobだけ削除します。

ただし最初からここまで実装すると複雑なので、初期版では単純な別ファイル保存でも問題ありません。

---

## 8. 実装しやすい現実的な方針

現在の構成なら、まずはこれで十分です。

```text
一時ファイル
- /data/workspaces/{run_id}
- 成功時は即削除
- 失敗時は24時間保持
- 1時間ごとに古いworkspaceを削除

Artifact
- 通常30日保持
- pinnedなら期限なし
- 毎日1回期限切れを削除
- 1ファイル100MBまで
- 1ユーザー5GBまで
```

DBは次の程度追加します。

```sql
ALTER TABLE artifacts ADD COLUMN expires_at TEXT;
ALTER TABLE artifacts ADD COLUMN pinned INTEGER NOT NULL DEFAULT 0;
ALTER TABLE artifacts ADD COLUMN status TEXT NOT NULL DEFAULT 'ready';
ALTER TABLE artifacts ADD COLUMN deleted_at TEXT;
```

## 推奨ライフサイクル

```text
一時ファイル
作成 → 使用 → Artifact化 → Run終了 → 削除

Artifact
作成 → ready → 期限切れ → deleting → deleted

保存指定Artifact
作成 → ready → pinned → ユーザー削除まで保持
```

つまり、**一時ファイルは原則残さず、Artifactも期限付きで残す**設計です。ユーザーが明示的に保存した成果物だけ長期保持にするのが、容量・使いやすさ・運用負荷のバランスがよいです。

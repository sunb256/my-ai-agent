# AGENTS.md

## 概要

リポジトリ構成
- Backend: Python + uv

## 基本方針

- 変更は最小限に留める
- 既存の実装パターンを優先する
- 影響範囲を明示する
- 作業中に新しい未コミット変更を検知した場合は含める


## 実装ルール

### Backend

- 既存構成を崩さない
- 例外処理は既存のエラーハンドリング方針に合わせる
- logging では秘密情報や過剰な内部情報を出力しない

### Python / uv

- Python は `uv` を使用
- 実行・検証コマンドは `uv run` を使う


## 確認コマンド


```bash
uv run ruff check .
uv run mypy .
uv run pytest
```

- lint / format / type check が導入されている場合は、repo の既存コマンドに従う


## レビュー方法

- frontend の変更レビューでは `frontend-review` skill を使うこと


## 注意事項

- gitのブランチは `dev` がなければ作成して `dev` で作業

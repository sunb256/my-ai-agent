---
name: data-file-analysis
description: sandbox 内でアップロード済みの CSV、Excel、JSON、PDF、Markdown、テキストファイルを解析するときに使う。ファイル構造、列、シート、ページの概要を確認し、次の分析手順を決めるための skill。
---

# データファイル解析

ユーザがデータファイルやドキュメントファイルの確認、要約、検証、分析を依頼したときに使う。

## 手順

1. ファイルがホスト側にある場合は、まず `upload_file` で sandbox の `/tmp` 配下へ配置する。
2. 個別分析を始める前に、同梱の profiler を実行する。

```bash
python /tmp/skills/data-file-analysis/scripts/profile_file.py /tmp/input.xlsx --limit 5
```

3. profiler が返す JSON を見て、次に必要な分析を決める。
4. より詳しい分析が必要な場合は、利用可能なら `pandas`、`openpyxl`、`fitz`、`markitdown` を使って `exec_python` で処理する。
5. 最終回答では実装の詳細ではなく、ユーザの質問に対する答えを中心にする。

## 注意点

- 計算やファイル解析は、できるだけ決定的なコードで行う。
- Excel ファイルでは、分析対象のシートを選ぶ前にシート名を確認する。
- CSV ファイルでは、集計前に列、欠損値、数値列の概要を確認する。
- PDF やテキストファイルでは、結論を出す前に抽出されたテキストを確認する。
- 必要なライブラリが無い場合は、その制約を伝え、可能なら別の方法で確認する。

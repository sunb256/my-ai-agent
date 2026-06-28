---
name: data-file-analysis
description: Use this skill when the user asks to inspect, profile, summarize, validate, or analyze uploaded data/document files in the sandbox, including
  Excel/xlsx/xls spreadsheets, CSV/TSV, JSON/JSONL, PDF, Markdown, and text files. Use it for checking workbook sheet names, sheet structure, columns, data
  types, missing values, sample rows, file structure, and deciding the next analysis steps before computing results such as rankings, totals, statistics, or
  JSON answers. 日本語では、Excel、xlsx、CSV、シート構造、列確認、欠損確認、ファイル分析、データ分析、集計、ランキング、JSON出力などを依頼されたときに使う。
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

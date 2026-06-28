


## code execution

```bash
# exec_python
uv run my-ai-agent "次のデータをカテゴリ別に合計して、JSONだけ答えて: A,120 B,90 A,75 C,200 B,125 A,55 C,80"

# bash_tool
uv run my-ai-agent "bash_toolを使って sandbox 内で pwd と python --version を実行し、結果だけ答えて"
uv run my-ai-agent "bash_toolを使って sandbox 内で /tmp/log.txt を作り、ERROR の行数だけ数えて答えて。内容は次: INFO start, ERROR db, WARN retry, ERROR timeout, INFO done"
> 2行です。

uv run my-ai-agent "/tmp/report.txt に3行のテキストを書き込み、その後 wc -l /tmp/report.txt と cat /tmp/report.txt を実行して、結果だけ答えて。3行は alpha, beta, gamma"

> wc -l の結果: 3
> cat の結果:
> alpha
> beta
> gamma


uv run my-ai-agent --verbose "Pythonで pandas と openpyxl を使い、sandbox 内に /tmp/sample_sales.xlsx を作成してから読み直し、city別の
  sales合計をJSONだけ答えて。データは Tokyo 120, Osaka 90, Tokyo 80, Nagoya 60, Osaka 110"


# upload_files
uv run my-ai-agent "./src/agent/tests/samples/pop_area_2009.xlsx upload_file で sandbox にアップロードして、bash_tool で awk を使って 人口密度が高い国TOP10を挙げて"

人口密度が高い国TOP10は以下の通りです。

*   マカオ: 20,426.00
*   モナコ: 16,244.00
*   シンガポール: 6,773.00
*   香港: 6,361.00
*   ジブラルタル: 5,174.00
*   バチカン: 1,782.00
*   マルタ: 1,293.00
*   バミューダ諸島: 1,201.00
*   バングラデシュ: 1,127.00
*   バーレーン: 1,068.00
```



## skills

```bash
uv run my-ai-agent "./src/agent/tests/samples/pop_area_2009.xlsx を upload_file でアップロードして、data-file-analysis skills を使い、シート構造を確認してから人口密度が高い国TOP10をJSONだけで答えて"
```


# WEB UI

## 確認方法

```bash
cd src/frontend/web && npm run dev

# -> http://localhost:5173
```


## HITL確認

```bash
先にテストファイルを作ります。

echo test > /tmp/agui-hitl-test.txt

Web画面で送ります。

delete_file ツールで /tmp/agui-hitl-test.txt を削除して

期待する状態:

- /agent のレスポンスに RUN_FINISHED + outcome.type: "interrupt" が出る
- interrupts[0].reason が "confirmation"
- metadata.tool_name が "delete_file"
- まだ承認していないのでファイルは残る
```

# WebAPI

## 確認方法

起動方法

```bash
uv run uvicorn api.main:app --reload
```

確認
```bash
curl http://127.0.0.1:8000/healthz
```

stream確認
```bash
curl -N -X POST 'http://127.0.0.1:8000/api/v1/chat?session_id=test-session' \
    -H "content-type: application/json" \
    -d '{"prompt":"短く自己紹介して"}'
```
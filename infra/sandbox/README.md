

```bash
docker build -t ai-agent-python:local -f infra/sandbox/Dockerfile .

# convert tar for microsandbox
docker save ai-agent-python:local -o /tmp/ai-agent-python.tar

# load microsandbox
.venv/lib/python3.14/site-packages/microsandbox/_bundled/bin/msb image load \
    -i /tmp/ai-agent-python.tar \
    -t ai-agent-python:local

# list image
.venv/lib/python3.14/site-packages/microsandbox/_bundled/bin/msb image list

ai-agent-python:local    sha256:9459f18fb826    133.9 MiB    2026-06-14 23:48:07
python                   sha256:9bb1441ba9bd    384.8 MiB    2026-06-13 19:09:20
```

config.yml
```yml
agent:
    code_exec: True
    code_exec_image: "ai-agent-python:local"
```
結論としては、**`plugin_name + version` を単位に zip を追加インストールし、FastAPI 起動中は `PluginManager` の registry だけ差し替える**設計がよいです。これなら、Web から plugin を追加しても backend 再起動なしで新しい request から使えます。

前提はこの方式です。

```text
- plugin は zip 配布
- plugin 内の package 名は version 入りにする
- 外部依存は vendor/ に同梱する
- native extension は禁止
- 同じ name + version の上書きは禁止
- version を上げた plugin を追加する
- registry は reload 時に丸ごと差し替える
```

全体像はこうです。

```text
FastAPI 起動時
  PluginManager.load_installed_plugins()
  ↓
  installed/*.zip を読む
  ↓
  各 plugin の最新 version だけロード
  ↓
  ToolRegistry を作り直して差し替え

Web から plugin install
  /plugins/install
  ↓
  zip download
  ↓
  hash / manifest / native extension 検証
  ↓
  installed/plugin-name-0.1.0-xxxx.zip に保存
  ↓
  PluginManager.reload_plugins()
  ↓
  新しい request から利用可能
```

以下は最小構成です。

## 1. plugin 側の構成

plugin zip はこうします。

```text
sample_tools-0.1.0.zip
  plugin.json
  sample_tools_v0_1_0/
    __init__.py
    tools.py
  vendor/
    ...
```

`plugin.json` です。

```json
{
  "name": "sample_tools",
  "version": "0.1.0",
  "api_version": "1",
  "module_prefix": "sample_tools_v0_1_0",
  "entrypoint": "sample_tools_v0_1_0.tools:register"
}
```

`sample_tools_v0_1_0/tools.py` です。

```python
from myagent_sdk import tool


@tool
def add_numbers(a: int, b: int) -> int:
    """Add two integers and return the result."""
    return a + b


@tool(need_confirm=True, confirm_msg_tmpl="Delete file {args}?")
def delete_file(filepath: str) -> str:
    """Deletes a file. This action cannot be undone."""
    return f"File {filepath} has been deleted."


def register():
    return [
        add_numbers,
        delete_file,
    ]
```

plugin 側は `FuncTool` や `BaseTool` を同梱しません。必ず host 側の `myagent_sdk` から `tool` を import します。

## 2. host 側の SDK

plugin から見える場所に `myagent_sdk.py` を置きます。

```python
# myagent_sdk.py

# TODO: あなたの実装に合わせて import path を変更してください
from your_agent.tools import BaseTool, tool

__all__ = [
    "BaseTool",
    "tool",
]
```

ここがかなり重要です。plugin zip の中に `tool` デコレータをコピーして入れると、host 側の `BaseTool` と別物になり、`isinstance` 判定や registry 登録が壊れやすいです。

## 3. PluginManager 実装

以下を `plugin_system.py` のようなファイルに置きます。

```python
from __future__ import annotations

import hashlib
import importlib
import json
import re
import shutil
import sys
import tempfile
import urllib.request
import zipfile
from contextlib import contextmanager
from dataclasses import dataclass
from pathlib import Path
from threading import RLock
from typing import Any, Iterator

# TODO: あなたの実装に合わせて import path を変更してください
from your_agent.context import ExecContext
from your_agent.tools import BaseTool


SEMVER_RE = re.compile(r"^\d+\.\d+\.\d+$")
PLUGIN_NAME_RE = re.compile(r"^[a-zA-Z][a-zA-Z0-9_-]*$")
MODULE_PREFIX_RE = re.compile(r"^[a-zA-Z_][a-zA-Z0-9_]*$")
NATIVE_SUFFIXES = (".so", ".pyd", ".dll", ".dylib")


@dataclass(frozen=True)
class PluginManifest:
    name: str
    version: str
    api_version: str
    module_prefix: str
    entrypoint: str

    @property
    def plugin_id(self) -> str:
        return f"{self.name}@{self.version}"

    @property
    def version_key(self) -> tuple[int, int, int]:
        major, minor, patch = self.version.split(".")
        return int(major), int(minor), int(patch)

    @classmethod
    def from_dict(cls, data: dict[str, Any]) -> "PluginManifest":
        manifest = cls(
            name=str(data["name"]),
            version=str(data["version"]),
            api_version=str(data.get("api_version", "1")),
            module_prefix=str(data["module_prefix"]),
            entrypoint=str(data["entrypoint"]),
        )

        manifest.validate()
        return manifest

    def validate(self) -> None:
        if not PLUGIN_NAME_RE.match(self.name):
            raise ValueError(f"Invalid plugin name: {self.name}")

        if not SEMVER_RE.match(self.version):
            raise ValueError(
                f"Invalid plugin version: {self.version}. "
                "Use semantic version like 0.1.0."
            )

        if not MODULE_PREFIX_RE.match(self.module_prefix):
            raise ValueError(f"Invalid module_prefix: {self.module_prefix}")

        expected_prefix = expected_module_prefix(self.name, self.version)

        if self.module_prefix != expected_prefix:
            raise ValueError(
                f"module_prefix must be {expected_prefix!r}, "
                f"but got {self.module_prefix!r}"
            )

        if not self.entrypoint.startswith(self.module_prefix + "."):
            raise ValueError(
                "entrypoint must start with module_prefix. "
                f"entrypoint={self.entrypoint!r}, module_prefix={self.module_prefix!r}"
            )

        if ":" not in self.entrypoint:
            raise ValueError("entrypoint must be like 'package.module:register'")


@dataclass(frozen=True)
class PluginRecord:
    manifest: PluginManifest
    zip_path: Path
    tools: list[BaseTool]


def normalize_plugin_name(name: str) -> str:
    return re.sub(r"[^a-zA-Z0-9_]", "_", name).lower()


def expected_module_prefix(name: str, version: str) -> str:
    safe_name = normalize_plugin_name(name)
    safe_version = version.replace(".", "_")
    return f"{safe_name}_v{safe_version}"


def sha256_file(path: Path) -> str:
    h = hashlib.sha256()

    with path.open("rb") as f:
        for chunk in iter(lambda: f.read(1024 * 1024), b""):
            h.update(chunk)

    return h.hexdigest()


def read_manifest_from_zip(zip_path: Path) -> PluginManifest:
    with zipfile.ZipFile(zip_path) as zf:
        with zf.open("plugin.json") as f:
            data = json.loads(f.read().decode("utf-8"))

    return PluginManifest.from_dict(data)


def validate_no_native_extensions(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            lower = name.lower()
            if lower.endswith(NATIVE_SUFFIXES):
                raise ValueError(
                    f"Native extension is not allowed in zip plugin: {name}"
                )


def validate_zip_paths(zip_path: Path) -> None:
    with zipfile.ZipFile(zip_path) as zf:
        for name in zf.namelist():
            path = Path(name)

            if path.is_absolute():
                raise ValueError(f"Absolute path is not allowed in plugin zip: {name}")

            if ".." in path.parts:
                raise ValueError(f"Path traversal is not allowed in plugin zip: {name}")


def validate_plugin_zip(zip_path: Path) -> PluginManifest:
    validate_zip_paths(zip_path)
    validate_no_native_extensions(zip_path)

    manifest = read_manifest_from_zip(zip_path)

    expected_init = f"{manifest.module_prefix}/__init__.py"
    expected_module_dir = f"{manifest.module_prefix}/"

    with zipfile.ZipFile(zip_path) as zf:
        names = set(zf.namelist())

    if expected_init not in names:
        raise ValueError(f"Missing plugin package file: {expected_init}")

    if not any(name.startswith(expected_module_dir) for name in names):
        raise ValueError(f"Missing plugin package dir: {expected_module_dir}")

    return manifest


@contextmanager
def temporary_sys_path(paths: list[str]) -> Iterator[None]:
    added: list[str] = []

    for path in reversed(paths):
        if path not in sys.path:
            sys.path.insert(0, path)
            added.append(path)

    importlib.invalidate_caches()

    try:
        yield
    finally:
        for path in added:
            if path in sys.path:
                sys.path.remove(path)

        importlib.invalidate_caches()


def plugin_import_paths(zip_path: Path) -> list[str]:
    resolved = str(zip_path.resolve())

    return [
        f"{resolved}/vendor",
        resolved,
    ]


def resolve_entrypoint(entrypoint: str):
    module_name, attr_name = entrypoint.split(":", maxsplit=1)

    module = importlib.import_module(module_name)

    obj = module
    for part in attr_name.split("."):
        obj = getattr(obj, part)

    return obj


class PluginToolProxy(BaseTool):
    """
    plugin由来のtoolを包む薄いproxy。

    目的:
    - plugin_idを保持する
    - 実行時にplugin zip/vendorをsys.pathへ一時的に入れる
    - host側からは通常のBaseToolとして扱えるようにする
    """

    def __init__(
        self,
        *,
        inner: BaseTool,
        manifest: PluginManifest,
        import_paths: list[str],
    ):
        self.inner = inner
        self.manifest = manifest
        self.import_paths = import_paths

        super().__init__(
            name=inner.name,
            desc=inner.desc,
            tool_def=inner.tool_def,
            need_confirm=getattr(inner, "need_confirm", False),
            confirm_msg_tmpl=getattr(inner, "confirm_msg_tmpl", ""),
        )

    async def exec(self, ctx: ExecContext, **kwargs) -> Any:
        with temporary_sys_path(self.import_paths):
            return await self.inner.exec(ctx=ctx, **kwargs)


def load_plugin_from_zip(zip_path: Path) -> PluginRecord:
    manifest = validate_plugin_zip(zip_path)
    paths = plugin_import_paths(zip_path)

    with temporary_sys_path(paths):
        register = resolve_entrypoint(manifest.entrypoint)
        tools = register()

    if not isinstance(tools, list):
        raise TypeError(
            f"{manifest.entrypoint} must return list[BaseTool]"
        )

    proxied_tools: list[BaseTool] = []

    for tool_obj in tools:
        if not isinstance(tool_obj, BaseTool):
            raise TypeError(
                f"Invalid tool from {manifest.plugin_id}: {tool_obj!r}. "
                "Plugin tools must be created by myagent_sdk.tool"
            )

        proxied_tools.append(
            PluginToolProxy(
                inner=tool_obj,
                manifest=manifest,
                import_paths=paths,
            )
        )

    return PluginRecord(
        manifest=manifest,
        zip_path=zip_path,
        tools=proxied_tools,
    )


class PluginManager:
    def __init__(self, plugins_dir: Path):
        self.plugins_dir = plugins_dir
        self.plugins_dir.mkdir(parents=True, exist_ok=True)

        self._lock = RLock()
        self._records: dict[str, PluginRecord] = {}
        self._tools: dict[str, BaseTool] = {}

    def load_installed_plugins(self) -> None:
        self.reload_plugins()

    def reload_plugins(self) -> None:
        latest = self._find_latest_plugin_zips()

        new_records: dict[str, PluginRecord] = {}
        new_tools: dict[str, BaseTool] = {}

        for zip_path in latest:
            record = load_plugin_from_zip(zip_path)

            if record.manifest.plugin_id in new_records:
                raise ValueError(f"Duplicate plugin: {record.manifest.plugin_id}")

            for tool_obj in record.tools:
                if tool_obj.name in new_tools:
                    raise ValueError(
                        f"Duplicate tool name: {tool_obj.name}. "
                        "Tool names must be globally unique."
                    )

                new_tools[tool_obj.name] = tool_obj

            new_records[record.manifest.plugin_id] = record

        with self._lock:
            self._records = new_records
            self._tools = new_tools

    def install_zip(
        self,
        zip_path: Path,
        *,
        expected_sha256: str | None = None,
    ) -> PluginManifest:
        zip_path = zip_path.resolve()

        if expected_sha256 is not None:
            actual = sha256_file(zip_path)
            if actual != expected_sha256:
                raise ValueError(
                    f"Plugin hash mismatch. expected={expected_sha256}, actual={actual}"
                )

        manifest = validate_plugin_zip(zip_path)
        digest = sha256_file(zip_path)
        dest = self._dest_path(manifest, digest)

        existing_same_version = list(
            self.plugins_dir.glob(f"{manifest.name}-{manifest.version}-*.zip")
        )

        for existing in existing_same_version:
            if sha256_file(existing) == digest:
                # すでに同じものが入っている
                self.reload_plugins()
                return manifest

        if existing_same_version:
            raise ValueError(
                f"{manifest.name}@{manifest.version} is already installed "
                "with different content. Bump plugin version."
            )

        shutil.copyfile(zip_path, dest)

        try:
            self.reload_plugins()
        except Exception:
            dest.unlink(missing_ok=True)
            self.reload_plugins()
            raise

        return manifest

    def install_from_url(
        self,
        url: str,
        *,
        expected_sha256: str | None = None,
    ) -> PluginManifest:
        with tempfile.TemporaryDirectory() as tmp:
            tmp_path = Path(tmp) / "plugin.zip"

            with urllib.request.urlopen(url, timeout=30) as response:
                tmp_path.write_bytes(response.read())

            return self.install_zip(
                tmp_path,
                expected_sha256=expected_sha256,
            )

    def build_session_tools(self, input_: Any) -> list[BaseTool]:
        # 最初は全plugin toolを返す。
        # 後で input_.profile_id などを見て絞る。
        with self._lock:
            return list(self._tools.values())

    def all_tools(self) -> list[BaseTool]:
        with self._lock:
            return list(self._tools.values())

    def list_plugins(self) -> list[dict[str, Any]]:
        with self._lock:
            return [
                {
                    "name": record.manifest.name,
                    "version": record.manifest.version,
                    "plugin_id": record.manifest.plugin_id,
                    "tools": [tool.name for tool in record.tools],
                    "zip_path": str(record.zip_path),
                }
                for record in self._records.values()
            ]

    def _dest_path(self, manifest: PluginManifest, digest: str) -> Path:
        short_hash = digest[:12]
        filename = f"{manifest.name}-{manifest.version}-{short_hash}.zip"
        return self.plugins_dir / filename

    def _find_latest_plugin_zips(self) -> list[Path]:
        candidates: dict[str, tuple[PluginManifest, Path]] = {}

        for zip_path in self.plugins_dir.glob("*.zip"):
            manifest = validate_plugin_zip(zip_path)

            current = candidates.get(manifest.name)
            if current is None:
                candidates[manifest.name] = (manifest, zip_path)
                continue

            current_manifest, _ = current
            if manifest.version_key > current_manifest.version_key:
                candidates[manifest.name] = (manifest, zip_path)

        return [path for _, path in candidates.values()]
```

この実装では、同じ `plugin_name` の plugin が複数 version 入っていても、読み込むのは最新 version だけです。古い version は zip として残りますが、registry には入りません。

## 4. FastAPI への組み込み

`lifespan` で `PluginManager` を作って、`AgentApiService` に渡します。

```python
from contextlib import asynccontextmanager
from pathlib import Path
import os

from fastapi import FastAPI, HTTPException, Request
from fastapi.middleware.cors import CORSMiddleware
from fastapi.responses import StreamingResponse

from plugin_system import PluginManager


@asynccontextmanager
async def lifespan(_: FastAPI):
    load_env()

    config_path = Path(os.environ.get("MY_AI_AGENT_CONFIG", str(DEFAULT_CONFIG)))
    config = load_config(config_path)

    client = get_client(config)
    session_manager = InMemorySessionManager()

    plugin_manager = PluginManager(
        plugins_dir=Path("./plugins/installed"),
    )
    plugin_manager.load_installed_plugins()

    agent = get_agent(
        config=config,
        client=client,
        max_steps=None,
        session_manager=session_manager,
    )

    state.service = AgentApiService(
        agent=agent,
        plugin_manager=plugin_manager,
    )

    try:
        yield
    finally:
        state.service = None


app = FastAPI(
    title="ai-agent-api",
    version="0.1.0",
    lifespan=lifespan,
)

app.add_middleware(
    CORSMiddleware,
    allow_origins=["http://127.0.0.1:5173", "http://localhost:5173"],
    allow_credentials=True,
    allow_methods=["*"],
    allow_headers=["*"],
)


def _get_stream_agent(req: Request, input_: RunAgentInput):
    if state.service is None:
        raise HTTPException(status_code=503, detail="Service not initialized.")

    accept = req.headers.get("accept")

    return state.service.stream_agent(
        input_=input_,
        accept=accept,
    )


@app.get("/healthz")
async def healthz() -> dict[str, bool]:
    return {"ok": True}


@app.post("/agent")
async def agent_endpoint(req: Request):
    body = await req.json()
    input_ = RunAgentInput.model_validate(body)

    stream_agent = _get_stream_agent(req, input_)

    return StreamingResponse(
        stream_agent,
        media_type="text/event-stream",
        headers={
            "Cache-Control": "no-cache",
            "Connection": "keep-alive",
            "X-Accel-Buffering": "no",
        },
    )
```

## 5. AgentApiService 側

`AgentApiService` では、agent 実行直前に plugin tool を取得します。

```python
from typing import AsyncIterator

from plugin_system import PluginManager


class AgentApiService:
    def __init__(
        self,
        agent: Agent,
        plugin_manager: PluginManager,
    ):
        self._agent = agent
        self._plugin_manager = plugin_manager

    async def stream_agent(
        self,
        input_: RunAgentInput,
        accept: str | None,
    ) -> AsyncIterator[str]:
        encoder = EventEncoder(accept=accept)

        yield encoder.encode(
            RunStartedEvent(
                type=EventType.RUN_STARTED,
                thread_id=input_.thread_id,
                run_id=input_.run_id,
            )
        )

        try:
            plugin_tools = self._plugin_manager.build_session_tools(input_)

            result = await self._run_agent(
                input_=input_,
                tools=plugin_tools,
            )

            async for chunk in self._agent_result_to_events(
                encoder=encoder,
                input_=input_,
                result=result,
            ):
                yield chunk

        except Exception as error:
            yield encoder.encode(
                RunErrorEvent(
                    type=EventType.RUN_ERROR,
                    message=str(error),
                    code="agent_error",
                )
            )

        finally:
            yield encoder.encode(
                RunFinishedEvent(
                    type=EventType.RUN_FINISHED,
                    thread_id=input_.thread_id,
                    run_id=input_.run_id,
                )
            )

    async def _run_agent(
        self,
        input_: RunAgentInput,
        tools: list[BaseTool],
    ):
        return await self._agent.run(
            input_=input_,
            tools=tools,
        )

    def reload_plugins(self) -> None:
        self._plugin_manager.reload_plugins()

    def install_plugin_from_url(
        self,
        url: str,
        sha256: str | None = None,
    ) -> dict:
        manifest = self._plugin_manager.install_from_url(
            url,
            expected_sha256=sha256,
        )

        return {
            "name": manifest.name,
            "version": manifest.version,
            "plugin_id": manifest.plugin_id,
        }

    def list_plugins(self) -> list[dict]:
        return self._plugin_manager.list_plugins()
```

ここで重要なのは、`Agent.run()` に `tools` を渡せるようにすることです。

```python
class Agent:
    async def run(
        self,
        input_: RunAgentInput,
        tools: list[BaseTool],
    ) -> AgentResult:
        tool_defs = [tool.tool_def for tool in tools]
        tool_map = {tool.name: tool for tool in tools}

        # LLM呼び出し時
        # response = await client.chat(..., tools=tool_defs)

        # tool_call実行時
        # tool = tool_map[tool_call.name]
        # result = await tool.exec(ctx=ctx, **tool_call.args)

        ...
```

`tool_defs` と `tool_map` は必ず同じ `tools` から作ります。これで「LLM に見せた tool」と「実行できる tool」がズレません。

## 6. plugin 管理 endpoint

Web から plugin を追加する endpoint です。

```python
import asyncio
from pydantic import BaseModel


class InstallPluginRequest(BaseModel):
    url: str
    sha256: str | None = None


@app.post("/plugins/install")
async def install_plugin(req: InstallPluginRequest):
    if state.service is None:
        raise HTTPException(status_code=503, detail="Service not initialized.")

    result = await asyncio.to_thread(
        state.service.install_plugin_from_url,
        req.url,
        req.sha256,
    )

    return {
        "ok": True,
        "plugin": result,
    }


@app.post("/plugins/reload")
async def reload_plugins():
    if state.service is None:
        raise HTTPException(status_code=503, detail="Service not initialized.")

    await asyncio.to_thread(state.service.reload_plugins)

    return {"ok": True}


@app.get("/plugins")
async def list_plugins():
    if state.service is None:
        raise HTTPException(status_code=503, detail="Service not initialized.")

    return {
        "plugins": state.service.list_plugins(),
    }
```

この `install` endpoint を呼ぶと、backend を再起動せずに plugin が追加されます。すでに実行中の `/agent` stream は古い tool list のまま完走し、新しい `/agent` request から新しい plugin tool が使われます。

## 7. plugin zip の作り方

例として `sample_tools` plugin を作ります。

```text
sample_tools/
  plugin.json
  requirements.txt
  sample_tools_v0_1_0/
    __init__.py
    tools.py
```

`requirements.txt` です。

```txt
more-itertools==10.5.0
```

外部ライブラリを使う `tools.py` の例です。

```python
from myagent_sdk import tool
from more_itertools import chunked


@tool
def split_numbers(values: list[int], size: int) -> list[list[int]]:
    """Split integer list into chunks."""
    return [list(chunk) for chunk in chunked(values, size)]


def register():
    return [
        split_numbers,
    ]
```

ビルドコマンドです。

```bash
cd sample_tools
python -m pip install -r requirements.txt --target vendor
python -m zipfile -c ../sample_tools-0.1.0.zip plugin.json sample_tools_v0_1_0 vendor
```

作成した zip の hash を確認します。

```bash
python - <<'PY'
import hashlib
from pathlib import Path

path = Path("sample_tools-0.1.0.zip")
print(hashlib.sha256(path.read_bytes()).hexdigest())
PY
```

install API に投げます。

```bash
curl -X POST http://localhost:5000/plugins/install \
  -H "Content-Type: application/json" \
  -d '{
    "url": "https://example.com/plugins/sample_tools-0.1.0.zip",
    "sha256": "ここにsha256"
  }'
```

ローカルで試すだけなら、`PluginManager.install_zip()` を直接呼んでもよいです。

```python
plugin_manager.install_zip(
    Path("./sample_tools-0.1.0.zip"),
)
```

## 8. version 更新のルール

plugin を更新するときは、package 名も version も変えます。

```text
sample_tools 0.1.0
  module_prefix: sample_tools_v0_1_0
  package: sample_tools_v0_1_0

sample_tools 0.2.0
  module_prefix: sample_tools_v0_2_0
  package: sample_tools_v0_2_0
```

`plugin.json` もこう変えます。

```json
{
  "name": "sample_tools",
  "version": "0.2.0",
  "api_version": "1",
  "module_prefix": "sample_tools_v0_2_0",
  "entrypoint": "sample_tools_v0_2_0.tools:register"
}
```

このルールにしておくと、Python の `sys.modules` キャッシュに邪魔されにくくなります。同じ `name + version` の上書きはしません。修正する場合は必ず version を上げます。

## 9. この設計の制約

この方式はかなり軽く使えますが、完全な隔離ではありません。特に `vendor/` 同梱方式は、次の制約があります。

```text
- pure Python ライブラリ向け
- .so / .pyd を含むライブラリは禁止
- plugin 間で同じ外部ライブラリの別versionを混在させるのは非保証
- 未信頼 plugin を同一プロセスで実行するのは危険
```

`numpy`, `pandas`, `torch`, `opencv`, `lxml`, `cryptography` のようなものを使いたくなったら、その plugin だけ `venv + subprocess` または container 実行に逃がす方が安定します。

この設計なら、最初はかなりシンプルに始められます。

```text
plugin追加:
  backend再起動なし

plugin更新:
  versionを上げて追加

plugin反映:
  registryを丸ごと差し替え

セッション:
  新しいrequestから新registryを使用
```

今の FastAPI 構成にもそのまま乗せやすく、将来的に `McpTool` や `SubprocessPluginTool` を足す場合も、`BaseTool` として registry に入れるだけで拡張できます。

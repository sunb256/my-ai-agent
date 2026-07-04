import asyncio
import os
import re
import tempfile
from dataclasses import dataclass
from pathlib import PurePosixPath
from typing import Self


@dataclass(frozen=True)
class DockerExecResult:
    stdout_text: str
    stderr_text: str
    exit_code: int | None


async def run_docker_command(*args: str, timeout: float | None = None) -> DockerExecResult:
    proc = await asyncio.create_subprocess_exec(
        "docker",
        *args,
        stdout=asyncio.subprocess.PIPE,
        stderr=asyncio.subprocess.PIPE,
    )

    try:
        stdout, stderr = await asyncio.wait_for(proc.communicate(), timeout=timeout)
    except TimeoutError:
        proc.kill()
        stdout, stderr = await proc.communicate()
        return DockerExecResult(
            stdout.decode("utf-8", errors="replace"),
            stderr.decode("utf-8", errors="replace") or "command timed out",
            None,
        )

    return DockerExecResult(
        stdout.decode("utf-8", errors="replace"),
        stderr.decode("utf-8", errors="replace"),
        proc.returncode,
    )


def make_container_name(name: str) -> str:
    normalized = re.sub(r"[^a-zA-Z0-9_.-]", "-", name).strip("-")
    return normalized[:128] or "agent-code-env"


class DockerCodeSandboxFs:
    def __init__(self, sandbox: "DockerCodeSandbox"):
        self._sandbox = sandbox

    async def exists(self, path: str) -> bool:
        result = await self._sandbox.exec("test", ["-e", path])
        return result.exit_code == 0

    async def mkdir(self, path: str) -> None:
        result = await self._sandbox.exec("mkdir", ["-p", path])
        if result.exit_code != 0:
            raise RuntimeError(result.stderr_text or f"failed to create directory: {path}")

    async def write(self, path: str, content: bytes) -> None:
        await self.mkdir(str(PurePosixPath(path).parent))

        temp_path = ""
        try:
            with tempfile.NamedTemporaryFile(delete=False) as temp_file:
                temp_file.write(content)
                temp_path = temp_file.name

            await self.copy_from_host(temp_path, path)
        finally:
            if temp_path:
                try:
                    os.unlink(temp_path)
                except FileNotFoundError:
                    pass

    async def copy_from_host(self, host_path: str, guest_path: str) -> None:
        await self.mkdir(str(PurePosixPath(guest_path).parent))
        result = await run_docker_command("cp", host_path, f"{self._sandbox.name}:{guest_path}")
        if result.exit_code != 0:
            raise RuntimeError(result.stderr_text or f"failed to copy file to sandbox: {guest_path}")


class DockerCodeSandbox:
    def __init__(self, name: str):
        self.name = name
        self.fs = DockerCodeSandboxFs(self)

    @classmethod
    async def create(
        cls,
        name: str,
        *,
        image: str,
        replace: bool = True,
    ) -> Self:
        container_name = make_container_name(name)

        if replace:
            await run_docker_command("rm", "-f", container_name)

        result = await run_docker_command(
            "run",
            "-d",
            "--name",
            container_name,
            "--pull",
            "never",
            image,
            "sleep",
            "infinity",
        )

        if result.exit_code != 0:
            raise RuntimeError(result.stderr_text or f"failed to start Docker code environment: {image}")

        return cls(container_name)

    async def exec(
        self,
        command: str,
        args: list[str] | None = None,
        timeout: float | None = None,
    ) -> DockerExecResult:
        return await run_docker_command("exec", self.name, command, *(args or []), timeout=timeout)

    async def kill(self) -> None:
        await run_docker_command("rm", "-f", self.name)

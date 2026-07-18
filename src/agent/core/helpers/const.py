
from typing import Final, Literal, TypeAlias

ToolStatus: TypeAlias = Literal["success", "error"]
STR_SUCCESS: Final[Literal["success"]] = "success"
STR_ERROR: Final[Literal["error"]] = "error"

SYSTEM = "system"
USER = "user"
ASSISTANT = "assistant"
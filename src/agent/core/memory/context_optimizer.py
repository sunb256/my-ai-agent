import inspect
import json
from typing import TYPE_CHECKING, Optional

from agent.core.model.context import ExecContext
from agent.core.model.types import ContentItem, Message, ToolCall, ToolResult

if TYPE_CHECKING:
    from agent.core.llm_client import Client
    from agent.core.model.llm_message import Request, Response


def create_opimizer_cb(apply_opt, threashold: int = 50000):
    
    async def cb(ctx: ExecContext, req: "Request") -> Optional["Response"]:

        token_cnt = count_tokens(req)
        if token_cnt < threashold:
            return None
        
        result = apply_opt(ctx, req)
        if inspect.isawaitable(result):
            await result
        return None
    
    return cb


def count_tokens(req: "Request") -> int:
    import tiktoken
    from agent.core.llm_client import MessageHelper

    try:
        encoding = tiktoken.encoding_for_model(req.model_id or "gpt-5")
    except KeyError:
        encoding = tiktoken.get_encoding("o200k_base")
    
    total_tokens = 0

    for msg in MessageHelper.build_msgs(req):
        total_tokens += 4  # per-message overhead

        content = msg.get("content")
        if content:
            total_tokens += len(encoding.encode(str(content)))
        
        tool_calls = msg.get("tool_calls")
        if not tool_calls:
            continue

        for tool_call in tool_calls:
            func = tool_call.get("function", {})

            name = func.get("name")
            if name:
                total_tokens += len(encoding.encode(name))

            arguments = func.get("arguments")
            if arguments:
                total_tokens += len(encoding.encode(arguments))
        
    if not req.tools:
        return total_tokens

    for tool in req.tools:
        tool_def = tool.tool_def
        if not tool_def:
            continue

        tool_json = json.dumps(tool_def, ensure_ascii=False)
        total_tokens += len(encoding.encode(tool_json))
    
    return total_tokens


def apply_sliding_window(ctx: ExecContext, req: "Request", size: int = 20) -> None:
    contents = req.contents

    msg_idx = None
    for i, item in enumerate(contents):
        if isinstance(item, Message):
            msg_idx = i
            break
    
    if msg_idx is None:
        return
    
    # first n
    head = contents[: msg_idx + 1]

    # last n
    tail = contents[msg_idx + 1:]
    if len(tail) > size:
        tail = tail[-size:]
    
    req.contents = head + tail


def apply_compaction(_ctx: ExecContext, req: "Request") -> None:
    tool_call_args: dict[str, dict] = {}
    compacted: list[ContentItem] = []

    for item in req.contents:
        if isinstance(item, ToolCall):
            tool_call_args[item.tool_call_id] = item.args
            tool_call = _compact_tool_call(item)
            compacted.append(tool_call)
            continue

        if isinstance(item, ToolResult):
            tool_result = _compact_tool_result(item, tool_call_args)
            compacted.append(tool_result)
            continue

        compacted.append(item)

    req.contents = compacted


def _compact_tool_call(item: ToolCall) -> ToolCall:

    RULES = {
        "create_file": "[Content saved to file]"
    }

    if item.name not in RULES:
        return item

    compacted_args = {
        key: RULES[item.name] if key == "content" else value
        for key, value in item.args.items()
    }

    return ToolCall(
        tool_call_id=item.tool_call_id,
        name=item.name,
        args=compacted_args,
    )


def _compact_tool_result(item: ToolResult, tool_call_args: dict[str, dict]) -> ToolResult:
        
    RULES = {
        "read_file": "File content from {file_path}. Re-read if needed",
        "search_web": "Search results processed. Query: {query}. Re-search if needed.",
    }

    if item.name not in RULES:
        return item

    args = tool_call_args.get(item.tool_call_id, {})
    template = RULES[item.name]

    content = template.format(
        file_path=args.get("file_path", args.get("path", "unknown")),
        query=args.get("query", "unknown"),
    )

    return ToolResult(
        tool_call_id=item.tool_call_id,
        name=item.name,
        status=item.status,
        content=[content],
    )


async def apply_summary(ctx: ExecContext, req: "Request", client: "Client", keep_recent: int = 5) -> None:

    contents = req.contents

    user_idx = None
    for i, item in enumerate(contents):
        if isinstance(item, Message) and item.role == "user":
            user_idx = i
            break
    
    if user_idx is None:
        return
    
    last_idx = ctx.state.get("last_summary_idx", user_idx)

    st = last_idx + 1
    ed = len(contents) - keep_recent

    if ed <= st:
        return
    
    contents2 = contents[st:ed]
    head = contents[: last_idx + 1]
    tail = contents[ed:] 

    history_text = format_history(contents2)
    summary = await generate_summary(client, history_text)

    req.append_prompt(f"[Prev work summary]\n{summary}")
    req.contents = head + tail
    ctx.state["last_summary_idx"] = len(head) -1


def format_history(items: list[ContentItem]) -> str:

    lines = []
    for item in items:
        if isinstance(item, Message):
            lines.append(f"[{item.role}]: {item.content[:500]}...")
        elif isinstance(item, ToolCall):
            lines.append(f"[Tool Call]: {item.name}({item.args})")
        elif isinstance(item, ToolResult):
            preview = str(item.content[0])[:200] if item.content else ""
            lines.append(f"[Tool Result]: {item.name} -> {preview}...")
    return "\n".join(lines)


async def generate_summary(client: "Client", history: str) -> str:
    from agent.core.model.llm_message import Request

    PROMPT = """You are summarizing an AI agent's work progress.

Given the following execution history, extract:
1. Key findings: Important information discovered
2. Tools used: List of tools that were called
3. Current status: What has been accomplished and what remains

Be concise. Focus on information that will help the agent continue its work.

Execution History:
{history}

Provide a structured summary."""

    prompt = PROMPT.format(history=history)
    content: list[ContentItem] = [Message(role="user", content="Please summarize.")]

    req = Request(system_prompt=[prompt], contents=content)
    res = await client.call_llm(req)

    for item in res.content:
        if isinstance(item, Message):
            return item.content
        
    return ""


class ContextOptimizer:

    def __init__(
            self, 
            client: "Client",
            token_threshold: int = 50000,
            enable_compaction: bool = True,
            enable_summarization: bool = True,
            keep_recent: int = 5
    ):
        self.client = client
        self.token_threshold = token_threshold
        self.enable_compaction = enable_compaction
        self.enable_summarization = enable_summarization
        self.keep_recent = keep_recent

    async def __call__(self, ctx: ExecContext, req: "Request") -> Optional["Response"]:

        if count_tokens(req) < self.token_threshold:
            return None
        
        if self.enable_compaction:
            apply_compaction(ctx, req)
            if count_tokens(req) < self.token_threshold:
                return None
            
        if self.enable_summarization:
            await apply_summary(ctx, req, self.client, self.keep_recent)
        
        return None

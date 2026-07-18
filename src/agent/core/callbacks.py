
from agent.core.rag import fixed_length_chunking, get_embd, vector_search
from agent.core.model.context import ExecContext
from agent.core.model.types import ToolCall, ToolResult
from agent.core.helpers.const import STR_SUCCESS

DANGEROUSE_TOOLS = ["delete_file", "send_email", "execute_sql"]

def approval_cb(ctx: ExecContext, tool_call: ToolCall):

    if tool_call.name not in DANGEROUSE_TOOLS:
        return None
    
    print(f"\n⚠️ Dangerous tool execution requested")
    print(f"Tool: {tool_call.name}")
    print(f"Arguments: {tool_call.args}")

    res = input("Do you want to execute? (y/N): ").lower().strip()

    if res == 'y':
        print("✅ Approved. Executing...\n")
        return None
    else:
        print("❌ Denied. Skipping execution.\n")
        return f"User denied execution of {tool_call.name}"


def search_compress(ctx: ExecContext, tool_result: ToolResult):
    if tool_result.name != "search_web":
        return None

    org_content = tool_result.content
    if not isinstance(org_content, str) or len(org_content) < 2000:
        return None

    query = _extract_search_query(ctx, tool_result.tool_call_id)
    if not query:
        return None
    
    chunks = fixed_length_chunking(org_content, chunk_size=500, overlap=50)
    embd = get_embd(chunks)
    results = vector_search(query, chunks, embd, top_k=3)

    compress = "\n\n".join([r['chunk'] for r in results])

    return ToolResult(
        tool_call_id=tool_result.tool_call_id,
        name=tool_result.name,
        status=STR_SUCCESS,
        content=compress,
    )

def _extract_search_query(ctx: ExecContext, tool_call_id: str) -> str:
    for event in ctx.events:
        for item in event.content:
            if isinstance(item, ToolCall) and \
               item.name == "search_web" and \
               item.tool_call_id == tool_call_id:
                return item.args.get("query", "")
    return ""


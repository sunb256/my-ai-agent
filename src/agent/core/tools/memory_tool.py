from typing import TYPE_CHECKING, Any

from agent.core.model.context import ExecContext
from agent.core.model.tool_base import BaseTool
from agent.core.model.types import Message

if TYPE_CHECKING:
    from agent.core.model.llm_message import Request
    from agent.core.memory.long_term import TaskMemory


class MemoryTool(BaseTool):
    
    def __init__(self):
        super().__init__(
            name="recall_memory",
            desc="Search for past problem-solving records. Use this to check if similar problems were solved before.",
            tool_def=None,
        )
    

    async def exec(self, ctx: ExecContext, **kwargs: Any) -> str:

        query = str(kwargs.get("query", ""))
        if ctx.memory_manager is None or not query:
            return ""
        
        memories = await ctx.memory_manager.search(query, top_k=3)
        if not memories:
            return ""
        
        return self._format_memories(memories)

    def _format_memories(self, memories: list["TaskMemory"]) -> str:

        results = []

        for i, mem in enumerate(memories, 1):
            status = "Correct" if mem.is_correct else "Incorrect"
            text = (
                f"[Record {i}]\n"
                f"- Problem: {mem.task_summary}\n"
                f"- Approach: {mem.approach}\n"
                f"- ANswer: {mem.final_answer}\n"
                f"- Result: {status}\n"
            )
            
            if not mem.is_correct and mem.error_analysis:
                text += f"\n- Errror analysis: {mem.error_analysis}"
            results.append(text)

        return "\n\n".join(results)
    
    async def process_llm_request(self, ctx: "ExecContext", req: "Request") -> None:

        if ctx.memory_manager is None:
            return None
        
        user_msgs = [c for c in req.contents if isinstance(c, Message) and c.role == "user"]

        if not user_msgs:
            return None
        
        result = await self.exec(ctx, query=user_msgs[-1].content)
        if not result:
            return None

        req.append_prompt(
            "The following are records from similar problems solved in the past:\n"
            "<PAST_EXPERIENCES>\n"
            f"{result}\n"
            "</PAST_EXPERIENCES>\n"
            "Reference successful approaches and avoid approaches that led to failures."
        )
        return None


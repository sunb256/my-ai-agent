from typing import Any, cast
import uuid

import chromadb
from chromadb.utils.embedding_functions import OpenAIEmbeddingFunction
from pydantic import BaseModel, Field

from agent.context import ExecContext
from agent.types import Message, ToolCall, ToolResult, Event


class TaskMemory(BaseModel):

    task_summary: str = Field(description="What the problem asked")
    approach: str = Field(description="Methods and tools used to solve it")
    final_answer: str = Field(description="The agent's submitted answer")
    is_correct: bool = Field(description="Whether the answer was correct")
    error_analysis: str | None = Field(default=None, description="Why the attempt failed, if it did")

    def to_embedding_text(self) -> str:
        return f"Task: {self.task_summary}"
    

class DuplicateCheckResult(BaseModel):
    decision: str = Field(description="ADD (new information) or SKIP (duplication)")
    reason: str = Field(description="Explanation for the decision")



TASK_MEMORY_EXTRACTION_PROMPT = """Analyze the following execution history and extract a structured task memory.

Execution History:
{execution_history}

Extract:
- task_summary: What the problem asked
- approach: Methods and tools used to solve it
- final_answer: The agent's submitted answer
- is_correct: Whether the answer was correct (true or false)
- error_analysis: If incorrect, explain why; otherwise leave null
"""


DUPLICATE_CHECK_PROMPT = """Compare the new memory against existing memories to determine if it's a duplicate.

Existing memories:
{existing_memories}

New memory:
{new_memory}

Respond with one of:
- ADD: This is new information that should be stored
- SKIP: Similar information already exists, no need to store

Judgment criteria:
- Same problem with different approach or different result counts as new information
- Same problem with same approach and same result is a duplicate
"""


class TaskMemoryManager:

    def __init__(self, client, collection_name: str = "task_memories"):
        self.client = client
        self.chroma = chromadb.Client()

        embd_fn = OpenAIEmbeddingFunction(model_name="text-embedding-3-small")
        self.collection = self.chroma.get_or_create_collection(name=collection_name, embedding_function=cast(Any, embd_fn))

    async def _extract_memory(self, execution_history: str) -> TaskMemory | None:
        prompt = TASK_MEMORY_EXTRACTION_PROMPT.format(execution_history=execution_history)

        try:
            result = await self.client.ask(prompt=prompt, res_format=TaskMemory)
            if isinstance(result, TaskMemory):
                return result
            return None
        except Exception as error:
            print("Memory extraction failed: %s", error)
            return None
    
    def _format_execution_history(self, events: list[Event]) -> str:
        lines = []
        for event in events:
            for item in event.content:
                if isinstance(item, Message):
                    lines.append(f"[{item.role}]: {item.content}")
                elif isinstance(item, ToolCall):
                    lines.append(f"[Tool Call]: {item.name}({item.args})")
                elif isinstance(item, ToolResult):
                    preview = str(item.content[0])[:500] if item.content else ""
                    lines.append(f"[Tool Result]: {item.name} -> {preview}")
        return "\n".join(lines)
    
    async def _is_duplicate(self, new: TaskMemory, exists: Any) -> bool:

        metadatas = exists.get("metadatas") or []
        if not metadatas or not metadatas[0]:
            return False
        
        exists_text = []
        for meta in exists["metadatas"][0]:
            exists_text.append(
                f"task_summary: {meta.get('task_summary')}, "
                f"approach: {meta.get('approach')}, "
                f"is_correct: {meta.get('is_correct')}"
            )
        
        prompt = DUPLICATE_CHECK_PROMPT.format(
            existing_memories="\n".join(exists_text),
            new_memory=(
                f"task_summary: {new.task_summary}, "
                f"approach: {new.approach}, "
                f"is_correct: {new.is_correct}"
            ),
        )

        try:
            result = await self.client.ask(prompt=prompt, res_format=DuplicateCheckResult)

            if not isinstance(result, DuplicateCheckResult):
                return False
            
            return result.decision == "SKIP"

        except Exception:
            return False


    async def save(self, ctx: ExecContext) -> str | None:

        histories = self._format_execution_history(ctx.events)

        memory = await self._extract_memory(histories)
        if memory is None:
            return None
        
        exist = self.collection.query(
            query_texts=[memory.to_embedding_text()],
            n_results=3
        )

        if await self._is_duplicate(memory, exist):
            return None
        
        memory_id = str(uuid.uuid4())
        metadata = memory.model_dump()

        metadata = {k: ("" if v is None else v) for k,v in metadata.items()}
        self.collection.add(
            ids=[memory_id],
            documents=[memory.to_embedding_text()],
            metadatas=[metadata]
        )
        return memory_id
    

    async def search(self, query: str, top_k: int = 5) -> list[TaskMemory]:

        results = self.collection.query(query_texts=[query], n_results=top_k)
        metadatas = results.get("metadatas") or []
        if not metadatas or not metadatas[0]:
            return []

        return [TaskMemory.model_validate(meta) for meta in metadatas[0]]


from collections.abc import Sequence
from typing import Any

import numpy as np
from openai import OpenAI

DEFAULT_EMBD_MODEL = "text-embedding-3-small"

def get_embeddings(texts: str | Sequence[str], model: str=DEFAULT_EMBD_MODEL) -> np.ndarray:
    client = OpenAI()
    input_texts = [texts] if isinstance(texts, str) else list(texts)

    response = client.embeddings.create(input=input_texts, model=model)
    return np.array([item.embedding for item in response.data], dtype=float)

def get_embd(texts: str | Sequence[str], model: str = DEFAULT_EMBD_MODEL) -> np.ndarray:
    return get_embeddings(texts, model=model)


def fixed_length_chunking( text: str, chunk_size: int = 500, overlap: int = 50) -> list[str]:
      
      if chunk_size <= 0:
          raise ValueError("chunk_size must be positive")
      if overlap < 0:
          raise ValueError("overlap must be non-negative")
      if overlap >= chunk_size:
          raise ValueError("overlap must be smaller than chunk_size")

      chunks: list[str] = []
      start = 0

      while start < len(text):
          end = start + chunk_size
          chunk = text[start:end].strip()

          if chunk:
              chunks.append(chunk)

          start = end - overlap if end < len(text) else end

      return chunks


def vector_search(query: str, chunks: Sequence[str], chunk_embeddings: np.ndarray, top_k: int = 3) -> list[dict[str, Any]]:

    if top_k <= 0 or not chunks:
        return []

    embeddings = np.asarray(chunk_embeddings, dtype=float)
    if embeddings.ndim != 2:
        raise ValueError("chunk_embeddings must be a 2D array")

    if len(chunks) != embeddings.shape[0]:
        raise ValueError("chunks and chunk_embeddings must have the same length")

    query_embeddings = get_embeddings(query)
    score = _cosine_similarity(query_embeddings, embeddings)[0]

    idxs = score.argsort()[::-1][:top_k]

    return [
        {
            "chunk": chunks[int(idx)],
            "similarity": float(score[int(idx)]),
        }
        for idx in idxs
    ]

def _cosine_similarity(query_embeddings: np.ndarray, embeddings: np.ndarray) -> np.ndarray:

    query = np.linalg.norm(query_embeddings, axis=1, keepdims=True)
    norm = np.linalg.norm(embeddings, axis=1, keepdims=True).T

    denominator = query * norm
    denominator = np.where(denominator == 0, 1.0, denominator)

    return (query_embeddings @ embeddings.T) / denominator


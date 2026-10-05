"""
Workflow 09 — RAG Retrieval Adapter

Loads the existing intervention RAG artifacts.
Does not rebuild embeddings or modify the FAISS index.

Returns evidence with source metadata and applicability caveats.
"""

import json
from pathlib import Path
from typing import Optional

import faiss
import numpy as np
from sentence_transformers import SentenceTransformer


DEFAULT_RAG_DIR = Path(
    "/content/CoolPlan_Intervention_RAG_Runtime/"
    "CoolPlan_Intervention_RAG_Final"
)

DEFAULT_MODEL_NAME = "sentence-transformers/all-MiniLM-L6-v2"


class Workflow09RAGRetriever:
    """Semantic retrieval over the existing Workflow 09 RAG index."""

    def __init__(
        self,
        rag_dir=DEFAULT_RAG_DIR,
        model_name=DEFAULT_MODEL_NAME,
        model=None,
    ):
        self.rag_dir = Path(rag_dir)

        self.index_path = self.rag_dir / "intervention.faiss"
        self.chunks_path = self.rag_dir / "chunks.jsonl"
        self.id_map_path = self.rag_dir / "chunk_id_map.json"
        self.manifest_path = self.rag_dir / "manifest.json"

        for path in (
            self.index_path,
            self.chunks_path,
            self.id_map_path,
        ):
            if not path.is_file():
                raise FileNotFoundError(
                    f"Required RAG artifact not found: {path}"
                )

        # Load the existing index and metadata.
        self.index = faiss.read_index(str(self.index_path))

        with self.chunks_path.open("r", encoding="utf-8") as f:
            self.chunks = [
                json.loads(line)
                for line in f
                if line.strip()
            ]

        with self.id_map_path.open("r", encoding="utf-8") as f:
            self.chunk_id_map = json.load(f)

        if not isinstance(self.chunk_id_map, list):
            raise ValueError(
                "Expected chunk_id_map.json to contain a list."
            )

        if self.index.d != 384:
            raise ValueError(
                f"Expected 384-dimensional index; found {self.index.d}."
            )

        if self.index.ntotal != len(self.chunks):
            raise ValueError(
                "FAISS vector count does not match chunk count."
            )

        if len(self.chunk_id_map) != len(self.chunks):
            raise ValueError(
                "Chunk ID map length does not match chunk count."
            )

        self.chunk_lookup = {
            chunk["chunk_id"]: chunk
            for chunk in self.chunks
        }

        # Lazy model loading keeps initialization lighter.
        self._model = model

        self.manifest = {}
        if self.manifest_path.is_file():
            with self.manifest_path.open(
                "r", encoding="utf-8"
            ) as f:
                self.manifest = json.load(f)

    @property
    def model(self):
        if self._model is None:
            self._model = SentenceTransformer(
                DEFAULT_MODEL_NAME
            )
        return self._model

    def retrieve(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
        min_similarity: Optional[float] = None,
    ):
        """
        Retrieve relevant evidence.

        Args:
            query: Natural-language search query.
            top_k: Maximum number of results to return.
            category: Optional exact intervention_category filter.
            min_similarity: Optional minimum cosine similarity.
                Similarity is a retrieval signal, not a truth score.

        Returns:
            A list of evidence dictionaries with source metadata.
        """
        if not isinstance(query, str) or not query.strip():
            raise ValueError("query must be a non-empty string")

        if not isinstance(top_k, int) or top_k < 1:
            raise ValueError("top_k must be a positive integer")

        if min_similarity is not None and not (
            -1.0 <= min_similarity <= 1.0
        ):
            raise ValueError(
                "min_similarity must be between -1 and 1"
            )

        query_vector = self.model.encode(
            [query.strip()],
            normalize_embeddings=True,
            convert_to_numpy=True,
        ).astype("float32")

        if query_vector.shape != (1, self.index.d):
            raise ValueError(
                "Query embedding dimension does not match FAISS index."
            )

        # Search broadly when filtering by category so relevant
        # category-specific results are less likely to be missed.
        search_k = min(
            self.index.ntotal,
            max(top_k, top_k * 5 if category else top_k),
        )

        scores, indices = self.index.search(
            query_vector,
            search_k,
        )

        results = []

        for score, row_index in zip(scores[0], indices[0]):
            if row_index < 0:
                continue

            chunk_id = self.chunk_id_map[int(row_index)]
            chunk = self.chunk_lookup.get(chunk_id)

            if chunk is None:
                raise ValueError(
                    f"Missing chunk metadata for ID: {chunk_id}"
                )

            if category and (
                chunk.get("intervention_category", "").strip().casefold()
                != category.strip().casefold()
            ):
                continue

            similarity = float(score)

            if (
                min_similarity is not None
                and similarity < min_similarity
            ):
                continue

            results.append({
                "similarity": round(similarity, 4),
                "chunk_id": chunk.get("chunk_id"),
                "source_id": chunk.get("source_id"),
                "source_title": chunk.get("source_title"),
                "source_filename": chunk.get("source_filename"),
                "publisher": chunk.get("publisher"),
                "publication_year": chunk.get("publication_year"),
                "page_number": chunk.get("page_number"),
                "section_heading": chunk.get("section_heading"),
                "intervention_category": chunk.get(
                    "intervention_category"
                ),
                "source_url": chunk.get("source_url"),
                "source_sha256": chunk.get("source_sha256"),
                "evidence_geography": chunk.get(
                    "evidence_geography"
                ),
                "local_applicability": chunk.get(
                    "local_applicability"
                ),
                "extraction_method": chunk.get(
                    "extraction_method"
                ),
                "chunk_text": chunk.get("chunk_text", ""),
            })

            if len(results) >= top_k:
                break

        return results

    def retrieve_context(
        self,
        query: str,
        top_k: int = 5,
        category: Optional[str] = None,
    ):
        """
        Return evidence in a compact, traceable format for an LLM.

        This formats retrieved evidence only. It does not call an LLM.
        """
        results = self.retrieve(
            query=query,
            top_k=top_k,
            category=category,
        )

        if not results:
            return "No matching RAG evidence was retrieved.", []

        blocks = []
        for i, item in enumerate(results, start=1):
            blocks.append(
                f"[Evidence {i}]\n"
                f"Source: {item['source_title']}\n"
                f"Publisher: {item['publisher']}\n"
                f"Year: {item['publication_year']}\n"
                f"Page: {item['page_number']}\n"
                f"Section: {item['section_heading']}\n"
                f"Category: {item['intervention_category']}\n"
                f"Similarity: {item['similarity']}\n"
                f"Geography: {item['evidence_geography']}\n"
                f"Local applicability: {item['local_applicability']}\n"
                f"Chunk ID: {item['chunk_id']}\n"
                f"Evidence text:\n{item['chunk_text']}"
            )

        context = (
            "Use only the following retrieved material as source evidence. "
            "Do not treat similarity as proof. Preserve the source's "
            "geographic limitations. Do not claim that U.S.-based evidence "
            "has been validated for Pakistan.\n\n"
            + "\n\n".join(blocks)
        )

        return context, results

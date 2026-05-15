"""
Vector Store Service
====================
ChromaDB-backed vector store with BGE-M3 embeddings for
immigration document retrieval.

BGE-M3 supports:
- Dense retrieval (semantic similarity)
- Sparse retrieval (keyword matching — critical for legal terms like "I-485")
- Multilingual (EN/TR/ES/ZH — matches our translation pipeline)

We use the dense embeddings with ChromaDB for now, with metadata filtering
for case_type, client_name, and document_type.
"""

import chromadb
from chromadb.config import Settings
from sentence_transformers import SentenceTransformer
from typing import Optional
import logging
import os

from app.utils.pdf_parser import DocumentChunk

logger = logging.getLogger(__name__)

# BGE-M3 is 568M params — great quality but needs ~2 GB RAM.
# On memory-constrained hosts (e.g. Fly.io free/small VMs) set:
#   EMBEDDING_MODEL=sentence-transformers/all-MiniLM-L6-v2
# MiniLM uses ~150 MB RAM and is more than good enough for demos.
DEFAULT_EMBEDDING_MODEL = os.getenv("EMBEDDING_MODEL", "BAAI/bge-m3")
FALLBACK_EMBEDDING_MODEL = "sentence-transformers/all-MiniLM-L6-v2"

COLLECTION_NAME = "immigration_documents"


class VectorStoreService:
    """
    Manages document embeddings and retrieval using ChromaDB + BGE-M3.
    """

    def __init__(
        self,
        persist_directory: str = "./data/chromadb",
        embedding_model: Optional[str] = None,
    ):
        self.persist_directory = persist_directory
        self.model_name = embedding_model or DEFAULT_EMBEDDING_MODEL
        self.embedding_model: Optional[SentenceTransformer] = None
        self.client: Optional[chromadb.ClientAPI] = None
        self.collection = None

    async def initialize(self):
        """Load embedding model and connect to ChromaDB."""
        # Load embedding model
        try:
            logger.info(f"Loading embedding model: {self.model_name}")
            self.embedding_model = SentenceTransformer(self.model_name)
            logger.info(f"✅ Loaded {self.model_name}")
        except Exception as e:
            logger.warning(
                f"Failed to load {self.model_name}: {e}. "
                f"Falling back to {FALLBACK_EMBEDDING_MODEL}"
            )
            self.model_name = FALLBACK_EMBEDDING_MODEL
            self.embedding_model = SentenceTransformer(self.model_name)

        # Initialize ChromaDB
        os.makedirs(self.persist_directory, exist_ok=True)
        self.client = chromadb.PersistentClient(path=self.persist_directory)
        self.collection = self.client.get_or_create_collection(
            name=COLLECTION_NAME,
            metadata={"hnsw:space": "cosine"},
        )

        doc_count = self.collection.count()
        logger.info(
            f"✅ ChromaDB initialized at {self.persist_directory} "
            f"({doc_count} documents in collection)"
        )

    def add_chunks(
        self,
        chunks: list[DocumentChunk],
        client_name: Optional[str] = None,
        case_type: Optional[str] = None,
        document_type: Optional[str] = None,
    ) -> int:
        """
        Embed and store document chunks with metadata.
        
        Returns:
            Number of chunks added.
        """
        if not chunks:
            return 0

        texts = [chunk.text for chunk in chunks]
        embeddings = self.embedding_model.encode(
            texts, show_progress_bar=False, normalize_embeddings=True
        ).tolist()

        # Scope ids by client so two clients uploading the same filename
        # don't overwrite each other via upsert. Falls back to "_global" when
        # no client is provided (e.g. anonymous demo uploads).
        client_key = (client_name or "_global").strip().lower().replace(" ", "_")
        ids = [
            f"{client_key}::{chunk.source_filename}::{chunk.chunk_index}"
            for chunk in chunks
        ]

        metadatas = []
        for chunk in chunks:
            meta = {
                "source_filename": chunk.source_filename,
                "page_number": chunk.page_number,
                "chunk_index": chunk.chunk_index,
                "char_start": chunk.char_start,
                "char_end": chunk.char_end,
            }
            if client_name:
                meta["client_name"] = client_name
            if case_type:
                meta["case_type"] = case_type
            if document_type:
                meta["document_type"] = document_type
            metadatas.append(meta)

        self.collection.upsert(
            ids=ids,
            embeddings=embeddings,
            documents=texts,
            metadatas=metadatas,
        )

        logger.info(
            f"Added {len(chunks)} chunks from {chunks[0].source_filename}"
        )
        return len(chunks)

    def query(
        self,
        question: str,
        top_k: int = 5,
        client_name: Optional[str] = None,
        case_type: Optional[str] = None,
    ) -> list[dict]:
        """
        Retrieve relevant chunks for a question with optional metadata filtering.
        
        Returns:
            List of dicts with 'text', 'score', and 'metadata' keys.
        """
        # Encode query
        query_embedding = self.embedding_model.encode(
            [question], normalize_embeddings=True
        ).tolist()

        # Build metadata filter
        where_filter = None
        conditions = []
        if client_name:
            conditions.append({"client_name": {"$eq": client_name}})
        if case_type:
            conditions.append({"case_type": {"$eq": case_type}})

        if len(conditions) == 1:
            where_filter = conditions[0]
        elif len(conditions) > 1:
            where_filter = {"$and": conditions}

        # Query ChromaDB
        results = self.collection.query(
            query_embeddings=query_embedding,
            n_results=top_k,
            where=where_filter,
            include=["documents", "metadatas", "distances"],
        )

        # Format results
        formatted = []
        if results and results["documents"]:
            for i, doc in enumerate(results["documents"][0]):
                # ChromaDB returns cosine distance; convert to similarity
                distance = results["distances"][0][i]
                similarity = 1 - distance

                formatted.append(
                    {
                        "text": doc,
                        "score": round(similarity, 4),
                        "metadata": results["metadatas"][0][i],
                    }
                )

        return formatted

    def get_collection_stats(self) -> dict:
        """Get statistics about the document collection."""
        count = self.collection.count()
        return {
            "total_chunks": count,
            "embedding_model": self.model_name,
            "collection_name": COLLECTION_NAME,
        }

    def delete_document(self, filename: str, client_name: Optional[str] = None) -> int:
        """
        Delete all chunks for a specific document.
        If client_name is provided, only deletes chunks belonging to that client.
        """
        where: dict = {"source_filename": {"$eq": filename}}
        if client_name:
            where = {"$and": [where, {"client_name": {"$eq": client_name}}]}

        results = self.collection.get(where=where, include=[])
        if results and results["ids"]:
            self.collection.delete(ids=results["ids"])
            logger.info(f"Deleted {len(results['ids'])} chunks for {filename} (client={client_name})")
            return len(results["ids"])
        return 0

    def list_documents_by_client(self, client_name: str) -> list[str]:
        """Return unique filenames stored under a specific client."""
        results = self.collection.get(
            where={"client_name": {"$eq": client_name}},
            include=["metadatas"],
        )
        if not results or not results["metadatas"]:
            return []
        filenames = sorted(set(
            m["source_filename"]
            for m in results["metadatas"]
            if "source_filename" in m
        ))
        return filenames

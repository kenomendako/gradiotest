# lib/langchain_cognee/vectorstores.py
# This file has been patched by Jules to work with the modern `cognee` package API.
# The original code was incompatible with cognee v0.2.4 due to structural changes
# in the cognee library and undeclared dependencies in the langchain-cognee package.
from __future__ import annotations

import asyncio
from typing import (
    Any,
    Iterable,
    List,
    Optional,
)

from langchain_core.documents import Document
from langchain_core.embeddings import Embeddings
from langchain_core.vectorstores import VectorStore

from cognee import add, search

class CogneeVectorStore(VectorStore):
    """
    Wrapper around Cognee vector store.
    """

    def __init__(
        self,
        *,
        cognee_client: Optional[Any] = None,
    ):
        """
        Initialize with Cognee client.
        """
        # The original code instantiated a `Cognee()` client, which no longer exists.
        # This has been patched to work with the functional API of the modern cognee package.
        pass


    def add_texts(
        self,
        texts: Iterable[str],
        metadatas: Optional[List[dict]] = None,
        **kwargs: Any,
    ) -> List[str]:
        """Run more texts through the embeddings and add to the vectorstore.

        Args:
            texts: Iterable of strings to add to the vectorstore.
            metadatas: Optional list of metadatas associated with the texts.
            kwargs: vectorstore specific parameters

        Returns:
            List of ids from adding the texts into the vectorstore.
        """
        if metadatas is None:
            metadatas = [{} for _ in texts]

        documents = [
            Document(page_content=text, metadata=metadata)
            for text, metadata in zip(texts, metadatas)
        ]

        return self.add_documents(documents)

    def add_documents(self, documents: List[Document], **kwargs: Any) -> List[str]:
        return asyncio.run(self.aadd_documents(documents, **kwargs))

    async def aadd_documents(
        self, documents: List[Document], **kwargs: Any
    ) -> List[str]:
        """Run more documents through the embeddings and add to the vectorstore.

        Args:
            documents: Documents to add to the vectorstore.
            kwargs: vectorstore specific parameters

        Returns:
            List of ids from adding the texts into the vectorstore.
        """
        # Patched to call the imported `add` function directly.
        await add(documents, **kwargs)
        return [document.metadata.get("id", "") for document in documents]

    def similarity_search(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> List[Document]:
        """Return docs most similar to query."""
        return asyncio.run(self.asimilarity_search(query, k, **kwargs))

    async def asimilarity_search(
        self, query: str, k: int = 4, **kwargs: Any
    ) -> List[Document]:
        """Return docs most similar to query."""
        # Patched to call the imported `search` function directly.
        results = await search(query, k=k, **kwargs)
        return [result for result in results if isinstance(result, Document)]

    @classmethod
    def from_texts(
        cls,
        texts: List[str],
        embedding: Optional[Embeddings] = None,
        metadatas: Optional[List[dict]] = None,
        **kwargs: Any,
    ) -> CogneeVectorStore:
        """
        Return VectorStore initialized from texts and embeddings.
        """
        cognee_vectorstore = cls(**kwargs)
        cognee_vectorstore.add_texts(texts=texts, metadatas=metadatas)
        return cognee_vectorstore

    def _select_relevance_score_fn(self) -> float:
        raise NotImplementedError

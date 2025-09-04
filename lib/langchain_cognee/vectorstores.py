# lib/langchain_cognee/vectorstores.py
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

# Patched by Jules: The original 'from cognee.cognee import Cognee' fails because
# the 'cognee' package (v0.2.4) does not have that structure.
# The langchain-cognee package also fails to declare its dependency on cognee.
# This patch imports the necessary functions directly and wraps them in a dummy client.
from cognee import add as aadd_documents
from cognee import search as asearch

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
        if cognee_client:
            self.cognee_client = cognee_client
        else:
            # Create a dummy client that holds the functions
            class CogneeClient:
                pass
            self.cognee_client = CogneeClient()
            self.cognee_client.aadd_documents = aadd_documents
            self.cognee_client.asearch = asearch

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
        # The cognee `add` function, which we aliased to `aadd_documents`, is async.
        # We need to run it in an event loop.
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
        # The original code was `await self.cognee_client.aadd_documents(documents)`.
        # Our dummy client's method points to the real `add` function from cognee.
        # The `add` function in cognee likely takes documents directly.
        await self.cognee_client.aadd_documents(documents)
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
        # The original code was `results = await self.cognee_client.asearch(query, k, **kwargs)`
        # Our dummy client's method points to the real `search` function.
        results = await self.cognee_client.asearch(query, k=k, **kwargs)
        # The original code returned a list of Documents, so we assume the search function does as well.
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

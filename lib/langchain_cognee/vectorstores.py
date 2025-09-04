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

from cognee.cognee import Cognee

class CogneeVectorStore(VectorStore):
    """
    Wrapper around Cognee vector store.
    """

    def __init__(
        self,
        *,
        cognee_client: Optional[Cognee] = None,
    ):
        """
        Initialize with Cognee client.
        """
        try:
            from cognee.cognee import Cognee
        except ImportError as e:
            raise ImportError(
                "Could not import cognee python package. "
                "Please install it with `pip install cognee-python`."
            ) from e

        self.cognee_client = cognee_client or Cognee()

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
        results = await self.cognee_client.asearch(query, k, **kwargs)
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

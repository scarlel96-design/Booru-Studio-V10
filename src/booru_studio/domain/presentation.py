from __future__ import annotations

from dataclasses import dataclass
from enum import StrEnum


class PresentationMode(StrEnum):
    """How one logical source is represented in the product UI.

    Presentation is a domain semantic, not a QML heuristic.  Resolvers decide whether a source is
    one standalone item or a collection and the UI only renders that authoritative decision.
    """

    INDIVIDUAL = "INDIVIDUAL"
    BATCH = "BATCH"


class CollectionSemantics(StrEnum):
    NONE = "NONE"
    PLAYLIST = "PLAYLIST"
    CHANNEL = "CHANNEL"
    MULTI_INPUT = "MULTI_INPUT"
    GALLERY = "GALLERY"
    WEB_PAGE = "WEB_PAGE"


@dataclass(frozen=True, slots=True)
class MediaPresentationContract:
    mode: PresentationMode
    collection: CollectionSemantics = CollectionSemantics.NONE

    def __post_init__(self) -> None:
        if self.mode is PresentationMode.INDIVIDUAL and self.collection is not CollectionSemantics.NONE:
            raise ValueError("individual presentation cannot carry collection semantics")
        if self.mode is PresentationMode.BATCH and self.collection is CollectionSemantics.NONE:
            raise ValueError("batch presentation requires explicit collection semantics")

    @classmethod
    def single_media(cls) -> "MediaPresentationContract":
        return cls(PresentationMode.INDIVIDUAL, CollectionSemantics.NONE)

    @classmethod
    def playlist(cls) -> "MediaPresentationContract":
        return cls(PresentationMode.BATCH, CollectionSemantics.PLAYLIST)

    @classmethod
    def channel(cls) -> "MediaPresentationContract":
        return cls(PresentationMode.BATCH, CollectionSemantics.CHANNEL)

    @classmethod
    def multi_input(cls) -> "MediaPresentationContract":
        return cls(PresentationMode.BATCH, CollectionSemantics.MULTI_INPUT)

    @classmethod
    def gallery(cls) -> "MediaPresentationContract":
        return cls(PresentationMode.BATCH, CollectionSemantics.GALLERY)

    @classmethod
    def web_page(cls) -> "MediaPresentationContract":
        return cls(PresentationMode.BATCH, CollectionSemantics.WEB_PAGE)

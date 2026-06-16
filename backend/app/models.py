"""Pydantic request/response schemas.

Timeline shapes use extra='allow' so later steps (effects) can add fields to
clips/tracks without breaking older saves.
"""
from __future__ import annotations

from typing import Any, Literal, Optional

from pydantic import BaseModel, ConfigDict, Field

TrackKind = Literal["audio", "video", "image", "effect"]


class ProjectCreate(BaseModel):
    name: str = Field(min_length=1, max_length=200)


class ProjectUpdate(BaseModel):
    name: Optional[str] = Field(default=None, min_length=1, max_length=200)


class Track(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    kind: TrackKind
    name: str


class Clip(BaseModel):
    model_config = ConfigDict(extra="allow")
    id: str
    trackId: str
    assetId: Optional[str] = None
    name: str = ""
    start: float = 0.0       # timeline position (seconds)
    duration: float = 0.0    # length on the timeline (seconds)
    inPoint: float = 0.0     # offset into the source media (seconds)
    color: Optional[str] = None


class TimelineDoc(BaseModel):
    model_config = ConfigDict(extra="allow")
    tracks: list[Track] = Field(default_factory=list)
    clips: list[Clip] = Field(default_factory=list)


class MediaUpdate(BaseModel):
    label: Optional[str] = None
    tags: Optional[list[str]] = None


class AnimateRequest(BaseModel):
    prompt: Optional[str] = None
    duration: int = 5


class FilterCreate(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class FilterFork(BaseModel):
    name: str = Field(min_length=1, max_length=80)


class FilterSave(BaseModel):
    code: str
    message: str = "Manual edit"


class FilterRollback(BaseModel):
    version: int


class FilterChatRequest(BaseModel):
    message: str


class FilterPreviewRequest(BaseModel):
    filter_id: str
    params: dict[str, Any] = Field(default_factory=dict)
    cursor_time: float = 0.0


class ChatMessage(BaseModel):
    role: str
    content: str


class ChatRequest(BaseModel):
    messages: list[ChatMessage] = Field(default_factory=list)
    cursor_time: float = 0.0


class SongStatus(BaseModel):
    status: str           # none|processing|done|error
    progress: float       # 0..1
    stage: Optional[str] = None
    error: Optional[str] = None


class Analysis(BaseModel):
    model_config = ConfigDict(extra="allow")
    duration: Optional[float] = None
    beats: Optional[dict[str, Any]] = None       # {bass, mid, high}
    waveform: Optional[dict[str, Any]] = None     # {peaks, pps}
    lyrics: Optional[list[dict[str, Any]]] = None  # [{start, end, text}]
    mood: Optional[dict[str, Any]] = None

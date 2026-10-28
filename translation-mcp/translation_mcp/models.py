from __future__ import annotations

from typing import Annotated, Literal

from pydantic import BaseModel, ConfigDict, Field, model_validator


class StrictModel(BaseModel):
    model_config = ConfigDict(extra="forbid", strict=True)


ShortText = Annotated[str, Field(max_length=4000)]


class Segment(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(min_length=1, max_length=8000)
    speaker: str = Field(default="", max_length=128)
    context: ShortText = ""
    protected_tokens: list[Annotated[str, Field(min_length=1, max_length=256)]] = Field(default_factory=list, max_length=32)

    @model_validator(mode="after")
    def check_protected(self):
        if any(token not in self.text for token in self.protected_tokens):
            raise ValueError("Every protected token must occur in its source segment")
        return self


class GlossaryTerm(StrictModel):
    source: str = Field(min_length=1, max_length=128)
    target: str = Field(min_length=1, max_length=128)
    note: str = Field(default="", max_length=512)
    required: bool = True


class Character(StrictModel):
    name: str = Field(min_length=1, max_length=128)
    description: ShortText = ""
    voice: ShortText = ""


class Translation(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    text: str = Field(max_length=16000)


class Batch(StrictModel):
    segments: list[Segment] = Field(min_length=1, max_length=64)
    source_language: Literal["ja", "en", "mixed"] = "mixed"
    target_language: Literal["zh-Hans"] = "zh-Hans"
    context: ShortText = ""
    style: ShortText = "Faithful, natural Simplified Chinese; retain characterization and tone."
    characters: list[Character] = Field(default_factory=list, max_length=24)
    glossary: list[GlossaryTerm] = Field(default_factory=list, max_length=128)
    preserve_line_breaks: bool = True
    glossary_version: str = Field(default="", max_length=128)

    @model_validator(mode="after")
    def check_ids_and_glossary(self):
        ids = [segment.id for segment in self.segments]
        if len(ids) != len(set(ids)):
            raise ValueError("Segment IDs must be unique")
        terms = {}
        for term in self.glossary:
            if term.source in terms and terms[term.source] != term.target:
                raise ValueError("Conflicting glossary targets")
            terms[term.source] = term.target
        return self


class TranslateRequest(Batch):
    request_id: str = Field(min_length=1, max_length=128, pattern=r"^[A-Za-z0-9_.:-]+$")
    model: str | None = Field(default=None, min_length=1, max_length=256)
    allow_fallback: bool = True


class ReviewRequest(TranslateRequest):
    translations: list[Translation] = Field(min_length=1, max_length=64)


class ValidationRequest(Batch):
    translations: list[Translation] = Field(min_length=1, max_length=64)


class ModelTranslations(StrictModel):
    translations: list[Translation] = Field(min_length=1, max_length=64)


class ReviewIssue(StrictModel):
    id: str = Field(min_length=1, max_length=128)
    severity: Literal["error", "warning", "suggestion"]
    category: Literal["meaning", "omission", "terminology", "voice", "fluency", "format"]
    explanation: str = Field(min_length=1, max_length=2000)
    suggested_translation: str | None = Field(default=None, max_length=16000)


class ModelReview(StrictModel):
    reviewed_ids: list[str] = Field(min_length=1, max_length=64)
    issues: list[ReviewIssue] = Field(default_factory=list, max_length=128)


class Policy(StrictModel):
    primary_model: str = "deepseek/deepseek-flash"
    fallback_model: str = "openrouter/~google/gemini-flash-latest"
    max_input_chars: int = Field(default=16000, ge=100, le=100000)
    max_output_tokens: int = Field(default=8192, ge=64, le=16384)
    request_timeout_seconds: int = Field(default=120, ge=5, le=300)
    concurrency: int = Field(default=2, ge=1, le=8)

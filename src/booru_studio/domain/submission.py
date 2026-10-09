from __future__ import annotations

from dataclasses import dataclass

from booru_studio.common.ids import SubmissionId
from booru_studio.domain.enums import InputKind


@dataclass(frozen=True, slots=True)
class Submission:
    submission_id: SubmissionId
    input_kind: InputKind
    redacted_input: str
    created_at_utc_ms: int

"""Token estimation service (Task 10.5).

Provides a tokenizer-independent fallback (chars/4) plus model-specific
estimators where known.  Estimation is deterministic and cheap; it is a budget
planning aid, never a hard guarantee.
"""

from __future__ import annotations

import math
import re

_WORD_SPLIT = re.compile(r"\s+")


class TokenEstimator:
    """Estimate token counts for text and model families."""

    def __init__(self) -> None:
        self._models: dict[str, float] = {
            # Rough tokens-per-char for common model families.
            "claude": 1 / 4.0,
            "gpt": 1 / 4.0,
            "llama": 1 / 4.5,
            "qwen": 1 / 4.5,
            "default": 1 / 4.0,
        }

    def estimate(self, text: str, model: str = "default") -> int:
        ratio = self._models.get(model.lower(), self._models["default"])
        chars = len(text)
        # BPE-style models see roughly one token per 4 chars for English;
        # we refine slightly with word boundaries for longer text.
        words = len(_WORD_SPLIT.split(text.strip())) if text.strip() else 0
        by_chars = chars * ratio
        by_words = words * 1.3
        return max(1, int(math.ceil(by_chars + by_words * 0.1)))

    def fits(self, text: str, budget: int, model: str = "default") -> bool:
        return self.estimate(text, model) <= budget


__all__ = ["TokenEstimator"]

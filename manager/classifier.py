"""
Phishing-oriented domain classification utilities for CertPatrol Orchestrator.

This module adapts the heuristics from phishing_catcher's catch_phishing.py
so discovered domains can be enriched with basic risk scoring metadata.
"""
from __future__ import annotations

import json
import math
import os
import re
import threading
from dataclasses import dataclass, field
from pathlib import Path
from typing import Dict, Optional, Tuple

import yaml
from tld import get_tld

try:  # Prefer the C extension for performance if available
    from Levenshtein import distance as levenshtein_distance  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    levenshtein_distance = None

try:  # Fallback to rapidfuzz if python-Levenshtein is not installed
    from rapidfuzz.distance import Levenshtein as rf_levenshtein  # type: ignore
except Exception:  # pragma: no cover - optional dependency
    rf_levenshtein = None

DEFAULT_THRESHOLDS = {
    "critical": 100,
    "high": 90,
    "medium": 80,
    "low": 65,
}

DEFAULT_RULES_PATH = Path(__file__).parent / "data" / "suspicious.yaml"
ENV_RULES_PATH = "MANAGER_RULES_PATH"


@dataclass
class Rules:
    """In-memory representation of keyword/TLD heuristics."""

    keywords: Dict[str, int]
    tlds: Tuple[str, ...]
    thresholds: Dict[str, int] = field(default_factory=lambda: dict(DEFAULT_THRESHOLDS))

    @property
    def strong_keywords(self) -> Tuple[str, ...]:
        return tuple(key for key, score in self.keywords.items() if score >= 70)


@dataclass
class Classification:
    score: int
    risk: str
    matched_keyword: Optional[str] = None
    matched_tld: Optional[str] = None
    details: Dict[str, object] = field(default_factory=dict)

    def to_record(self) -> Dict[str, object]:
        return {
            "score": self.score,
            "risk_level": self.risk,
            "matched_keyword": self.matched_keyword,
            "matched_tld": self.matched_tld,
            "details": self.details or None,
        }

    def as_json(self) -> Optional[str]:
        record = self.to_record()
        # Avoid storing mostly-empty payloads
        if all(record.get(k) is None for k in ("matched_keyword", "matched_tld", "details")):
            return None
        return json.dumps(record, ensure_ascii=False)


def _load_rules_from_path(path: Path) -> Rules:
    with path.open("r", encoding="utf-8") as fh:
        raw = yaml.safe_load(fh) or {}

    keywords = raw.get("keywords") or {}
    tlds = raw.get("tlds") or {}
    thresholds = raw.get("thresholds") or {}

    # Normalize structures
    normalized_keywords = {str(k).lower(): int(v) for k, v in keywords.items()}
    normalized_tlds = tuple(str(t).lower() for t in tlds.keys())
    normalized_thresholds = dict(DEFAULT_THRESHOLDS)
    for key, value in thresholds.items():
        if key in DEFAULT_THRESHOLDS:
            normalized_thresholds[key] = int(value)

    return Rules(
        keywords=normalized_keywords,
        tlds=normalized_tlds,
        thresholds=normalized_thresholds,
    )


def _current_rules_path() -> Path:
    override = os.environ.get(ENV_RULES_PATH)
    if override:
        path = Path(override).expanduser()
        if path.exists():
            return path
    return DEFAULT_RULES_PATH


class DomainClassifier:
    """Scores domains using phishing_catcher-inspired heuristics."""

    def __init__(self, rules: Rules):
        self.rules = rules

    # --- Public API -----------------------------------------------------
    def classify(self, domain: str) -> Classification:
        prepared = self._prepare_domain(domain)
        if not prepared:
            # Domain did not pass basic sanity checks; treat score as 0
            return Classification(score=0, risk="unknown")

        original, normalized, words = prepared
        score = 0
        details: Dict[str, object] = {
            "domain": original,
            "normalized": normalized,
            "keyword_hits": [],
            "levenshtein_hits": [],
        }

        matched_tld = None
        for tld in self.rules.tlds:
            if normalized.endswith(tld):
                score += 20
                matched_tld = tld
                details["keyword_hits"].append({"type": "tld", "value": tld, "score": 20})
                break

        # Entropy-based score
        score_entropy = self._entropy_score(normalized)
        score += score_entropy
        if score_entropy:
            details["entropy"] = score_entropy

        # Base domain heuristics
        if words and words[0] in {"com", "net", "org"}:
            score += 10
            details["keyword_hits"].append({"type": "prefix", "value": words[0], "score": 10})

        matched_keyword = None
        for keyword, weight in self.rules.keywords.items():
            if keyword in normalized:
                score += weight
                if matched_keyword is None:
                    matched_keyword = keyword
                else:
                    current_weight = self.rules.keywords.get(matched_keyword, -1)
                    if weight > current_weight:
                        matched_keyword = keyword
                details["keyword_hits"].append({"type": "keyword", "value": keyword, "score": weight})

        strong_hits = self._levenshtein_hits(words)
        if strong_hits:
            score += 70 * len(strong_hits)
            details["levenshtein_hits"] = [dict(hit) for hit in strong_hits]
            if not matched_keyword:
                matched_keyword = strong_hits[0].get("target")

        hyphen_count = normalized.count("-")
        if "xn--" not in normalized and hyphen_count >= 4:
            bonus = hyphen_count * 3
            score += bonus
            details["keyword_hits"].append({"type": "hyphen", "value": hyphen_count, "score": bonus})

        dot_count = normalized.count(".")
        if dot_count >= 3:
            bonus = dot_count * 3
            score += bonus
            details["keyword_hits"].append({"type": "subdomain", "value": dot_count, "score": bonus})

        risk = label_score(score, self.rules.thresholds)

        # Clean up details for storage
        if not details["keyword_hits"]:
            details.pop("keyword_hits")
        if not details["levenshtein_hits"]:
            details.pop("levenshtein_hits")
        if "entropy" in details and not details["entropy"]:
            details.pop("entropy")
        if not details:
            details = {}

        return Classification(
            score=score,
            risk=risk,
            matched_keyword=matched_keyword,
            matched_tld=matched_tld,
            details=details,
        )

    # --- Internal helpers -----------------------------------------------
    def _prepare_domain(self, domain: str) -> Optional[Tuple[str, str, Tuple[str, ...]]]:
        if not domain:
            return None

        candidate = domain.strip().lower()
        if candidate.startswith("*."):
            candidate = candidate[2:]

        if "." not in candidate or " " in candidate:
            return None

        # Try to remove the registered TLD so subdomain heuristics work
        try:
            res = get_tld(candidate, as_object=True, fail_silently=True, fix_protocol=True)
            if res:
                parts = [value for value in (res.subdomain, res.domain) if value]
                candidate = ".".join(parts) if parts else res.domain
        except Exception:
            pass

        words = tuple(filter(None, re.split(r"\W+", candidate)))
        if not words:
            return None

        return domain, candidate, words

    def _entropy_score(self, value: str) -> int:
        if not value:
            return 0
        probabilities = [float(value.count(c)) / len(value) for c in dict.fromkeys(value)]
        entropy = -sum(p * math.log(p, 2.0) for p in probabilities if p > 0)
        return int(round(entropy * 10))

    def _levenshtein_hits(self, words: Tuple[str, ...]) -> Tuple[Dict[str, str], ...]:
        strong_keywords = self.rules.strong_keywords
        if not strong_keywords:
            return tuple()

        relevant_words = tuple(word for word in words if word not in {"email", "mail", "cloud"})
        hits = []
        for word in relevant_words:
            for target in strong_keywords:
                if _distance(word, target) == 1:
                    hits.append({"word": word, "target": target})
        return tuple(hits)


def label_score(score: int, thresholds: Optional[Dict[str, int]] = None) -> str:
    thresholds = thresholds or DEFAULT_THRESHOLDS
    if score >= thresholds.get("critical", 100):
        return "critical"
    if score >= thresholds.get("high", 90):
        return "high"
    if score >= thresholds.get("medium", 80):
        return "medium"
    if score >= thresholds.get("low", 65):
        return "low"
    return "unknown"


_classifier_lock = threading.Lock()
_cached_classifier: Optional[DomainClassifier] = None
_cached_rules_path: Optional[Path] = None
_cached_mtime: Optional[float] = None


def get_classifier() -> DomainClassifier:
    """Return a cached DomainClassifier, reloading rules if needed."""
    global _cached_classifier, _cached_rules_path, _cached_mtime

    path = _current_rules_path()
    mtime = path.stat().st_mtime if path.exists() else None

    with _classifier_lock:
        must_reload = (
            _cached_classifier is None
            or _cached_rules_path != path
            or (mtime and _cached_mtime and mtime > _cached_mtime)
        )

        if must_reload:
            rules = _load_rules_from_path(path)
            _cached_classifier = DomainClassifier(rules)
            _cached_rules_path = path
            _cached_mtime = mtime

        return _cached_classifier


def _distance(a: str, b: str) -> int:
    """Compute Levenshtein distance with fallbacks."""
    if levenshtein_distance:
        return int(levenshtein_distance(a, b))
    if rf_levenshtein:
        return int(rf_levenshtein.distance(a, b))
    # Fallback: simple dynamic programming (slower but always available)
    if a == b:
        return 0
    len_a, len_b = len(a), len(b)
    dp = list(range(len_b + 1))
    for i in range(1, len_a + 1):
        prev = dp[0]
        dp[0] = i
        for j in range(1, len_b + 1):
            current = dp[j]
            if a[i - 1] == b[j - 1]:
                dp[j] = prev
            else:
                dp[j] = 1 + min(prev, dp[j], dp[j - 1])
            prev = current
    return dp[len_b]


__all__ = [
    "Classification",
    "DomainClassifier",
    "DEFAULT_RULES_PATH",
    "get_classifier",
    "label_score",
]

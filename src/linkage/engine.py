"""Integrated Member 3 linkage engine for blocking, matching, and clustering."""

from __future__ import annotations

from typing import Sequence

from src.contracts import LinkageDecision, PatientCluster, PatientRecord
from src.linkage.blocking import generate_candidate_pairs
from src.linkage.clustering import cluster_records
from src.linkage.matcher import MatcherPolicy, match_candidates


class ConservativeLinkageEngine:
    """Protocol-compatible linkage engine with conservative defaults."""

    def __init__(
        self,
        matcher_policy: MatcherPolicy | None = None,
        max_bucket_size: int = 100,
    ) -> None:
        self.matcher_policy = matcher_policy or MatcherPolicy()
        self.max_bucket_size = max_bucket_size

    def link_records(
        self, records: Sequence[PatientRecord]
    ) -> tuple[list[LinkageDecision], list[PatientCluster]]:
        candidates = generate_candidate_pairs(records, self.max_bucket_size)
        decisions = match_candidates(records, candidates, self.matcher_policy)
        result = cluster_records(records, decisions)
        return decisions, list(result.clusters)

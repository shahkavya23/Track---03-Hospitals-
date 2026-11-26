"""Integrated Member 3 linkage engine for blocking, matching, and clustering."""

from __future__ import annotations

from typing import Sequence
from collections import defaultdict

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
        ambiguity_margin: float = 0.05,
        ambiguity_floor: float = 0.5,
    ) -> None:
        self.matcher_policy = matcher_policy or MatcherPolicy()
        self.max_bucket_size = max_bucket_size
        self.ambiguity_margin = ambiguity_margin
        self.ambiguity_floor = ambiguity_floor

    def link_records(
        self, records: Sequence[PatientRecord]
    ) -> tuple[list[LinkageDecision], list[PatientCluster]]:
        candidates = generate_candidate_pairs(records, self.max_bucket_size)
        decisions = match_candidates(records, candidates, self.matcher_policy)
        scores: dict[str, list[float]] = defaultdict(list)
        for decision in decisions:
            if decision.score >= self.ambiguity_floor:
                scores[decision.record_ref_a].append(decision.score)
                scores[decision.record_ref_b].append(decision.score)
        records_by_ref = {record.record_ref: record for record in records}
        for record_ref, candidate_scores in scores.items():
            ordered = sorted(candidate_scores, reverse=True)
            if len(ordered) >= 2 and ordered[0] - ordered[1] <= self.ambiguity_margin:
                records_by_ref[record_ref].field_metadata["linkage_null_reason"] = (
                    "AMBIGUOUS_CANDIDATE_CLUSTERS"
                )
        result = cluster_records(records, decisions)
        return decisions, list(result.clusters)

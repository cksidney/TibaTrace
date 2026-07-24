from __future__ import annotations

from abc import ABC, abstractmethod
from dataclasses import dataclass
from typing import Iterable


@dataclass(frozen=True)
class KnowledgeFinding:
    rule_id: str
    rule_version: str
    rule_type: str
    source: str
    source_version: str
    effective_date: object
    severity: str
    evidence_summary: str
    explanation: str
    recommended_action: str
    override_policy: str
    affected_medicine_id: object | None
    interacting_factor: str
    prescription_item_id: object | None = None


class ClinicalKnowledgeProvider(ABC):
    @abstractmethod
    def check_drug_drug(self, context) -> Iterable[KnowledgeFinding]: ...

    @abstractmethod
    def check_allergy(self, context) -> Iterable[KnowledgeFinding]: ...

    @abstractmethod
    def check_duplicate_therapy(self, context) -> Iterable[KnowledgeFinding]: ...

    @abstractmethod
    def check_condition_contraindication(self, context) -> Iterable[KnowledgeFinding]: ...

    @abstractmethod
    def check_age(self, context) -> Iterable[KnowledgeFinding]: ...

    @abstractmethod
    def check_pregnancy(self, context) -> Iterable[KnowledgeFinding]: ...

    @abstractmethod
    def check_renal(self, context) -> Iterable[KnowledgeFinding]: ...

    @abstractmethod
    def check_hepatic(self, context) -> Iterable[KnowledgeFinding]: ...

    @abstractmethod
    def check_dose(self, context) -> Iterable[KnowledgeFinding]: ...

    @abstractmethod
    def check_duration(self, context) -> Iterable[KnowledgeFinding]: ...

    def check_frequency(self, context) -> Iterable[KnowledgeFinding]:
        return ()

    def check_weight(self, context) -> Iterable[KnowledgeFinding]:
        return ()

    def check_lactation(self, context) -> Iterable[KnowledgeFinding]:
        return ()

    def check_controlled_medicine(self, context) -> Iterable[KnowledgeFinding]:
        return ()

    def check_repeat_interval(self, context) -> Iterable[KnowledgeFinding]:
        return ()

    def check_formulary(self, context) -> Iterable[KnowledgeFinding]:
        return ()

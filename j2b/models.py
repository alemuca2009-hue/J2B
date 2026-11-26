"""Data model for scans, conversions and reports."""

from __future__ import annotations

from dataclasses import dataclass, field
from pathlib import Path
from typing import Any

from .utils import clamp, now_iso

STATUS_WEIGHT = {"converted": 1.0, "partial": 0.55, "manual": 0.15, "unsupported": 0.0, "skipped": 0.0}
STATUS_ORDER = ("converted", "partial", "manual", "unsupported", "skipped")


@dataclass
class Issue:
    severity: str
    code: str
    message: str
    detail: str = ""
    feature_id: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "severity": self.severity,
            "code": self.code,
            "message": self.message,
            "detail": self.detail,
            "feature_id": self.feature_id,
        }


@dataclass
class Feature:
    id: str
    kind: str
    name: str
    display: str = ""
    source: str = ""
    data: dict[str, Any] = field(default_factory=dict)
    status: str = "pending"
    confidence: float = 0.0
    strategy: str = ""
    issues: list[Issue] = field(default_factory=list)
    limitations: list[str] = field(default_factory=list)
    assumptions: list[str] = field(default_factory=list)
    outputs: list[str] = field(default_factory=list)
    kb_refs: list[dict[str, Any]] = field(default_factory=list)

    # -- mutation helpers -------------------------------------------------
    def add_issue(self, severity: str, code: str, message: str, detail: str = "") -> None:
        self.issues.append(Issue(severity, code, message, detail, self.id))

    def add_limitation(self, text: str) -> None:
        if text and text not in self.limitations:
            self.limitations.append(text)

    def add_assumption(self, text: str) -> None:
        if text and text not in self.assumptions:
            self.assumptions.append(text)

    def add_output(self, path: str) -> None:
        if path and path not in self.outputs:
            self.outputs.append(path)

    def set_result(self, status: str, confidence: float, strategy: str = "") -> None:
        self.status = status
        self.confidence = clamp(confidence)
        if strategy:
            self.strategy = strategy

    # -- serialisation ----------------------------------------------------
    def to_dict(self) -> dict[str, Any]:
        return {
            "id": self.id,
            "kind": self.kind,
            "name": self.name,
            "display": self.display,
            "source": self.source,
            "status": self.status,
            "confidence": round(self.confidence, 3),
            "strategy": self.strategy,
            "outputs": list(self.outputs),
            "limitations": list(self.limitations),
            "assumptions": list(self.assumptions),
            "issues": [issue.to_dict() for issue in self.issues],
            "knowledge": list(self.kb_refs),
            "data_keys": sorted(self.data.keys()),
        }


@dataclass
class ModMetadata:
    name: str = "Unknown mod"
    mod_id: str = "unknown"
    version: str = "0.0.0"
    loader: str = "unknown"
    description: str = ""
    authors: list[str] = field(default_factory=list)
    minecraft_version: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {
            "name": self.name,
            "mod_id": self.mod_id,
            "version": self.version,
            "loader": self.loader,
            "description": self.description,
            "authors": list(self.authors),
            "minecraft_version": self.minecraft_version,
        }


@dataclass
class ConversionOptions:
    output_dir: str = "j2b_output"
    pack_name: str = ""
    make_mcaddon: bool = True
    record_learning: bool = True
    report_formats: tuple[str, ...] = ("json", "md", "html")
    min_engine_version: tuple[int, int, int] = (1, 20, 80)
    #: Optional reference jar (vanilla client jar or resource jar). When given,
    #: vanilla parent models are read from it instead of curated templates.
    vanilla_path: str = ""
    #: Turn Create-style machine blocks (millstone, press, deployer…) into custom
    #: Bedrock crafting stations so their processing recipes survive as hand crafts.
    machine_stations: bool = True
    #: When a machine recipe has no station block in the pack, still write it onto
    #: the plain crafting table. Off by default: it changes where a recipe is made.
    machine_workbench: bool = False



@dataclass
class PackPaths:
    root: Path
    bp: Path
    rp: Path
    mcaddon: Path | None = None

    def to_dict(self) -> dict[str, Any]:
        return {
            "root": str(self.root),
            "behavior_pack": str(self.bp),
            "resource_pack": str(self.rp),
            "mcaddon": str(self.mcaddon) if self.mcaddon else None,
        }


@dataclass
class Check:
    severity: str
    check_id: str
    message: str
    detail: str = ""

    def to_dict(self) -> dict[str, Any]:
        return {"severity": self.severity, "check": self.check_id, "message": self.message, "detail": self.detail}


@dataclass
class ScanResult:
    mod: ModMetadata
    namespaces: list[str] = field(default_factory=list)
    features: list[Feature] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)


@dataclass
class ConversionResult:
    mod: ModMetadata
    features: list[Feature] = field(default_factory=list)
    packs: PackPaths | None = None
    reports: dict[str, str] = field(default_factory=dict)
    validation: list[Check] = field(default_factory=list)
    issues: list[Issue] = field(default_factory=list)
    stats: dict[str, Any] = field(default_factory=dict)
    history_id: int | None = None
    started_at: str = field(default_factory=now_iso)
    finished_at: str = ""

    def compute_stats(self) -> dict[str, Any]:
        counts = {status: 0 for status in STATUS_ORDER}
        by_kind: dict[str, dict[str, int]] = {}
        weighted = 0.0
        counted = 0
        for feature in self.features:
            counts[feature.status] = counts.get(feature.status, 0) + 1
            bucket = by_kind.setdefault(feature.kind, {})
            bucket[feature.status] = bucket.get(feature.status, 0) + 1
            if feature.status == "skipped":
                continue
            weighted += STATUS_WEIGHT.get(feature.status, 0.0)
            counted += 1
        fidelity = weighted / counted if counted else 0.0
        documented = sum(1 for feature in self.features if feature.kb_refs)
        stats = {
            "features_total": len(self.features),
            "status_counts": counts,
            "by_kind": by_kind,
            "estimated_fidelity": round(fidelity, 4),
            "kb_documented": documented,
            "kb_coverage": round(documented / len(self.features), 3) if self.features else 0.0,
            "limitations_total": sum(len(feature.limitations) for feature in self.features),
            "manual_work": sum(
                1 for feature in self.features if feature.status in ("manual", "unsupported")
            ),
        }
        self.stats = stats
        return stats

    def to_dict(self) -> dict[str, Any]:
        stats = self.stats or self.compute_stats()
        return {
            "tool": {"name": "J2B Studio"},
            "mod": self.mod.to_dict(),
            "packs": self.packs.to_dict() if self.packs else None,
            "stats": stats,
            "features": [feature.to_dict() for feature in self.features],
            "validation": [check.to_dict() for check in self.validation],
            "issues": [issue.to_dict() for issue in self.issues],
            "reports": dict(self.reports),
            "started_at": self.started_at,
            "finished_at": self.finished_at,
        }

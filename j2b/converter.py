"""Orchestration: scan → convert → validate → report → remember."""

from __future__ import annotations

from contextlib import ExitStack
from pathlib import Path
from typing import Callable

from .analyzer.feature_scan import ModScanner
from .analyzer.model_resolver import ModelResolver
from .analyzer.mod_archive import ModArchive
from .analyzer.tags import TagIndex
from .converters import (
    ConversionContext,
    PackWriter,
    convert_block,
    convert_entity_feature,
    convert_item,
    convert_recipe,
    convert_worldgen,
    convert_sound_feature,
)
from .converters.context import TextureManager
from .history import ConversionHistory
from .knowledge.base import CaseMemory, KnowledgeBase, derive_signals
from .models import Check, ConversionOptions, ConversionResult, Feature
from .report import write_reports
from .utils import now_iso
from .validate import validate_packs

ProgressFn = Callable[[str], None]


class ConversionError(RuntimeError):
    """Raised when the mod cannot be read or nothing convertible was found."""


class Converter:
    def __init__(
        self,
        options: ConversionOptions | None = None,
        knowledge: KnowledgeBase | None = None,
        memory: CaseMemory | None = None,
        progress: ProgressFn | None = None,
    ) -> None:
        self.options = options or ConversionOptions()
        self.knowledge = knowledge or KnowledgeBase()
        self.memory = memory
        self._progress = progress

    # -- helpers ----------------------------------------------------------
    def progress(self, message: str) -> None:
        if self._progress:
            self._progress(message)

    def _dispatch(self, feature: Feature, ctx: ConversionContext) -> None:
        if feature.kind == "block":
            convert_block(feature, ctx)
        elif feature.kind == "item":
            convert_item(feature, ctx)
        elif feature.kind == "recipe":
            convert_recipe(feature, ctx)
        elif feature.kind == "entity":
            convert_entity_feature(feature, ctx)
        elif feature.kind == "worldgen":
            convert_worldgen(feature, ctx)
        elif feature.kind == "sound":
            convert_sound_feature(feature, ctx)
        else:
            self._convert_by_knowledge(feature)

    def _convert_by_knowledge(self, feature: Feature) -> None:
        """GUI and mechanic features: report the documented verdict, build nothing."""
        entry = self.knowledge.best(feature)
        if entry is None:
            feature.set_result("manual", 0.05, "manual_review")
            feature.add_issue(
                "warning",
                "NO_STRATEGY",
                "No documented strategy matches this feature.",
                "Add an overlay entry in knowledge_overlay.json once you decide how it should map.",
            )
            self.knowledge.suggest(
                {
                    "kind": feature.kind,
                    "signals": sorted(derive_signals(feature)),
                    "feature": feature.id,
                    "hint": feature.display,
                }
            )
            return
        feature.set_result(entry.outcome, 0.35 if entry.outcome == "manual" else 0.1, entry.strategy)
        for limitation in entry.limitations:
            feature.add_limitation(limitation)
        feature.add_issue(
            "info" if entry.outcome == "manual" else "warning",
            "STRATEGY_FROM_KB",
            f"Applied documented strategy `{entry.id}`.",
            entry.rationale,
        )
        if feature.data.get("bytecode_only"):
            feature.add_issue(
                "warning",
                "CLASS_HINT_ONLY",
                "Detected from a class name only — no source or bytecode analysis was performed.",
                "Treat this as a lead to inspect, not a finding.",
            )

    def _apply_kb_outcome(self, feature: Feature) -> None:
        """Never let an engine claim more than the documented strategy supports."""
        entry = self.knowledge.best(feature)
        if entry is None or feature.status in ("pending", "skipped"):
            return
        rank = {"converted": 3, "partial": 2, "manual": 1, "unsupported": 0}
        if rank.get(entry.outcome, 0) >= rank.get(feature.status, 0):
            return
        previous = feature.status
        feature.status = entry.outcome
        feature.confidence = min(feature.confidence, 0.7 if entry.outcome == "partial" else 0.4)
        if entry.strategy and not feature.strategy:
            feature.strategy = entry.strategy
        for limitation in entry.limitations:
            feature.add_limitation(limitation)
        feature.add_issue(
            "warning",
            "FIDELITY_DOWNGRADED",
            f"Downgraded from '{previous}' to '{entry.outcome}' to match the documented strategy.",
            f"{entry.title}: {entry.rationale}",
        )

    # -- main entry point -------------------------------------------------
    def convert(self, mod_path: str | Path) -> ConversionResult:
        self.progress(f"Opening {Path(mod_path).name}")
        try:
            archive = ModArchive(mod_path)
        except (OSError, ValueError) as exc:
            raise ConversionError(str(exc)) from exc

        extra = ExitStack()
        with archive, extra:
            vanilla = None
            if self.options.vanilla_path:
                try:
                    vanilla = extra.enter_context(ModArchive(self.options.vanilla_path))
                except (OSError, ValueError) as exc:
                    raise ConversionError(
                        f"The reference jar could not be opened: {exc}"
                    ) from exc
                self.progress(f"Using {Path(self.options.vanilla_path).name} as vanilla reference")

            self.progress("Scanning mod structure and resources")
            scan = ModScanner(archive).scan()
            if not scan.features:
                raise ConversionError(
                    "No convertible features were found. This is expected for mods that only contain code — "
                    "there is nothing in the jar that maps to Bedrock data."
                )
            self.progress(f"Detected {len(scan.features)} features")

            result = ConversionResult(mod=scan.mod, features=scan.features, issues=list(scan.issues))
            writer = PackWriter(
                output_root=self.options.output_dir,
                mod=result.mod,
                pack_name=self.options.pack_name,
                min_engine_version=self.options.min_engine_version,
                make_mcaddon=self.options.make_mcaddon,
            )
            ctx = ConversionContext(
                writer=writer,
                textures=TextureManager(archive, writer),
                options=self.options,
                mod_id=result.mod.mod_id,
                archive=archive,
                tags=TagIndex(archive),
                features=result.features,
                resolver=ModelResolver(archive, vanilla),
            )

            # Recipes are converted after items and blocks, so the set of ids the
            # pack actually defines is known before any recipe is written.
            ctx.known_items = {
                feature.id for feature in result.features if feature.kind in ("item", "block")
            }

            self.progress("Attaching documented strategies")
            for feature in result.features:
                matches = self.knowledge.match(feature)
                feature.kb_refs = [entry.reference(score) for entry, score in matches]
                if not matches:
                    self.knowledge.suggest(
                        {
                            "kind": feature.kind,
                            "signals": sorted(derive_signals(feature)),
                            "feature": feature.id,
                        }
                    )

            self.progress("Converting features")
            for feature in result.features:
                try:
                    self._dispatch(feature, ctx)
                except Exception as exc:  # noqa: BLE001 - one bad feature must not kill the run
                    feature.set_result("unsupported", 0.0, feature.strategy or "error")
                    feature.add_issue(
                        "error",
                        "CONVERSION_FAILED",
                        f"The converter failed on this feature: {exc.__class__.__name__}: {exc}",
                        "This is a bug in J2B Studio; the rest of the conversion continues.",
                    )
                self._apply_kb_outcome(feature)
                if self.memory is not None and self.options.record_learning:
                    self.memory.record(feature, result.mod.mod_id)

            animations = ctx.textures.flush_animations()
            if animations:
                self.progress(f"Wrote {animations} animated texture definition(s)")

            self.progress("Writing pack manifests and texture atlases")
            result.packs = writer.finalize()

            self.progress("Validating generated add-on")
            checks = validate_packs(result.packs.bp, result.packs.rp, result.features)
            seen_ids: dict[str, int] = {}
            for feature in result.features:
                seen_ids[feature.id] = seen_ids.get(feature.id, 0) + 1
            for identifier, count in seen_ids.items():
                if count > 1:
                    checks.append(
                        Check("error", "DUPLICATE_FEATURE_ID",
                              f"Feature id `{identifier}` appears {count} times; per-feature results are ambiguous.")
                    )
            for feature in result.features:
                for issue in feature.issues:
                    if issue.severity in ("error", "warning"):
                        checks.append(Check(issue.severity, issue.code, issue.message, f"{feature.id}: {issue.detail}"))
            for issue in result.issues:
                if issue.severity == "error":
                    checks.append(Check("error", issue.code, issue.message, issue.detail))
            result.validation = checks
            result.stats = result.compute_stats()
            # Texture summary owns the key ``collisions`` (atlas-key clashes);
            # block collision boxes are counted separately so neither number
            # hides the other.
            result.stats["converter"] = ctx.stats() | ctx.textures.summary()
            resolver = ctx.resolver
            if resolver is not None:
                result.stats["models"] = {
                    "vanilla_models_loaded": len(resolver.vanilla_hits),
                    "vanilla_templates_used": len(resolver.template_hits),
                    "unresolved": len(resolver.missing_models),
                }
            if ctx.textures.collisions:
                result.stats["texture_collisions"] = list(ctx.textures.collisions)
            result.stats["knowledge"] = self.knowledge.stats()

            self.progress("Writing reports")
            result.reports = write_reports(result, self.options.output_dir, self.options.report_formats)

            try:
                history = ConversionHistory()
                result.history_id = history.record(result)
                result.stats["history"] = history.stats()
            except Exception:  # noqa: BLE001 - history is optional
                result.stats["history"] = {"available": False}
            if self.memory is not None:
                # One transaction for the whole run's rows instead of one per
                # feature: see CaseMemory.record for the measurement.
                self.memory.flush()
                result.stats["case_memory"] = self.memory.stats()

            result.finished_at = now_iso()
            self.progress("Done")
            return result

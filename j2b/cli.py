"""Command line interface.

    python -m j2b convert mods/ruby.jar -o out
    python -m j2b analyze mods/ruby.jar
    python -m j2b validate out/ruby/behavior_pack
    python -m j2b kb stats
    python -m j2b history
"""

from __future__ import annotations

import argparse
import json
import sys
from pathlib import Path

from .analyzer.feature_scan import ModScanner
from .analyzer.mod_archive import ModArchive
from .converter import ConversionError, Converter
from .history import ConversionHistory
from .knowledge import CaseMemory, KnowledgeBase
from .models import ConversionOptions
from .validate import validate_packs
from .version import __version__


def _print_progress(message: str) -> None:
    print(f"  · {message}", file=sys.stderr)


def cmd_convert(args: argparse.Namespace) -> int:
    options = ConversionOptions(
        output_dir=args.output,
        pack_name=args.pack_name or "",
        make_mcaddon=not args.no_mcaddon,
        record_learning=not args.no_learning,
        vanilla_path=getattr(args, "reference", "") or "",
        report_formats=tuple(part for part in args.reports.split(",") if part),
        machine_stations=not getattr(args, "no_machine_stations", False),
        machine_workbench=getattr(args, "machine_workbench", False),
    )
    converter = Converter(
        options=options,
        knowledge=KnowledgeBase(),
        memory=None if args.no_learning else CaseMemory(),
        progress=None if args.quiet else _print_progress,
    )
    try:
        result = converter.convert(args.mod)
    except ConversionError as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2

    if args.json:
        print(json.dumps(result.to_dict(), indent=2, ensure_ascii=False))
    else:
        stats = result.stats or result.compute_stats()
        counts = stats["status_counts"]
        print(f"\n{result.mod.name} ({result.mod.mod_id} {result.mod.version}, {result.mod.loader})")
        print(
            f"{stats['features_total']} features — "
            f"{counts.get('converted', 0)} converted, {counts.get('partial', 0)} partial, "
            f"{counts.get('manual', 0)} manual, {counts.get('unsupported', 0)} unsupported, "
            f"{counts.get('skipped', 0)} skipped — estimated fidelity "
            f"{stats['estimated_fidelity'] * 100:.1f}%"
        )
        errors = [check for check in result.validation if check.severity == "error"]
        warnings = [check for check in result.validation if check.severity == "warning"]
        for check in errors[:10]:
            print(f"  error: {check.check_id} — {check.message}")
        for check in warnings[:10]:
            print(f"  warning: {check.check_id} — {check.message}")
        overflow = len(errors) + len(warnings) - 20
        if overflow > 0:
            print(f"  … {overflow} more findings in the report")
        print(f"\nOutput: {result.packs.root}")
        if result.packs.mcaddon:
            print(f"Package: {result.packs.mcaddon}")
        for name, path in result.reports.items():
            print(f"  report ({name}): {path}")
        if counts.get("manual", 0) or counts.get("unsupported", 0):
            print("\nManual work remains — see the checklist in the Markdown report.")

    return 1 if any(check.severity == "error" for check in result.validation) else 0


def cmd_analyze(args: argparse.Namespace) -> int:
    try:
        archive = ModArchive(args.mod)
    except (OSError, ValueError) as exc:
        print(f"error: {exc}", file=sys.stderr)
        return 2
    with archive:
        scan = ModScanner(archive).scan()
    if args.json:
        print(
            json.dumps(
                {
                    "mod": scan.mod.to_dict(),
                    "namespaces": scan.namespaces,
                    "stats": scan.stats,
                    "features": [feature.to_dict() for feature in scan.features],
                    "issues": [issue.to_dict() for issue in scan.issues],
                },
                indent=2,
                ensure_ascii=False,
            )
        )
    else:
        print(f"{scan.mod.name} — {scan.mod.mod_id} {scan.mod.version} ({scan.mod.loader})")
        print(f"Namespaces: {', '.join(scan.namespaces) or 'none'}")
        for kind, count in sorted(scan.stats.get("features_by_kind", {}).items()):
            print(f"  {kind:10s} {count}")
        for issue in scan.issues:
            print(f"  {issue.severity}: {issue.code} — {issue.message}")
    return 0


def cmd_validate(args: argparse.Namespace) -> int:
    pack_dir = Path(args.pack).expanduser().resolve()
    if not pack_dir.is_dir():
        print(f"error: {pack_dir} is not a directory", file=sys.stderr)
        return 2
    if (pack_dir / "manifest.json").is_file() and "resource_pack" not in pack_dir.name:
        bp = pack_dir
        rp = pack_dir.parent / "resource_pack"
    else:
        bp = pack_dir / "behavior_pack"
        rp = pack_dir / "resource_pack"
    if not (bp / "manifest.json").is_file():
        print(f"error: no manifest.json in {bp}", file=sys.stderr)
        return 2
    checks = validate_packs(bp, rp, features=[])
    if args.json:
        print(json.dumps([check.to_dict() for check in checks], indent=2, ensure_ascii=False))
    else:
        for check in checks:
            print(f"[{check.severity}] {check.check_id}: {check.message}")
            if check.detail and args.verbose:
                print(f"        {check.detail}")
    return 1 if any(check.severity == "error" for check in checks) else 0


def cmd_kb(args: argparse.Namespace) -> int:
    knowledge = KnowledgeBase()
    if args.action == "stats":
        print(json.dumps(knowledge.stats(), indent=2, ensure_ascii=False))
    elif args.action == "list":
        for entry in sorted(knowledge.entries, key=lambda item: item.id):
            if args.kind and entry.kind != args.kind:
                continue
            print(f"{entry.id}\n  {entry.title} [{entry.outcome}, {entry.verification}]")
            print(f"  signals: {', '.join(entry.signals)}")
    elif args.action == "search":
        needle = (args.query or "").lower()
        hits = [
            entry
            for entry in knowledge.entries
            if needle in entry.id.lower()
            or needle in entry.title.lower()
            or any(needle in limitation.lower() for limitation in entry.limitations)
        ]
        print(json.dumps([entry.reference(0) for entry in hits], indent=2, ensure_ascii=False))
    elif args.action == "audit":
        report = knowledge.audit()
        print(json.dumps(report, indent=2, ensure_ascii=False))
        return 0 if report["ok"] else 1
    elif args.action == "suggestions":
        print(json.dumps(knowledge.load_suggestions(), indent=2, ensure_ascii=False))
    elif args.action == "template":
        print(
            json.dumps(
                {
                    "id": "user.my.entry",
                    "title": "Describe the Java pattern",
                    "kind": "mechanic",
                    "signals": ["mechanic"],
                    "strategy": "manual_review",
                    "outcome": "manual",
                    "rationale": "Why this mapping is correct.",
                    "limitations": ["What does not survive"],
                    "refs": [],
                    "verification": "community",
                },
                indent=2,
            )
        )
    return 0


def cmd_history(args: argparse.Namespace) -> int:
    history = ConversionHistory()
    if args.action == "stats":
        print(json.dumps(history.stats(), indent=2))
    else:
        for row in history.recent(args.limit):
            print(
                f"{row['at']}  {row['mod_name']} ({row['mod_id']})  "
                f"{row['converted']}/{row['features']} converted  "
                f"{row['fidelity'] * 100:.1f}%  errors:{row['validation_errors']}"
            )
    return 0


def cmd_gui(_args: argparse.Namespace) -> int:
    from .gui import launch

    return launch()


def build_parser() -> argparse.ArgumentParser:
    parser = argparse.ArgumentParser(prog="j2b", description="J2B Studio — Java mod to Bedrock add-on converter")
    parser.add_argument("--version", action="version", version=f"J2B Studio {__version__}")
    subparsers = parser.add_subparsers(dest="command", required=True)

    convert = subparsers.add_parser("convert", help="convert a mod jar/zip")
    convert.add_argument("mod")
    convert.add_argument("-o", "--output", default="j2b_output")
    convert.add_argument("--pack-name", default="")
    convert.add_argument("--reference", default="", help="Java reference jar/zip supplying missing models and textures")
    convert.add_argument("--no-mcaddon", action="store_true")
    convert.add_argument("--no-learning", action="store_true")
    convert.add_argument(
        "--no-machine-stations",
        action="store_true",
        help="do not turn machine blocks (millstone, press, deployer…) into crafting stations",
    )
    convert.add_argument(
        "--machine-workbench",
        action="store_true",
        help="write machine recipes without a station block onto the plain crafting table",
    )
    convert.add_argument("--reports", default="json,md,html")
    convert.add_argument("--json", action="store_true", help="print the full result as JSON")
    convert.add_argument("-q", "--quiet", action="store_true")
    convert.set_defaults(func=cmd_convert)

    analyze = subparsers.add_parser("analyze", help="scan a mod without converting")
    analyze.add_argument("mod")
    analyze.add_argument("--json", action="store_true")
    analyze.set_defaults(func=cmd_analyze)

    validate = subparsers.add_parser("validate", help="validate a generated pack folder")
    validate.add_argument("pack")
    validate.add_argument("--json", action="store_true")
    validate.add_argument("-v", "--verbose", action="store_true")
    validate.set_defaults(func=cmd_validate)

    kb = subparsers.add_parser("kb", help="inspect the knowledge base")
    kb.add_argument("action", nargs="?", choices=["stats", "list", "search", "suggestions", "template", "audit"], default="stats")
    kb.add_argument("--kind", default="")
    kb.add_argument("--query", default="")
    kb.set_defaults(func=cmd_kb)

    history = subparsers.add_parser("history", help="previous conversions")
    history.add_argument("action", nargs="?", choices=["list", "stats"], default="list")
    history.add_argument("--limit", type=int, default=20)
    history.set_defaults(func=cmd_history)

    gui = subparsers.add_parser("gui", help="start the desktop UI")
    gui.set_defaults(func=cmd_gui)
    return parser


def main(argv: list[str] | None = None) -> int:
    parser = build_parser()
    args = parser.parse_args(argv)
    return int(args.func(args))


if __name__ == "__main__":
    raise SystemExit(main())

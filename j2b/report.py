"""Conversion reports: JSON for tooling, Markdown for humans, HTML for sharing."""

from __future__ import annotations

import html
import json
from pathlib import Path
from typing import Any

from .models import ConversionResult, Feature

STATUS_LABEL = {
    "converted": "Converted",
    "partial": "Partial",
    "manual": "Manual work",
    "unsupported": "Not supported",
    "skipped": "Skipped",
    "pending": "Pending",
}


def _feature_block(feature: Feature) -> list[str]:
    lines = [f"### `{feature.id}` — {STATUS_LABEL.get(feature.status, feature.status)}", ""]
    lines.append(f"*Kind:* {feature.kind} · *Strategy:* `{feature.strategy or 'none'}` · "
                 f"*Confidence:* {feature.confidence * 100:.0f}%")
    if feature.source:
        lines.append(f"*Source:* `{feature.source}`")
    lines.append("")
    if feature.kb_refs:
        entry = feature.kb_refs[0]
        lines.append(f"**Rule:** {entry['title']} (`{entry['id']}`, {entry['verification']})")
        lines.append("")
    if feature.limitations:
        lines.append("**What does not carry over**")
        lines.extend(f"* {item}" for item in feature.limitations)
        lines.append("")
    if feature.assumptions:
        lines.append("**Assumptions made**")
        lines.extend(f"* {item}" for item in feature.assumptions)
        lines.append("")
    if feature.outputs:
        lines.append("**Files**")
        lines.extend(f"* `{path}`" for path in feature.outputs)
        lines.append("")
    problems = [issue for issue in feature.issues if issue.severity in ("warning", "error")]
    if problems:
        lines.append("**Issues**")
        for issue in problems:
            lines.append(f"* `{issue.code}` — {issue.message}")
        lines.append("")
    return lines


def report_markdown(result: ConversionResult) -> str:
    stats = result.stats or result.compute_stats()
    counts = stats["status_counts"]
    lines = [
        f"# Conversion report — {result.mod.name}",
        "",
        f"`{result.mod.mod_id}` {result.mod.version} · loader: {result.mod.loader} · "
        f"tool: J2B Studio",
        "",
        "## Summary",
        "",
        f"* Features found: **{stats['features_total']}**",
        f"* Converted: **{counts.get('converted', 0)}** · Partial: **{counts.get('partial', 0)}** · "
        f"Manual: **{counts.get('manual', 0)}** · Unsupported: **{counts.get('unsupported', 0)}** · "
        f"Skipped: **{counts.get('skipped', 0)}**",
        f"* Estimated fidelity: **{stats['estimated_fidelity'] * 100:.1f}%** "
        f"(weighted: converted 1.0, partial 0.55, manual 0.15, unsupported 0)",
        f"* Documented by the knowledge base: **{stats['kb_coverage'] * 100:.0f}%** of features",
        "",
        "Fidelity is an honest average over the features that were found, not a promise about gameplay.",
        "",
        "## By kind",
        "",
        "| Kind | Converted | Partial | Manual | Unsupported |",
        "| --- | --- | --- | --- | --- |",
    ]
    for kind, bucket in sorted(stats["by_kind"].items()):
        lines.append(
            f"| {kind} | {bucket.get('converted', 0)} | {bucket.get('partial', 0)} | "
            f"{bucket.get('manual', 0)} | {bucket.get('unsupported', 0)} |"
        )
    lines.append("")

    manual = [f for f in result.features if f.status in ("manual", "unsupported")]
    if manual:
        lines.append("## Manual work checklist")
        lines.append("")
        lines.append("These items are **not** done for you. Each one lists why, and what Bedrock needs instead.")
        lines.append("")
        for feature in manual:
            lines.append(f"* [ ] `{feature.id}` ({STATUS_LABEL.get(feature.status)}) — "
                         + (feature.limitations[0] if feature.limitations else feature.display))
        lines.append("")

    validation = [check for check in result.validation if check.severity in ("error", "warning")]
    if validation:
        lines.append("## Validation")
        lines.append("")
        for check in validation:
            lines.append(f"* **{check.severity}** `{check.check_id}` — {check.message}"
                         + (f"  \n  {check.detail}" if check.detail else ""))
        lines.append("")

    lines.append("## Features")
    lines.append("")
    for feature in sorted(result.features, key=lambda f: (f.kind, f.id)):
        lines.extend(_feature_block(feature))

    if result.issues:
        lines.append("## Scan notes")
        lines.append("")
        for issue in result.issues:
            lines.append(f"* `{issue.code}` — {issue.message}")
        lines.append("")

    lines.append("## How to install")
    lines.append("")
    lines.append("1. Import the `.mcaddon` (double-click it) or copy both folders into "
                 "`development_behavior_packs` / `development_resource_packs`.")
    lines.append("2. Enable both packs on a world — the resource pack is required for textures.")
    lines.append("3. Work through the manual checklist above; the add-on is incomplete without it.")
    return "\n".join(lines) + "\n"


def report_html(result: ConversionResult) -> str:
    markdown = report_markdown(result)
    stats = result.stats or result.compute_stats()
    rows = "".join(
        f"<tr><td><code>{html.escape(feature.id)}</code></td><td>{html.escape(feature.kind)}</td>"
        f"<td class='s-{feature.status}'>{STATUS_LABEL.get(feature.status, feature.status)}</td>"
        f"<td>{html.escape(feature.strategy or '—')}</td>"
        f"<td>{feature.confidence * 100:.0f}%</td></tr>"
        for feature in sorted(result.features, key=lambda f: (f.kind, f.id))
    )
    return f"""<!doctype html>
<html lang="en"><head><meta charset="utf-8">
<title>J2B Studio — {html.escape(result.mod.name)}</title>
<style>
body{{font:15px/1.55 -apple-system,Segoe UI,Roboto,sans-serif;background:#0b0f17;color:#dbe4f0;margin:0;padding:40px}}
main{{max-width:980px;margin:0 auto}}
h1{{font-size:26px;margin:0 0 4px}}h2{{margin-top:34px;font-size:18px;border-bottom:1px solid #1d2636;padding-bottom:6px}}
code{{background:#131c2b;padding:1px 5px;border-radius:4px;font-size:13px}}
table{{border-collapse:collapse;width:100%;margin-top:12px}}
th,td{{text-align:left;padding:7px 9px;border-bottom:1px solid #1d2636;font-size:14px}}
th{{color:#8b9bb4;font-weight:600}}
.muted{{color:#8b9bb4}}
.s-converted{{color:#4ade80}}.s-partial{{color:#fbbf24}}.s-manual{{color:#60a5fa}}
.s-unsupported{{color:#f87171}}.s-skipped{{color:#94a3b8}}
pre{{white-space:pre-wrap;background:#0f1724;padding:18px;border-radius:8px;font-size:13px;color:#a9b8cc}}
</style></head><body><main>
<h1>{html.escape(result.mod.name)}</h1>
<p class="muted">{html.escape(result.mod.mod_id)} {html.escape(result.mod.version)} · {html.escape(result.mod.loader)}
· estimated fidelity <strong>{stats['estimated_fidelity'] * 100:.1f}%</strong></p>
<table><thead><tr><th>Feature</th><th>Kind</th><th>Status</th><th>Strategy</th><th>Confidence</th></tr></thead>
<tbody>{rows}</tbody></table>
<h2>Full report</h2>
<pre>{html.escape(markdown)}</pre>
</main></body></html>
"""


def write_reports(result: ConversionResult, output_root: str | Path, formats: tuple[str, ...]) -> dict[str, str]:
    base = Path(result.packs.root if result.packs else Path(output_root))
    base.mkdir(parents=True, exist_ok=True)
    written: dict[str, str] = {}
    payload: dict[str, Any] = result.to_dict()

    for fmt in formats:
        fmt = fmt.strip().lower()
        if fmt == "json":
            path = base / "conversion_report.json"
            path.write_text(json.dumps(payload, indent=2, ensure_ascii=False) + "\n", encoding="utf-8")
        elif fmt in ("md", "markdown"):
            path = base / "conversion_report.md"
            path.write_text(report_markdown(result), encoding="utf-8")
        elif fmt == "html":
            path = base / "conversion_report.html"
            path.write_text(report_html(result), encoding="utf-8")
        else:
            continue
        written[fmt] = str(path)
    return written

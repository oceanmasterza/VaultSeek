"""Built-in report format exporters (JSON, CSV, HTML).

Excel and PDF are listed in the Phase 13 roadmap goal but need extra
dependencies and templates that were never specified — deferred. These
three cover machine-readable (JSON), spreadsheet-friendly (CSV), and
human-preview (HTML) without new packages.
"""

from __future__ import annotations

import csv
import html
import io
import json
from typing import Protocol

from vaultseek.services.dto.report_dto import LibrarySummaryReport


class ReportExporter(Protocol):
    """Writes one report format."""

    format_id: str
    file_extension: str
    mime_type: str

    def export(self, report: LibrarySummaryReport) -> bytes: ...


class JsonReportExporter:
    format_id = "json"
    file_extension = ".json"
    mime_type = "application/json"

    def export(self, report: LibrarySummaryReport) -> bytes:
        return (json.dumps(report.to_dict(), indent=2, sort_keys=True) + "\n").encode("utf-8")


class CsvReportExporter:
    format_id = "csv"
    file_extension = ".csv"
    mime_type = "text/csv"

    def export(self, report: LibrarySummaryReport) -> bytes:
        buffer = io.StringIO()
        writer = csv.writer(buffer)
        writer.writerow(["metric", "value"])
        writer.writerow(["library_id", str(report.library_id)])
        writer.writerow(["library_name", report.library_name])
        writer.writerow(["generated_at", report.generated_at.isoformat()])
        writer.writerow(["track_count", report.track_count])
        writer.writerow(["lossless_count", report.lossless_count])
        writer.writerow(["lossy_count", report.lossy_count])
        writer.writerow(["needs_review_count", report.needs_review_count])
        writer.writerow(["has_embedded_art_count", report.has_embedded_art_count])
        writer.writerow(["missing_embedded_art_count", report.missing_embedded_art_count])
        writer.writerow(["open_duplicate_groups", report.open_duplicate_groups])
        writer.writerow(
            [
                "average_confidence",
                "" if report.average_confidence is None else f"{report.average_confidence:.4f}",
            ]
        )
        for zone, count in sorted(report.tracks_by_zone.items()):
            writer.writerow([f"zone.{zone}", count])
        for review_type, count in sorted(report.pending_reviews_by_type.items()):
            writer.writerow([f"pending_review.{review_type}", count])
        for bucket, count in sorted(report.quality_buckets.items()):
            writer.writerow([f"quality.{bucket}", count])
        return buffer.getvalue().encode("utf-8")


class HtmlReportExporter:
    format_id = "html"
    file_extension = ".html"
    mime_type = "text/html"

    def export(self, report: LibrarySummaryReport) -> bytes:
        name = html.escape(report.library_name)
        rows = [
            ("Tracks", str(report.track_count)),
            ("Lossless", str(report.lossless_count)),
            ("Lossy", str(report.lossy_count)),
            ("Needs review", str(report.needs_review_count)),
            ("Embedded art", str(report.has_embedded_art_count)),
            ("Missing embedded art", str(report.missing_embedded_art_count)),
            ("Open duplicate groups", str(report.open_duplicate_groups)),
            (
                "Average confidence",
                "—" if report.average_confidence is None else f"{report.average_confidence:.2%}",
            ),
        ]
        for zone, count in sorted(report.tracks_by_zone.items()):
            rows.append((f"Zone: {zone}", str(count)))
        for review_type, count in sorted(report.pending_reviews_by_type.items()):
            rows.append((f"Pending: {review_type}", str(count)))
        for bucket, count in sorted(report.quality_buckets.items()):
            rows.append((f"Quality: {bucket}", str(count)))

        body_rows = "\n".join(
            f"<tr><th>{html.escape(label)}</th><td>{html.escape(value)}</td></tr>"
            for label, value in rows
        )
        document = f"""<!DOCTYPE html>
<html lang="en">
<head>
<meta charset="utf-8"/>
<title>VaultSeek — {name}</title>
<style>
body {{ font-family: Segoe UI, sans-serif; margin: 2rem; color: #1a1a1a; }}
h1 {{ font-size: 1.4rem; }}
table {{ border-collapse: collapse; min-width: 24rem; }}
th, td {{ border: 1px solid #ccc; padding: 0.4rem 0.75rem; text-align: left; }}
th {{ background: #f4f4f4; }}
.meta {{ color: #666; font-size: 0.9rem; }}
</style>
</head>
<body>
<h1>Library summary — {name}</h1>
<p class="meta">Generated {html.escape(report.generated_at.isoformat())}</p>
<table>
{body_rows}
</table>
</body>
</html>
"""
        return document.encode("utf-8")


BUILTIN_EXPORTERS: tuple[ReportExporter, ...] = (
    JsonReportExporter(),
    CsvReportExporter(),
    HtmlReportExporter(),
)

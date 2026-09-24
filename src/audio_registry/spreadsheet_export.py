from __future__ import annotations

import uuid
import zipfile
from collections.abc import Callable, Collection
from dataclasses import dataclass
from datetime import datetime
from pathlib import Path
from xml.sax.saxutils import escape

from .database import DEFAULT_TAG, ProjectDatabase
from .i18n import t

HEADERS = tuple(t(f"spreadsheet.{key}") for key in (
    "speaker", "transcript", "tag", "notes", "project", "start", "end", "duration"
))
_SECONDS_PER_DAY = 86_400


@dataclass(frozen=True, slots=True)
class SpreadsheetExport:
    path: Path
    count: int


def _xml_text(value: object) -> str:
    text = str(value or "")
    clean = "".join(
        character for character in text
        if character in "\t\n\r"
        or 0x20 <= ord(character) <= 0xD7FF
        or 0xE000 <= ord(character) <= 0xFFFD
        or 0x10000 <= ord(character) <= 0x10FFFF
    )
    return escape(clean)


def _inline_cell(reference: str, value: object, style: int) -> str:
    return (
        f'<c r="{reference}" s="{style}" t="inlineStr"><is>'
        f'<t xml:space="preserve">{_xml_text(value)}</t></is></c>'
    )


def _number_cell(reference: str, value: float, style: int = 3) -> str:
    return f'<c r="{reference}" s="{style}"><v>{value:.15g}</v></c>'


def _worksheet_xml(rows: list[tuple[str, str, str, str, str, float, float, float]]) -> str:
    header_cells = "".join(
        _inline_cell(f"{column}1", header, 1)
        for column, header in zip("ABCDEFGH", HEADERS, strict=True)
    )
    sheet_rows = [f'<row r="1" ht="24" customHeight="1">{header_cells}</row>']
    for row_number, row in enumerate(rows, 2):
        text_cells = "".join(
            _inline_cell(f"{column}{row_number}", value, 2)
            for column, value in zip("ABCDE", row[:5], strict=True)
        )
        time_cells = "".join(
            _number_cell(f"{column}{row_number}", seconds / _SECONDS_PER_DAY)
            for column, seconds in zip("FGH", row[5:], strict=True)
        )
        sheet_rows.append(f'<row r="{row_number}">{text_cells}{time_cells}</row>')
    last_row = max(1, len(rows) + 1)
    return f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<worksheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <dimension ref="A1:H{last_row}"/>
  <sheetViews><sheetView workbookViewId="0" showGridLines="0"><pane ySplit="1" topLeftCell="A2" activePane="bottomLeft" state="frozen"/></sheetView></sheetViews>
  <sheetFormatPr defaultRowHeight="20"/>
  <cols>
    <col min="1" max="1" width="20" customWidth="1"/>
    <col min="2" max="2" width="56" customWidth="1"/>
    <col min="3" max="3" width="16" customWidth="1"/>
    <col min="4" max="4" width="34" customWidth="1"/>
    <col min="5" max="5" width="20" customWidth="1"/>
    <col min="6" max="8" width="17" customWidth="1"/>
  </cols>
  <sheetData>{''.join(sheet_rows)}</sheetData>
  <autoFilter ref="A1:H{last_row}"/>
</worksheet>'''


def _write_xlsx(path: Path, rows: list[tuple[str, str, str, str, str, float, float, float]]) -> None:
    parts = {
        "[Content_Types].xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Types xmlns="http://schemas.openxmlformats.org/package/2006/content-types">
  <Default Extension="rels" ContentType="application/vnd.openxmlformats-package.relationships+xml"/>
  <Default Extension="xml" ContentType="application/xml"/>
  <Override PartName="/xl/workbook.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.sheet.main+xml"/>
  <Override PartName="/xl/worksheets/sheet1.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.worksheet+xml"/>
  <Override PartName="/xl/styles.xml" ContentType="application/vnd.openxmlformats-officedocument.spreadsheetml.styles+xml"/>
</Types>''',
        "_rels/.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/officeDocument" Target="xl/workbook.xml"/>
</Relationships>''',
        "xl/workbook.xml": f'''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<workbook xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main" xmlns:r="http://schemas.openxmlformats.org/officeDocument/2006/relationships">
  <sheets><sheet name="{_xml_text(t('spreadsheet.sheet'))}" sheetId="1" r:id="rId1"/></sheets>
</workbook>''',
        "xl/_rels/workbook.xml.rels": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<Relationships xmlns="http://schemas.openxmlformats.org/package/2006/relationships">
  <Relationship Id="rId1" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/worksheet" Target="worksheets/sheet1.xml"/>
  <Relationship Id="rId2" Type="http://schemas.openxmlformats.org/officeDocument/2006/relationships/styles" Target="styles.xml"/>
</Relationships>''',
        "xl/styles.xml": '''<?xml version="1.0" encoding="UTF-8" standalone="yes"?>
<styleSheet xmlns="http://schemas.openxmlformats.org/spreadsheetml/2006/main">
  <numFmts count="1"><numFmt numFmtId="164" formatCode="[h]:mm:ss.000"/></numFmts>
  <fonts count="2">
    <font><sz val="10"/><name val="Microsoft YaHei"/><family val="2"/></font>
    <font><b/><color rgb="FFFFFFFF"/><sz val="10"/><name val="Microsoft YaHei"/><family val="2"/></font>
  </fonts>
  <fills count="3">
    <fill><patternFill patternType="none"/></fill>
    <fill><patternFill patternType="gray125"/></fill>
    <fill><patternFill patternType="solid"><fgColor rgb="FF1F4E78"/><bgColor indexed="64"/></patternFill></fill>
  </fills>
  <borders count="2">
    <border><left/><right/><top/><bottom/><diagonal/></border>
    <border><left/><right/><top/><bottom style="thin"><color rgb="FFD9E2F3"/></bottom><diagonal/></border>
  </borders>
  <cellStyleXfs count="1"><xf numFmtId="0" fontId="0" fillId="0" borderId="0"/></cellStyleXfs>
  <cellXfs count="4">
    <xf numFmtId="0" fontId="0" fillId="0" borderId="0" xfId="0"/>
    <xf numFmtId="0" fontId="1" fillId="2" borderId="0" xfId="0" applyAlignment="1"><alignment horizontal="center" vertical="center"/></xf>
    <xf numFmtId="0" fontId="0" fillId="0" borderId="1" xfId="0" applyAlignment="1"><alignment vertical="top" wrapText="1"/></xf>
    <xf numFmtId="164" fontId="0" fillId="0" borderId="1" xfId="0" applyNumberFormat="1" applyAlignment="1"><alignment horizontal="right" vertical="top"/></xf>
  </cellXfs>
  <cellStyles count="1"><cellStyle name="Normal" xfId="0" builtinId="0"/></cellStyles>
</styleSheet>''',
        "xl/worksheets/sheet1.xml": _worksheet_xml(rows),
    }
    temporary = path.with_name(f".{path.name}.{uuid.uuid4().hex}.tmp")
    try:
        with zipfile.ZipFile(temporary, "w", compression=zipfile.ZIP_DEFLATED) as archive:
            for name, content in parts.items():
                archive.writestr(name, content.encode("utf-8"))
        temporary.replace(path)
    finally:
        temporary.unlink(missing_ok=True)


def export_assembly_spreadsheet(
    database: ProjectDatabase,
    project_names: Collection[str],
    destination: str | Path,
    *,
    selected_speakers: Collection[str],
    selected_tags: Collection[str],
    on_progress: Callable[[int, int], None] | None = None,
) -> SpreadsheetExport:
    """Export the currently filtered saved rows without audio paths or offsets."""
    projects = database.load_assembly(sorted(project_names, key=str.casefold))["projects"]
    allowed_speakers = set(selected_speakers)
    allowed_tags = set(selected_tags)
    candidates = [
        (project, row)
        for project in projects
        for row in sorted(
            project["segments"],
            key=lambda item: (float(item["start"]), float(item["end"]), str(item["id"])),
        )
        if not row.get("deleted", False)
        and str(row.get("speaker") or "Unassigned") in allowed_speakers
        and str(row.get("tag") or DEFAULT_TAG) in allowed_tags
    ]
    if on_progress:
        on_progress(0, len(candidates))
    rows: list[tuple[str, str, str, str, str, float, float, float]] = []
    for index, (project, row) in enumerate(candidates, 1):
        start = float(row["start"])
        end = float(row["end"])
        rows.append((
            str(row.get("speaker") or "Unassigned"),
            str(row.get("text") or ""),
            str(row.get("tag") or DEFAULT_TAG),
            str(row.get("note") or ""),
            str(project["project_name"]),
            start,
            end,
            max(0.0, end - start),
        ))
        if on_progress:
            on_progress(index, len(candidates))
    output_directory = Path(destination).resolve()
    if not output_directory.is_dir():
        raise FileNotFoundError(output_directory)
    output_path = output_directory / t(
        "spreadsheet.filename", timestamp=datetime.now().strftime("%Y%m%d-%H%M%S-%f")
    )
    _write_xlsx(output_path, rows)
    return SpreadsheetExport(output_path, len(rows))

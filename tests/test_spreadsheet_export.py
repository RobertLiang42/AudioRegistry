from __future__ import annotations

import tempfile
import unittest
import zipfile
from pathlib import Path
from xml.etree import ElementTree

from audio_registry.database import ProjectDatabase
from audio_registry.models import Segment
from audio_registry.spreadsheet_export import HEADERS, export_assembly_spreadsheet

_NS = {"x": "http://schemas.openxmlformats.org/spreadsheetml/2006/main"}


class SpreadsheetExportTests(unittest.TestCase):
    def test_exports_only_filtered_metadata_with_raw_database_times(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "secret-audio.wav"
            audio.touch()
            database = ProjectDatabase(root / "audio-registry.sqlite3")
            database.create_review("项目甲", audio, [
                Segment(1.25, 2.75, "甲", "保留文本"),
                Segment(4, 6, "乙", "排除文本"),
            ])
            database.set_audio_offset("项目甲", audio, 123.456)
            project = database.load_assembly(["项目甲"])["projects"][0]
            database.save_assembly([{
                "project_name": "项目甲",
                "revision": project["revision"],
                "items": [
                    {**project["segments"][0], "tag": "保留", "note": "备注一"},
                    {**project["segments"][1], "tag": "排除", "note": "备注二"},
                ],
            }])

            exported = export_assembly_spreadsheet(
                database, ["项目甲"], root,
                selected_speakers=["甲"], selected_tags=["保留"],
            )
            self.assertEqual(exported.count, 1)
            self.assertEqual(exported.path.suffix, ".xlsx")
            with zipfile.ZipFile(exported.path) as archive:
                sheet_bytes = archive.read("xl/worksheets/sheet1.xml")
                sheet = ElementTree.fromstring(sheet_bytes)
                rows = sheet.findall(".//x:sheetData/x:row", _NS)
                self.assertEqual(len(rows), 2)

                def values(row):
                    result = []
                    for cell in row.findall("x:c", _NS):
                        if cell.get("t") == "inlineStr":
                            result.append("".join(cell.itertext()))
                        else:
                            result.append(float(cell.findtext("x:v", namespaces=_NS)))
                    return result

                self.assertEqual(values(rows[0]), list(HEADERS))
                data = values(rows[1])
                self.assertEqual(data[:5], ["甲", "保留文本", "保留", "备注一", "项目甲"])
                self.assertAlmostEqual(data[5] * 86400, 1.25)
                self.assertAlmostEqual(data[6] * 86400, 2.75)
                self.assertAlmostEqual(data[7] * 86400, 1.5)
                self.assertIsNotNone(sheet.find(".//x:pane[@state='frozen']", _NS))
                self.assertEqual(sheet.find("x:autoFilter", _NS).get("ref"), "A1:H2")
                self.assertNotIn(b"secret-audio", sheet_bytes)
                self.assertNotIn(b"123.456", sheet_bytes)

    def test_empty_filter_still_exports_the_exact_header(self):
        with tempfile.TemporaryDirectory() as directory:
            root = Path(directory)
            audio = root / "source.wav"
            audio.touch()
            database = ProjectDatabase(root / "audio-registry.sqlite3")
            database.create_review("项目", audio, [Segment(0, 1, "甲", "文本")])
            exported = export_assembly_spreadsheet(
                database, ["项目"], root, selected_speakers=[], selected_tags=[]
            )
            self.assertEqual(exported.count, 0)
            with zipfile.ZipFile(exported.path) as archive:
                sheet = ElementTree.fromstring(archive.read("xl/worksheets/sheet1.xml"))
            self.assertEqual(len(sheet.findall(".//x:sheetData/x:row", _NS)), 1)
            self.assertEqual(sheet.find("x:autoFilter", _NS).get("ref"), "A1:H1")


if __name__ == "__main__":
    unittest.main()

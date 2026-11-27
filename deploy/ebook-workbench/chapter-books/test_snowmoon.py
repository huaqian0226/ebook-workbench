import io
import json
import unittest
import zipfile
import xml.etree.ElementTree as ET

from snowmoon import REV, chapters, repair_diagrams


class IntegrityTest(unittest.TestCase):
    def test_a_missing_final_chapter_prevents_publication(self):
        data = io.BytesIO()
        with zipfile.ZipFile(data, "w") as archive:
            archive.writestr(
                f"Snowmoon-{REV}/content/episodes.json",
                json.dumps([{"id": i} for i in range(1, 32)]),
            )
        with zipfile.ZipFile(data) as archive, self.assertRaisesRegex(ValueError, "Incomplete"):
            list(chapters(archive))

    def test_each_diagram_gets_its_own_matching_reference(self):
        original = '<svg><marker id="arrow"/><path marker-end="url(#arrow)"/></svg>'
        translated = original.replace(' id="arrow"', '')
        root = ET.fromstring("<body>" + repair_diagrams(translated * 2, original * 2) + "</body>")
        refs = [svg.find("marker").attrib["id"] for svg in root]
        self.assertEqual(len(set(refs)), 2)
        for svg, ident in zip(root, refs):
            self.assertEqual(svg.find("path").attrib["marker-end"], f"url(#{ident})")

    def test_no_original_diagram_is_a_hard_error(self):
        with self.assertRaisesRegex(ValueError, "corresponding original"):
            repair_diagrams('<svg><use href="#figure"/></svg>', "<svg/>")

import unittest
from unittest.mock import patch
from xml.etree import ElementTree as ET

from workbench_sources import PROVIDERS, programming_records, solo_record, standard_list


class CatalogTests(unittest.TestCase):
    def test_comic_catalog_participates_in_ebook_requests(self):
        self.assertEqual(
            PROVIDERS["pepper-carrot-zh"].info()["mediaTypes"], ["book", "comic"]
        )

    def test_full_author_can_be_entered_in_reading_order(self):
        with patch("workbench_sources.solo_fetch", return_value=[]) as fetch:
            PROVIDERS["oxford-solo"].search("Astrophysics", "Bradley W. Carroll", "", 4)
        fetch.assert_called_once_with(
            'alma.title="Astrophysics" and alma.creator all "Bradley W. Carroll"', "", 4
        )

    def test_edition_with_two_isbns(self):
        record = ET.fromstring(
            '<record><controlfield tag="001">1234</controlfield><datafield tag="020"><subfield code="a">1-108-39024-2</subfield></datafield><datafield tag="020"><subfield code="a">1-108-38098-0</subfield></datafield><datafield tag="245"><subfield code="a">Astronomy /</subfield></datafield></record>'
        )
        hit = solo_record(record, "9781108380980")
        self.assertEqual((hit["title"], hit["isbn13"]), ("Astronomy", "9781108380980"))
        self.assertNotIn("isbn13", solo_record(record, ""))
        self.assertIn("alma1234", hit["url"])

    def test_individual_standard_editions(self):
        doc = b'<html><li typeof="schema:Book" about="/ebooks/jane-austen/emma"><span property="schema:name">Emma</span><span property="schema:name">Jane Austen</span></li></html>'
        (hit,) = standard_list(doc)
        self.assertEqual(hit["authors"], ["Jane Austen"])
        self.assertEqual(
            hit["url"], "https://standardebooks.org/ebooks/jane-austen/emma"
        )

    def test_programming_list_skips_chapter_links(self):
        doc = "* [Index](#index)\n* [Pro Git](https://git-scm.com/book/en/v2) - Scott Chacon, Ben Straub (HTML)"
        (row,) = programming_records(doc, "en")
        self.assertEqual(row["title"], "Pro Git")
        self.assertIn("Ben Straub", row["authors"])
        self.assertEqual(row["languageCode"], "en")

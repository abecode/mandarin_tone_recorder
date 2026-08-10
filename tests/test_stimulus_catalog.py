"""Tests for checked-in stimulus catalog conventions."""

import csv
from pathlib import Path

from django.test import SimpleTestCase


CATALOG_PATH = Path(__file__).resolve().parent.parent / "stimuli" / "syllables.csv"


class StimulusCatalogTests(SimpleTestCase):
    def test_ong_and_iong_rows_use_near_close_rounded_vowel(self) -> None:
        with CATALOG_PATH.open(newline="", encoding="utf-8") as source:
            rows = {
                row["ascii"]: row
                for row in csv.DictReader(source)
                if row["tone"] == "1"
            }

        expected_ipa = {
            "song": "sʊŋ",
            "dong": "tʊŋ",
            "tong": "tʰʊŋ",
            "gong": "gʊŋ",
            "cong": "t͡sʰʊŋ",
            "jiong": "t͡ɕjʊŋ",
            "qiong": "t͡ɕʰjʊŋ",
            "xiong": "ɕjʊŋ",
        }
        for ascii_base, ipa in expected_ipa.items():
            with self.subTest(ascii_base=ascii_base):
                self.assertEqual(rows[ascii_base]["nucleus"], "ʊ")
                self.assertEqual(rows[ascii_base]["ipa"], ipa)

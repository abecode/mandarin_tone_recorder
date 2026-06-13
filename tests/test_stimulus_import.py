"""Tests for the repeatable stimulus catalog import command."""

import tempfile
from pathlib import Path

from django.core.management import call_command
from django.core.management.base import CommandError
from django.test import TestCase

from mandarin_tone_recorder.experiments.models import (
    BaseSyllable,
    Experiment,
    ExperimentStimulus,
    Stimulus,
)


CSV_HEADER = (
    "stimulus_id,base_id,onset,medial,nucleus,coda,ipa,pinyin,"
    "pinyin_number,ascii,tone,is_attested,is_rare,rarity,"
    "source_row,original_line_number\n"
)


class StimulusImportTests(TestCase):
    def write_csv(self, rows: str) -> Path:
        temporary = tempfile.NamedTemporaryFile(
            mode="w",
            encoding="utf-8",
            newline="",
            suffix=".csv",
            delete=False,
        )
        self.addCleanup(Path(temporary.name).unlink, missing_ok=True)
        with temporary:
            temporary.write(CSV_HEADER)
            temporary.write(rows)
        return Path(temporary.name)

    def test_imports_tones_one_to_four_and_one_unspecified_prompt(self) -> None:
        csv_path = self.write_csv(
            "ma1,ma,m,,a,,ma,mā,ma1,ma,1,true,false,common,0,2\n"
            "ma2,ma,m,,a,,ma,má,ma2,ma,2,false,false,common,0,2\n"
            "ma3,ma,m,,a,,ma,mǎ,ma3,ma,3,unknown,false,common,0,2\n"
            "ma4,ma,m,,a,,ma,mà,ma4,ma,4,true,false,common,0,2\n"
            "ma5,ma,m,,a,,ma,ma,ma5,ma,5,true,false,common,0,2\n"
        )

        call_command("import_stimuli", csv=csv_path)

        self.assertEqual(BaseSyllable.objects.count(), 1)
        self.assertEqual(
            Stimulus.objects.filter(
                condition=Stimulus.Condition.TONE_BEARING
            ).count(),
            4,
        )
        self.assertFalse(Stimulus.objects.filter(stable_id="ma5").exists())

        unspecified = Stimulus.objects.get(stable_id="ma_unspecified")
        self.assertEqual(unspecified.display_text, "ma")
        self.assertIsNone(unspecified.target_tone)

        tone_experiment = Experiment.objects.get(slug="mandarin-tone-reading")
        non_tone_experiment = Experiment.objects.get(
            slug="mandarin-non-tone-reading"
        )
        self.assertEqual(tone_experiment.stimuli.count(), 4)
        self.assertEqual(non_tone_experiment.stimuli.count(), 1)
        self.assertFalse(Stimulus.objects.get(stable_id="ma2").is_attested)
        self.assertTrue(Stimulus.objects.get(stable_id="ma3").is_attested)

    def test_import_preserves_nan_as_a_literal_syllable(self) -> None:
        csv_path = self.write_csv(
            "nan1,nan,n,,a,n,nan,nān,nan1,nan,1,true,false,common,0,2\n"
        )

        call_command("import_stimuli", csv=csv_path)

        base = BaseSyllable.objects.get(ascii="nan")
        self.assertEqual(base.pinyin_base, "nan")
        self.assertTrue(Stimulus.objects.filter(stable_id="nan1").exists())
        self.assertTrue(
            Stimulus.objects.filter(stable_id="nan_unspecified").exists()
        )

    def test_excludes_syllabic_m_and_n_from_both_experiments(self) -> None:
        csv_path = self.write_csv(
            "m1,m,m,,,,m,m,m1,m,1,true,true,rare,0,2\n"
            "m5,m,m,,,,m,m,m5,m,5,true,true,rare,0,2\n"
            "n1,n,n,,,,n,n,n1,n,1,true,true,rare,1,3\n"
            "n5,n,n,,,,n,n,n5,n,5,true,true,rare,1,3\n"
            "ma1,ma,m,,a,,ma,mā,ma1,ma,1,true,false,common,2,4\n"
        )

        call_command("import_stimuli", csv=csv_path)

        self.assertFalse(BaseSyllable.objects.filter(ascii__in={"m", "n"}).exists())
        self.assertFalse(
            Stimulus.objects.filter(
                stable_id__in={
                    "m1",
                    "m_unspecified",
                    "n1",
                    "n_unspecified",
                }
            ).exists()
        )
        self.assertTrue(Stimulus.objects.filter(stable_id="ma1").exists())

    def test_rerunning_import_updates_rows_without_creating_duplicates(self) -> None:
        csv_path = self.write_csv(
            "ma1,ma,m,,a,,ma,mā,ma1,ma,1,true,false,common,0,2\n"
        )

        call_command("import_stimuli", csv=csv_path)
        csv_path.write_text(
            CSV_HEADER
            + "ma1,ma,m,,a,,ma,mā updated,ma1,ma,1,true,false,common,0,2\n",
            encoding="utf-8",
        )
        call_command("import_stimuli", csv=csv_path)

        self.assertEqual(BaseSyllable.objects.count(), 1)
        self.assertEqual(Stimulus.objects.count(), 2)
        self.assertEqual(ExperimentStimulus.objects.count(), 2)
        self.assertEqual(
            Stimulus.objects.get(stable_id="ma1").display_text,
            "mā updated",
        )

    def test_duplicate_base_and_tone_uses_first_row(self) -> None:
        csv_path = self.write_csv(
            "ri1,ri,r,,i,,ri,rī,ri1,ri,1,true,false,common,0,2\n"
            "ri1_duplicate,ri,r,,other,,ri,rī,ri1,ri,1,true,false,common,1,3\n"
        )

        call_command("import_stimuli", csv=csv_path)

        base = BaseSyllable.objects.get(ascii="ri")
        self.assertEqual(base.nucleus, "i")
        self.assertTrue(Stimulus.objects.filter(stable_id="ri1").exists())
        self.assertFalse(
            Stimulus.objects.filter(stable_id="ri1_duplicate").exists()
        )
        self.assertEqual(
            ExperimentStimulus.objects.filter(
                experiment__slug="mandarin-tone-reading",
                is_active=True,
            ).count(),
            1,
        )

    def test_invalid_csv_rolls_back_the_complete_import(self) -> None:
        csv_path = self.write_csv(
            "ma1,ma,m,,a,,ma,mā,ma1,ma,1,true,false,common,0,2\n"
            "bad,bad,b,,a,,ba,ba,bax,bad,x,true,false,common,1,3\n"
        )

        with self.assertRaises(CommandError):
            call_command("import_stimuli", csv=csv_path)

        self.assertFalse(BaseSyllable.objects.exists())
        self.assertFalse(Stimulus.objects.exists())

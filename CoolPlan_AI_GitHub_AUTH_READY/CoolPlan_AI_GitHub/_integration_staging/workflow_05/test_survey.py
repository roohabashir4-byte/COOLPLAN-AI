from pathlib import Path
import tempfile
import unittest

from core.survey import inspect_survey_dxf


class SurveyInspectionTests(unittest.TestCase):
    def test_missing_file_raises(self):
        with self.assertRaises(FileNotFoundError):
            inspect_survey_dxf("definitely_missing_survey.dxf")

    def test_non_dxf_rejected(self):
        with tempfile.NamedTemporaryFile(suffix=".dwg") as f:
            with self.assertRaises(ValueError):
                inspect_survey_dxf(f.name)

    def test_real_survey_has_conservative_report(self):
        # Optional integration test: set SURVEY_DXF to a local survey path.
        import os
        path = os.environ.get("SURVEY_DXF")
        if not path:
            self.skipTest("Set SURVEY_DXF to run the real-file integration test")
        report = inspect_survey_dxf(path)
        self.assertEqual(report["format"], "DXF")
        self.assertIn("alignment_performed", report)
        self.assertFalse(report["alignment_performed"])
        self.assertIn("warnings", report)


if __name__ == "__main__":
    unittest.main()

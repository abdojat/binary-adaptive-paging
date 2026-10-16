"""Ensure archive checks fail on corruption rather than merely parse happy paths."""
import importlib.util
from pathlib import Path
import tempfile
import unittest

spec = importlib.util.spec_from_file_location('artifact', Path(__file__).resolve().parents[1] / 'scripts/validate_artifact.py')
artifact = importlib.util.module_from_spec(spec)
spec.loader.exec_module(artifact)


class ArchiveChecks(unittest.TestCase):
    def test_rejects_bad_csv(self):
        for content in ('a,a\n1,2\n', 'a,b\n1\n', 'a\n1,2\n',
                        'a\nNaN\n', 'a\ninf\n', 'a\n',
                        'semantic_mismatches\n1\n', 'oracle_verified\nNO\n',
                        'tlb_measured\nYES\n'):
            with self.subTest(content=content), tempfile.TemporaryDirectory() as directory:
                path = Path(directory) / 'bad.csv'
                path.write_text(content)
                with self.assertRaises(RuntimeError):
                    artifact.rows(path)

    def test_comparison_rejects_changed_value(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / 'a.csv', Path(directory) / 'b.csv'
            a.write_text('value\n1\n')
            b.write_text('value\n2\n')
            with self.assertRaises(RuntimeError):
                artifact.same_csv(a, b)

    def test_csv_comparison_allows_line_ending_difference(self):
        with tempfile.TemporaryDirectory() as directory:
            a, b = Path(directory) / 'a.csv', Path(directory) / 'b.csv'
            a.write_bytes(b'value\r\n1\r\n')
            b.write_bytes(b'value\n1\n')
            artifact.same_csv(a, b)
            self.assertNotEqual(artifact.digest(a), artifact.digest(b))


if __name__ == '__main__':
    unittest.main()

"""配置与战绩持久化测试。"""

import json
import os
import tempfile
import unittest

from minesweeper.core import storage


class ConfigTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "config.json")

    def test_default_config_is_the_legacy_one(self):
        self.assertEqual(storage.DEFAULT_CONFIG, {"rows": 16, "cols": 16, "mines": 99})

    def test_is_valid_config(self):
        self.assertTrue(storage.is_valid_config({"rows": 9, "cols": 9, "mines": 10}))
        self.assertTrue(storage.is_valid_config({"rows": 24, "cols": 30, "mines": 668}))
        self.assertFalse(storage.is_valid_config({"rows": 8, "cols": 9, "mines": 10}))
        self.assertFalse(storage.is_valid_config({"rows": 25, "cols": 9, "mines": 10}))
        self.assertFalse(storage.is_valid_config({"rows": 9, "cols": 8, "mines": 10}))
        self.assertFalse(storage.is_valid_config({"rows": 9, "cols": 31, "mines": 10}))
        self.assertFalse(storage.is_valid_config({"rows": 9, "cols": 9, "mines": 9}))
        self.assertFalse(storage.is_valid_config({"rows": 9, "cols": 9, "mines": 669}))
        self.assertFalse(storage.is_valid_config({"rows": 9, "cols": 9}))
        self.assertFalse(storage.is_valid_config("not a dict"))

    def test_load_config_missing_file_writes_defaults(self):
        config = storage.load_config(self.path)
        self.assertEqual(config, storage.DEFAULT_CONFIG)
        self.assertTrue(os.path.isfile(self.path))
        with open(self.path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), storage.DEFAULT_CONFIG)

    def test_load_config_reads_existing_file(self):
        storage.save_config(self.path, {"rows": 9, "cols": 9, "mines": 10})
        self.assertEqual(
            storage.load_config(self.path), {"rows": 9, "cols": 9, "mines": 10}
        )

    def test_load_config_broken_json_falls_back(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("{not json")
        self.assertEqual(storage.load_config(self.path), storage.DEFAULT_CONFIG)

    def test_load_config_invalid_content_falls_back(self):
        with open(self.path, "w", encoding="utf-8") as f:
            json.dump({"rows": 1, "cols": 1, "mines": 1}, f)
        self.assertEqual(storage.load_config(self.path), storage.DEFAULT_CONFIG)
        with open(self.path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), storage.DEFAULT_CONFIG)

    def test_load_config_accepts_custom_default(self):
        custom = {"rows": 9, "cols": 9, "mines": 10}
        self.assertEqual(storage.load_config(self.path, default=custom), custom)

    def test_save_config_is_indented_utf8(self):
        storage.save_config(self.path, {"rows": 16, "cols": 16, "mines": 40})
        with open(self.path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertIn("\n    ", text)

    def test_config_key(self):
        self.assertEqual(
            storage.config_key({"rows": 16, "cols": 16, "mines": 99}), "16_16_99"
        )


class ResultsTest(unittest.TestCase):
    def setUp(self):
        self._tmp = tempfile.TemporaryDirectory()
        self.addCleanup(self._tmp.cleanup)
        self.path = os.path.join(self._tmp.name, "results.json")
        self.record = {
            "state": 1,
            "time": "00:42",
            "currenttime": "2024-10-30 12:00:00",
            "cheat": 0,
        }

    def test_load_results_missing_file_is_empty(self):
        self.assertEqual(storage.load_results(self.path), {})

    def test_load_results_broken_file_is_empty(self):
        with open(self.path, "w", encoding="utf-8") as f:
            f.write("[[[")
        self.assertEqual(storage.load_results(self.path), {})

    def test_append_result_creates_group(self):
        data = storage.append_result(self.path, "9_9_10", self.record)
        self.assertEqual(data, {"9_9_10": [self.record]})
        with open(self.path, "r", encoding="utf-8") as f:
            self.assertEqual(json.load(f), {"9_9_10": [self.record]})

    def test_append_result_appends_to_existing_group(self):
        storage.append_result(self.path, "9_9_10", self.record)
        second = dict(self.record, state=0)
        data = storage.append_result(self.path, "9_9_10", second)
        self.assertEqual(len(data["9_9_10"]), 2)
        self.assertEqual(data["9_9_10"][1]["state"], 0)

    def test_append_result_keeps_legacy_compact_format(self):
        """旧版用 json.dump(data, f) 写回，results.json 是单行紧凑格式。"""
        storage.append_result(self.path, "9_9_10", self.record)
        with open(self.path, "r", encoding="utf-8") as f:
            text = f.read()
        self.assertNotIn("\n", text.strip())

    def test_append_result_creates_missing_directory(self):
        nested = os.path.join(self._tmp.name, "sub", "dir", "results.json")
        storage.append_result(nested, "9_9_10", self.record)
        self.assertTrue(os.path.isfile(nested))


if __name__ == "__main__":
    unittest.main()

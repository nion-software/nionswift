import json
import os
import unittest

from nion.swift.model import Utility

class TestUtilityClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def test_backwards_compatibility_for_short_versions(self):
        self.assertEqual(Utility.compare_versions("1", "1.0.0"), 0)
        self.assertEqual(Utility.compare_versions("1", "1.0.4"), 0)
        self.assertLess(Utility.compare_versions("1", "1.1.0"), 0)

    def test_compatible_version(self):
        self.assertEqual(Utility.compare_versions("~1.0", "1.0.0"), 0)
        self.assertGreater(Utility.compare_versions("~1.1", "1.0.0"), 0)
        self.assertEqual(Utility.compare_versions("~1.1", "1.1.0"), 0)
        self.assertEqual(Utility.compare_versions("~1.1", "1.1.4"), 0)
        self.assertLess(Utility.compare_versions("~1.1", "1.2.0"), 0)

    def test_incompatible_version(self):
        self.assertLess(Utility.compare_versions("~1.0", "2.0.0"), 0)
        self.assertGreater(Utility.compare_versions("~2.0", "1.0.0"), 0)

    def test_invalid_compatible_version(self):
        with self.assertRaises(Exception):
            Utility.compare_versions("~1", "1.0.0")

    def test_clean_dict_handles_none_in_tuples_and_lists(self):
        d0 = {"abc": (None, 2)}
        d1 = {"abc": (2, None)}
        d2 = {"abc": [None, 2]}
        d3 = {"abc": [2, None]}
        self.assertEqual(Utility.clean_dict(d0), d0)
        self.assertEqual(Utility.clean_dict(d1), d1)
        self.assertEqual(Utility.clean_dict(d2), d2)
        self.assertEqual(Utility.clean_dict(d3), d3)
        # ok for json to switch tuples to lists
        self.assertEqual(Utility.clean_dict(json.loads(json.dumps(d0))), d2)
        self.assertEqual(Utility.clean_dict(json.loads(json.dumps(d1))), d3)

    def test_simplify_filename(self):
        test_filenames = [("test.bmp", "test.bmp"),
                          (r"5/3/2024.txt", r"5_3_2024.txt"),
                          ("50µm.png", "50µm.png"),
                          ("1234567890" * 13 + ".1234567", "1234567890" * 12 + ".1234567"),
                          ("NUL", "_NUL"),
                          (".", "_"),
                          ("a\N{WARNING SIGN}b", "a\N{WARNING SIGN}b"),
                          ("\N{WARNING SIGN}", "\N{WARNING SIGN}"),
                          ("abc\n\rdef", "abc__def"),
                          ("a\tb", "a_b")]

        current_working_directory = os.getcwd()

        for test, expected in test_filenames:
            simplified = Utility.simplify_filename(test)
            self.assertEqual(simplified, expected)

            # also ensure we can successfully save files with the simplified names
            file_path = os.path.join(current_working_directory, simplified)

            try:
                with open(file_path, mode='a'):
                    pass
                self.assertTrue(os.path.exists(file_path))
            finally:
                os.remove(file_path)

    def test_verify_filename_has_no_illegal_characters(self):
        test_filenames = [("5>3>2024", "Contains illegal character '>'"),
                          ("abc\n\rdef\\", r"Contains illegal characters '\n' (New Line), '\r' (Carriage Return), '\'"),
                          ("\26", r"Contains illegal character '\x16'")]

        for test_input, expected in test_filenames:
            with self.subTest(test_input=test_input):
                is_valid, error = Utility.verify_filename_has_no_illegal_characters(test_input)
                self.assertFalse(is_valid)
                self.assertEqual(error, expected)


    def test_verify_filename_is_legal_catches_illegal_names(self) -> None:
        test_filenames = [("", "Cannot be empty"),
                          ("file.", "Cannot end with a period"),
                          ("file ", "Cannot end with a whitespace"),
                          ("COM¹", "\"COM¹\" is illegal as it is reserved on some platforms"),
                          ("1234567890" * 13, "Exceeds the allowed length of 128 characters"),
                          ("NUL", "\"NUL\" is illegal as it is reserved on some platforms")]

        for test_input, expected in test_filenames:
            with self.subTest(test_input=test_input):
                is_valid, errors = Utility.verify_filename_is_legal(test_input)
                self.assertFalse(is_valid)
                self.assertEqual(errors, [expected])

    def test_verify_filename_is_legal_returns_multiple_errors(self) -> None:
        multi_error_filenames = [("/file.", ["Cannot end with a period", r"Contains illegal character '/'"]),
                                 ("*>" + "1234567890" * 13, ["Exceeds the allowed length of 128 characters", r"Contains illegal characters '*', '>'"])]

        for test_input, expected in multi_error_filenames:
            with self.subTest(test_input=test_input):
                is_valid, errors = Utility.verify_filename_is_legal(test_input)
                self.assertFalse(is_valid)
                self.assertEqual(errors, expected)

    def test_verify_filename_is_legal_returns_true_for_valid_names(self) -> None:
        valid_filenames = ["file",
                           "file.name",
                           "1234567890" * 12,
                           "NUL123"]
        for test_input in valid_filenames:
            with self.subTest(test_input=test_input):
                is_valid, errors = Utility.verify_filename_is_legal(test_input)
                self.assertTrue(is_valid)
                self.assertEqual(errors, None)


if __name__ == '__main__':
    unittest.main()

import json
import os
import typing
import unittest
import zoneinfo

from nion.swift.model import Utility

class TestUtilityClass(unittest.TestCase):

    def setUp(self):
        self.__get_localzone = Utility.tzlocal.get_localzone

    def tearDown(self):
        Utility.tzlocal.get_localzone = self.__get_localzone

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
        test_filenames = [("5>3>2024", ["Contains illegal character(s) '>'"]),
                          ("abcdef\\", [r"Contains illegal character(s) '\'"]),
                          ("abcdef\n", [r"Contains non-printable character(s)"]),
                          ("\26", [r"Contains non-printable character(s)"])]

        for test_input, expected in test_filenames:
            with self.subTest(test_input=test_input):
                errors = Utility.get_filename_illegal_chars_error(test_input)
                self.assertEqual(errors, expected)

    def test_verify_filename_is_legal_catches_illegal_names(self) -> None:
        test_filenames = [("", "Cannot be empty"),
                          ("file.", "Cannot end with a period"),
                          ("COM¹", "\"COM¹\" is illegal as it is reserved on some platforms"),
                          ("1234567890" * 13, "Exceeds the allowed length of 128 characters"),
                          ("NUL", "\"NUL\" is illegal as it is reserved on some platforms")]

        for test_input, expected in test_filenames:
            with self.subTest(test_input=test_input):
                is_valid, errors = Utility.verify_filename_is_legal(test_input)
                self.assertFalse(is_valid)
                self.assertEqual(errors, [expected])

    def test_verify_filename_is_legal_returns_multiple_errors(self) -> None:
        multi_error_filenames = [("/file.", ["Cannot end with a period", r"Contains illegal character(s) '/'"]),
                                 ("*>" + "1234567890" * 13, ["Exceeds the allowed length of 128 characters", r"Contains illegal character(s) '*', '>'"])]

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

    def test_get_local_timezone_maps_windows_keys_unknown_to_tzlocal(self) -> None:
        # Windows 11 KB5124010 added time zone keys tzlocal does not know. see nionswift#1971.
        def raise_british_columbia() -> typing.NoReturn:
            raise zoneinfo.ZoneInfoNotFoundError("British Columbia Standard Time")

        def raise_alberta() -> typing.NoReturn:
            raise zoneinfo.ZoneInfoNotFoundError("Alberta Standard Time")

        Utility.tzlocal.get_localzone = raise_british_columbia
        self.assertEqual("America/Vancouver", Utility.get_local_timezone())
        Utility.tzlocal.get_localzone = raise_alberta
        self.assertEqual("America/Edmonton", Utility.get_local_timezone())

    def test_get_local_timezone_returns_none_when_undeterminable(self) -> None:
        def raise_unknown_zone() -> typing.NoReturn:
            raise zoneinfo.ZoneInfoNotFoundError("Some Unknown Zone")

        def raise_other_error() -> typing.NoReturn:
            raise RuntimeError("no time zone")

        Utility.tzlocal.get_localzone = raise_unknown_zone
        self.assertIsNone(Utility.get_local_timezone())
        Utility.tzlocal.get_localzone = raise_other_error
        self.assertIsNone(Utility.get_local_timezone())


if __name__ == '__main__':
    unittest.main()

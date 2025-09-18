# standard libraries
import json
import logging
import pathlib
import typing
import unittest

# local libraries
from nion.swift.test import TestContext


class TestApplicationClass(unittest.TestCase):

    def setUp(self) -> None:
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self) -> None:
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_changes_json_file(self) -> None:
        with TestContext.MemoryProfileContext() as profile_context:
            changes_json_path = pathlib.Path(__file__).parent.parent / "resources" / "changes.json"
            with changes_json_path.open() as changes_json_fp:
                changes_data: typing.Sequence[typing.Mapping[str, typing.Any]] = json.load(changes_json_fp)


if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()

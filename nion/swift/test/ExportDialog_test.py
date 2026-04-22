# standard libraries
import datetime
import pathlib
import typing
import unittest

# local libraries
from nion.swift import ExportDialog
from nion.swift.model import ImportExportManager
from nion.swift.test import TestContext


class TestExportDialog(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_model(self):
        model = ExportDialog.ExportDialogViewModel(
            title=True,
            date=False,
            dimensions=False,
            sequence=False,
            writer=None,
            prefix=None,
            directory=None)
        # initial case - no directory
        self.assertIsNotNone(model.directory_warning.value)
        self.assertFalse(model.export_button_enabled.value)
        self.assertIsNotNone(model.export_button_tool_tip.value)
        # directory case
        model.directory.value = str(pathlib.Path.cwd())
        self.assertFalse(model.directory_warning.value)
        self.assertTrue(model.export_button_enabled.value)
        self.assertFalse(model.export_button_tool_tip.value)
        # bad prefix case
        model.prefix.value = "bad/prefix"
        self.assertIsNotNone(model.directory_warning.value)
        self.assertFalse(model.export_button_enabled.value)
        self.assertIsNotNone(model.export_button_tool_tip.value)

    def test_filename(self) -> None:
        model = ExportDialog.ExportDialogViewModel(
            title=True,
            date=False,
            dimensions=False,
            sequence=False,
            writer=ImportExportManager.NDataImportExportHandler("ndata1-io-handler", "ndata", ["ndata"]),
            prefix=None,
            directory=str(pathlib.Path.cwd()))
        filepath = model.build_filepath(
            displayed_title="title",
            date=datetime.datetime.now(),
            dimensional_shape=(20, 20),
            index=1
        )
        self.assertEqual("title.ndata", filepath.name)


if __name__ == '__main__':
    unittest.main()

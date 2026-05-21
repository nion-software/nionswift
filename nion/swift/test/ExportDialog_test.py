# standard libraries
import datetime
import pathlib
import typing
import unittest
import numpy

# local libraries
from nion.swift import ExportDialog
from nion.swift.model import DataItem
from nion.swift.model import ImportExportManager
from nion.swift.test import TestContext
from nion.utils import Model


class TestExportDialog(unittest.TestCase):

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def test_model(self) -> None:
        model = ExportDialog.ExportDialogViewModel(
            title=True,
            date=False,
            dimensions=False,
            sequence=False,
            writer=None,
            prefix=None,
            directory=None)
        # initial case - no directory
        self.assertTrue(model.directory_warning.value)  # The warning and tool tip can be '' or None if the button is in an invalid state
        self.assertFalse(model.export_button_enabled.value)
        self.assertTrue(model.export_button_tool_tip.value)
        # directory case
        model.directory.value = str(pathlib.Path.cwd())
        self.assertFalse(model.directory_warning.value)
        self.assertTrue(model.export_button_enabled.value)
        self.assertFalse(model.export_button_tool_tip.value)
        # bad prefix case
        model.prefix.value = "bad/prefix"
        self.assertTrue(model.directory_warning.value)
        self.assertFalse(model.export_button_enabled.value)
        self.assertTrue(model.export_button_tool_tip.value)

    def test_model_updates_button_status_when_options_change(self) -> None:
        model = ExportDialog.ExportDialogViewModel(
            title=False,
            date=False,
            dimensions=False,
            sequence=False,
            writer=None,
            prefix=None,
            directory=str(pathlib.Path.cwd())  # The directory is valid for this test to isolate the error of no options
        )
        # Check the export button is disabled when all the options are disabled
        self.assertFalse(model.export_button_enabled.value)
        self.assertTrue(model.export_button_tool_tip.value)
        # Check the export button updates to be valid when an option is enabled
        model.include_date.value = True
        self.assertTrue(model.export_button_enabled.value)
        self.assertFalse(model.export_button_tool_tip.value)
        # Check the export button goes back to disabled when the value changes back
        model.include_date.value = False
        self.assertFalse(model.export_button_enabled.value)
        self.assertTrue(model.export_button_tool_tip.value)

    def test_model_updates_button_status_when_prefix_changes(self) -> None:
        """Test that the changes to the prefix string will update the button's validity."""
        model = ExportDialog.ExportDialogViewModel(
            title=False,
            date=False,
            dimensions=False,
            sequence=False,
            writer=None,
            prefix=None,
            directory=str(pathlib.Path.cwd())  # The directory is valid for this test to isolate the error of no options
        )
        # The export button starts disabled when all options are disabled
        self.assertFalse(model.export_button_enabled.value)
        self.assertTrue(model.export_button_tool_tip.value)
        # Now check that the button updates to enabled when the prefix is set
        model.prefix.value = "prefix"
        self.assertTrue(model.export_button_enabled.value)
        self.assertFalse(model.export_button_tool_tip.value)
        # Check that the button becomes invalid when the prefix becomes invalid
        model.prefix.value = ""
        self.assertFalse(model.export_button_enabled.value)
        self.assertTrue(model.export_button_tool_tip.value)

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

class TestExportSizeModel(unittest.TestCase):
    """Unit tests for ExportSizeModel unit swapping and aspect lock behavior."""

    def setUp(self):
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self):
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def _make_line_plot_model(self, test_context, unit_id: str = "pixels"):
        """Create a 1D (line plot) display item and an ExportSizeModel bound to it."""
        document_model = test_context.create_document_model()
        data_item = DataItem.DataItem(numpy.zeros((10,), numpy.float32))
        document_model.append_data_item(data_item)
        display_item = document_model.get_display_item_for_data_item(data_item)
        display_item.display_type = "line_plot"

        unit_model = Model.PropertyModel(unit_id)
        model = ExportDialog.ExportSizeModel(display_item, unit_model)

        return model, display_item, document_model

    def _get_unit_index(self, unit_description):
        return ExportDialog.svg_export_unit_descriptions.index(unit_description)

    def test_line_plot_initial_size_is_5x3_inches(self):
        """A 1D line plot should initialize to 5in x 3in (aspect 5:3)."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            expected_px_size = ExportDialog.calculate_display_size_in_pixels(display_item)
            self.assertEqual(model.pixel_shape.width, expected_px_size.width)
            self.assertEqual(model.pixel_shape.height, expected_px_size.height)
            # Switch to inches and verify we see 5:3
            model.unit_index = self._get_unit_index(ExportDialog.inch_unit_description)
            width_in = float(model.placeholder_width_text)
            height_in = float(model.placeholder_height_text)
            self.assertAlmostEqual(width_in, expected_px_size.width / ExportDialog.inch_unit_description.conversion_factor, places=6)
            self.assertAlmostEqual(height_in, expected_px_size.height / ExportDialog.inch_unit_description.conversion_factor, places=6)
            ar = expected_px_size.width / expected_px_size.height
            self.assertAlmostEqual(ar, 5.0 / 3.0, places=6)

    def test_locked_edit_width_updates_height(self):
        """With lock on and primary field width, H = W / AR."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            model.aspect_ratio_locked.value = True
            base_px = ExportDialog.calculate_display_size_in_pixels(display_item)
            ar = base_px.width / base_px.height
            model.width_text = "960"
            expected_h = round(960 / ar)
            self.assertEqual(model.pixel_shape.width, 960)
            self.assertEqual(model.pixel_shape.height, expected_h)

    def test_locked_edit_height_updates_width(self):
        """With lock on and primary field height, W = H * AR."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            model.aspect_ratio_locked.value = True
            base_px = ExportDialog.calculate_display_size_in_pixels(display_item)
            ar = base_px.width / base_px.height
            model.height_text = "600"
            expected_w = round(600 * ar)
            self.assertEqual(model.pixel_shape.height, 600)
            self.assertEqual(model.pixel_shape.width, expected_w)

    def test_unlock_breaks_link_between_width_and_height(self):
        """With lock off, editing width does not change height """
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")

            # Start from a known size with lock on
            model.aspect_ratio_locked.value = True
            model.width_text = "480"
            h_before = model.pixel_shape.height

            # Unlock and change width
            model.aspect_ratio_locked.value = False
            model.width_text = "700"
            self.assertEqual(model.pixel_shape.width, 700)
            self.assertEqual(model.pixel_shape.height, h_before)  # unchanged

            # Change height now check if width remains unchanged when unlocked
            model.height_text = "350"
            self.assertEqual(model.pixel_shape.width, 700)
            self.assertEqual(model.pixel_shape.height, 350)

    def test_unit_switch_preserves_pixel_shape(self):
        """Changing units converts numbers but keeps the same pixel dimensions."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            model.aspect_ratio_locked.value = True

            base_px = model.pixel_shape
            # Switch to inches
            model.unit_index = self._get_unit_index(ExportDialog.inch_unit_description)
            self.assertEqual(model.pixel_shape.width, base_px.width)
            self.assertEqual(model.pixel_shape.height, base_px.height)

            # Switch to cm
            model.unit_index = self._get_unit_index(ExportDialog.centimeter_unit_description)
            self.assertEqual(model.pixel_shape.width, base_px.width)
            self.assertEqual(model.pixel_shape.height, base_px.height)

            # Switch back to pixels
            model.unit_index = self._get_unit_index(ExportDialog.pixel_unit_description)
            self.assertEqual(model.pixel_shape.width, base_px.width)
            self.assertEqual(model.pixel_shape.height, base_px.height)

    def test_locked_edit_in_inches_updates_pixels_consistently(self):
        """Editing in inches updates pixel_shape via unit conversion and AR."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            model.aspect_ratio_locked.value = True
            model.unit_index = self._get_unit_index(ExportDialog.inch_unit_description)
            # Set width to 6 inches; with AR=5/3 => height 3.6 in (placeholders show derived values)
            model.width_text = "6"
            self.assertAlmostEqual(float(model.placeholder_height_text), 3.6, places=6)

            # pixel_shape rounds to nearest pixel
            expected_w_px = round(6.0 * ExportDialog.inch_unit_description.conversion_factor)
            expected_h_px = round(3.6 * ExportDialog.inch_unit_description.conversion_factor)
            self.assertEqual(model.pixel_shape.width, expected_w_px)
            self.assertEqual(model.pixel_shape.height, expected_h_px)

    def test_switch_to_centimeters_shows_expected_values(self):
        """Switching to centimeters should show the cm equivalents of the default 5x3 inch plot."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            # Switch to cm and read the placeholders
            model.unit_index = self._get_unit_index(ExportDialog.centimeter_unit_description)

            px_size = ExportDialog.calculate_display_size_in_pixels(display_item)
            expected_w_cm = px_size.width / ExportDialog.centimeter_unit_description.conversion_factor
            expected_h_cm = px_size.height / ExportDialog.centimeter_unit_description.conversion_factor

            self.assertAlmostEqual(float(model.placeholder_width_text), expected_w_cm, places=6)
            self.assertAlmostEqual(float(model.placeholder_height_text), expected_h_cm, places=6)

    def test_relock_snaps_to_aspect_ratio_using_width_as_primary(self):
        """When unlocked and user last edits WIDTH, re-lock snaps H = W / AR."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            base_px = ExportDialog.calculate_display_size_in_pixels(display_item)
            ar = base_px.width / base_px.height
            model.aspect_ratio_locked.value = False
            model.width_text = "700"  # non-AR
            # Currently not at aspect ratio
            self.assertEqual(model.pixel_shape.width, 700)
            self.assertNotEqual(round(model.pixel_shape.width / ar), model.pixel_shape.height)
            # Simulate checkbox
            model.aspect_ratio_locked.value = True
            model.snap_dimensions_to_aspect_ratio()
            # Expect height snapped to W/AR while width preserved
            expected_h = round(700 / ar)
            self.assertEqual(model.pixel_shape.width, 700)
            self.assertEqual(model.pixel_shape.height, expected_h)

    def test_relock_snaps_to_aspect_ratio_using_height_as_primary(self):
        """When unlocked and user last edits HEIGHT, re-lock snaps W = H * AR."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            base_px = ExportDialog.calculate_display_size_in_pixels(display_item)
            ar = base_px.width / base_px.height
            model.aspect_ratio_locked.value = False
            model.height_text = "350"  # non-AR
            # Currently not at aspect ratio
            self.assertEqual(model.pixel_shape.height, 350)
            self.assertNotEqual(round(350 * ar), model.pixel_shape.width)
            # Simulate checkbox
            model.aspect_ratio_locked.value = True
            model.snap_dimensions_to_aspect_ratio()
            # Expect width snapped to H*AR while height preserved
            expected_w = round(350 * ar)
            self.assertEqual(model.pixel_shape.height, 350)
            self.assertEqual(model.pixel_shape.width, expected_w)

    def test_aspect_ratio_locked_focus_change_does_not_zero_dimensions(self):
        with TestContext.create_memory_context() as test_context:
            model = self._make_line_plot_model(test_context, unit_id="pixels")[0]
            # Force non-zero size
            original_width = model.pixel_shape.width
            original_height = model.pixel_shape.height
            self.assertGreater(original_width, 0)
            self.assertGreater(original_height, 0)
            model.set_aspect_ratio_mode("16:9")
            self.assertTrue(model.aspect_ratio_locked.value)
            # Simulate focus change with empty string
            model.height_text = ""
            model.width_text = ""
            pixel_shape = model.pixel_shape
            self.assertEqual(pixel_shape.width, original_width)
            self.assertEqual(pixel_shape.height, original_width*9/16)

    def test_primary_field_only_changes_on_valid_edit(self):
        with TestContext.create_memory_context() as test_context:
            model = self._make_line_plot_model(test_context)[0]
            model.set_aspect_ratio_mode("16:9")
            initial_shape = model.pixel_shape
            # Empty edit must not change anything
            model.width_text = ""
            self.assertEqual(model.pixel_shape, initial_shape)
            # Valid edit should update and propagate
            model.width_text = "300"
            updated_shape = model.pixel_shape
            self.assertEqual(updated_shape.width, 300)
            self.assertGreater(updated_shape.height, 0)
            self.assertEqual(updated_shape.height, round(300 * 9 / 16))


if __name__ == '__main__':
    unittest.main()

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
from nion.ui import TestUI
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
        # The warning and tooltip can be '' or None when the button is in a valid state
        # So we check the truthiness of the values when the state is expected to be invalid, to confirm a warning and tooltip are present
        self.assertTrue(model.directory_warning.value)
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
        """Test that when no options are selected the export button is disabled, and that when an option is selected the export button becomes enabled."""
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

    def test_locked_edit_updates_opposite_dimension(self):
        """With lock on, editing either primary field recomputes the other via the aspect ratio."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            model.aspect_ratio_locked.value = True
            base_px = ExportDialog.calculate_display_size_in_pixels(display_item)
            ar = base_px.width / base_px.height
            with self.subTest(primary="width"):
                model.width_text = "960"
                self.assertEqual(model.pixel_shape.width, 960)
                self.assertEqual(model.pixel_shape.height, round(960 / ar))
            with self.subTest(primary="height"):
                model.height_text = "600"
                self.assertEqual(model.pixel_shape.height, 600)
                self.assertEqual(model.pixel_shape.width, round(600 * ar))

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

    def test_relock_snaps_to_aspect_ratio_using_last_edited_field_as_primary(self):
        """When unlocked and the user last edits a field, re-locking snaps the *other* field to match
        the aspect ratio, whichever field (width or height) was edited last."""
        for primary in ("width", "height"):
            with self.subTest(primary=primary):
                with TestContext.create_memory_context() as test_context:
                    model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
                    base_px = ExportDialog.calculate_display_size_in_pixels(display_item)
                    ar = base_px.width / base_px.height
                    model.aspect_ratio_locked.value = False
                    if primary == "width":
                        model.width_text = "700"  # non-AR
                        self.assertEqual(model.pixel_shape.width, 700)
                        self.assertNotEqual(round(model.pixel_shape.width / ar), model.pixel_shape.height)
                    else:
                        model.height_text = "350"  # non-AR
                        self.assertEqual(model.pixel_shape.height, 350)
                        self.assertNotEqual(round(350 * ar), model.pixel_shape.width)
                    # Simulate checkbox
                    model.aspect_ratio_locked.value = True
                    model.snap_dimensions_to_aspect_ratio()
                    if primary == "width":
                        # Expect height snapped to W/AR while width preserved
                        self.assertEqual(model.pixel_shape.width, 700)
                        self.assertEqual(model.pixel_shape.height, round(700 / ar))
                    else:
                        # Expect width snapped to H*AR while height preserved
                        self.assertEqual(model.pixel_shape.height, 350)
                        self.assertEqual(model.pixel_shape.width, round(350 * ar))


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

    def test_set_ppi_does_not_affect_pixel_unit(self):
        """A size specified in Pixels must be unaffected by ppi changes."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            model.width_text = "800"
            model.aspect_ratio_locked.value = False
            model.height_text = "600"
            before_shape = model.pixel_shape
            before_width_text = model.width_text
            model.set_ppi(300)
            self.assertEqual(model.pixel_shape.width, before_shape.width)
            self.assertEqual(model.pixel_shape.height, before_shape.height)
            self.assertEqual(model.width_text, before_width_text)

    def test_set_ppi_scales_physical_units_pixel_shape_and_preserves_displayed_value(self):
        """Changing ppi while unit is Inches or Centimeters scales pixel_shape by the unit's ppi-based
        conversion factor, while the displayed value (in that physical unit) stays unchanged."""
        cases = (
            (ExportDialog.inch_unit_description, 4, 3, 96.0, 300.0),
            (ExportDialog.centimeter_unit_description, 10, 5, 96.0 / 2.54, 300.0 / 2.54),
        )
        for unit_description, width, height, factor_before, factor_after in cases:
            with self.subTest(unit=unit_description.unit_id):
                with TestContext.create_memory_context() as test_context:
                    model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
                    model.unit_index = self._get_unit_index(unit_description)
                    model.aspect_ratio_locked.value = False
                    model.width_text = str(width)
                    model.height_text = str(height)
                    self.assertEqual(model.pixel_shape.width, round(width * factor_before))
                    self.assertEqual(model.pixel_shape.height, round(height * factor_before))
                    model.set_ppi(300)
                    self.assertEqual(model.width_text, str(width))
                    self.assertEqual(model.height_text, str(height))
                    self.assertEqual(model.pixel_shape.width, round(width * factor_after))
                    self.assertEqual(model.pixel_shape.height, round(height * factor_after))

    def test_unit_switch_after_ppi_change_round_trips(self):
        """Switching units after a ppi change should still round-trip pixel_shape correctly."""
        with TestContext.create_memory_context() as test_context:
            model, display_item, _ = self._make_line_plot_model(test_context, unit_id="pixels")
            model.aspect_ratio_locked.value = True
            model.set_ppi(300)
            base_px = model.pixel_shape
            model.unit_index = self._get_unit_index(ExportDialog.inch_unit_description)
            self.assertEqual(model.pixel_shape.width, base_px.width)
            self.assertEqual(model.pixel_shape.height, base_px.height)
            model.unit_index = self._get_unit_index(ExportDialog.centimeter_unit_description)
            self.assertEqual(model.pixel_shape.width, base_px.width)
            self.assertEqual(model.pixel_shape.height, base_px.height)
            model.unit_index = self._get_unit_index(ExportDialog.pixel_unit_description)
            self.assertEqual(model.pixel_shape.width, base_px.width)
            self.assertEqual(model.pixel_shape.height, base_px.height)


class TestExportFormatModel(unittest.TestCase):
    """Unit tests for ExportFormatModel, isolated from ExportSizeModel."""

    class _PersistingUserInterface(TestUI.UserInterface):
        """A TestUI.UserInterface whose persistent-string storage actually persists.

        TestUI's built-in get/set_persistent_string are no-ops (by design, for test isolation), so
        this subclass backs them with an in-memory dict to exercise the persistence round-trip
        behavior of UserInterface.StringPersistentModel/FloatPersistentModel.
        """

        def __init__(self) -> None:
            super().__init__()
            self.__persisted: dict[str, str] = {}

        def get_persistent_string(self, key: str, default_value: str | None = None) -> str:
            return self.__persisted.get(key, super().get_persistent_string(key, default_value))

        def set_persistent_string(self, key: str, value: str) -> None:
            self.__persisted[key] = value

    def _make_persisting_ui(self) -> TestUI.UserInterface:
        return TestExportFormatModel._PersistingUserInterface()

    def test_defaults(self) -> None:
        ui = TestUI.UserInterface()
        model = ExportDialog.ExportFormatModel(ui)
        self.assertEqual(model.export_category, "svg")
        self.assertTrue(model.is_svg)
        self.assertFalse(model.is_bitmap)
        self.assertEqual(model.bitmap_format, "png")
        self.assertEqual(model.ppi, 96)
        self.assertEqual(model.effective_ppi, 96)

    def test_switching_category_persists_and_round_trips(self) -> None:
        ui = self._make_persisting_ui()
        model = ExportDialog.ExportFormatModel(ui)
        model.export_category = "bitmap"
        self.assertTrue(model.is_bitmap)
        self.assertFalse(model.is_svg)
        # a new model instance backed by the same (persisting) ui should see the persisted value
        model2 = ExportDialog.ExportFormatModel(ui)
        self.assertEqual(model2.export_category, "bitmap")

    def test_switching_bitmap_format_persists(self) -> None:
        ui = self._make_persisting_ui()
        model = ExportDialog.ExportFormatModel(ui)
        model.bitmap_format = "jpeg"
        self.assertEqual(model.bitmap_format, "jpeg")
        self.assertEqual(model.bitmap_format_extension, "jpg")
        model2 = ExportDialog.ExportFormatModel(ui)
        self.assertEqual(model2.bitmap_format, "jpeg")

    def test_ppi_preset_selection(self) -> None:
        ui = TestUI.UserInterface()
        model = ExportDialog.ExportFormatModel(ui)
        model.ppi_index = ExportDialog.ExportFormatModel.ppi_presets.index(300)
        self.assertEqual(model.ppi, 300)
        self.assertFalse(model.is_custom_ppi)
        self.assertEqual(model.ppi_text, "300")

    def test_ppi_custom_freeform_entry(self) -> None:
        ui = TestUI.UserInterface()
        model = ExportDialog.ExportFormatModel(ui)
        model.ppi_text = "133"
        self.assertEqual(model.ppi, 133)
        self.assertTrue(model.is_custom_ppi)
        self.assertEqual(model.ppi_index, len(ExportDialog.ExportFormatModel.ppi_presets))

    def test_custom_ppi_index_selection_round_trips_with_presets(self) -> None:
        """Regression test: selecting "Custom" in the PPI combo box must reveal the custom-entry
        field even when the current ppi value (e.g. the default 96) already equals a preset -- the
        underlying ppi value doesn't change just by selecting "Custom", only by then typing into the
        custom field, so is_custom_ppi must not be derived purely from "ppi not in presets". Re-selecting
        a preset afterward must clear that custom state again."""
        ui = TestUI.UserInterface()
        model = ExportDialog.ExportFormatModel(ui)
        self.assertEqual(model.ppi, 96)  # default, a preset value
        self.assertFalse(model.is_custom_ppi)
        model.ppi_index = len(ExportDialog.ExportFormatModel.ppi_presets)  # select "Custom"
        self.assertTrue(model.is_custom_ppi)
        self.assertEqual(model.ppi, 96)  # unchanged until the user types a new value
        self.assertEqual(model.ppi_index, len(ExportDialog.ExportFormatModel.ppi_presets))
        # re-select the preset that already matches the current (unchanged) ppi value
        model.ppi_index = ExportDialog.ExportFormatModel.ppi_presets.index(96)
        self.assertFalse(model.is_custom_ppi)
        self.assertEqual(model.ppi_index, ExportDialog.ExportFormatModel.ppi_presets.index(96))

    def test_ppi_persists_across_model_instances(self) -> None:
        ui = self._make_persisting_ui()
        model = ExportDialog.ExportFormatModel(ui)
        model.ppi = 150
        model2 = ExportDialog.ExportFormatModel(ui)
        self.assertEqual(model2.ppi, 150)

    def test_effective_ppi_is_fixed_96_for_svg_and_follows_ppi_for_bitmap(self) -> None:
        ui = TestUI.UserInterface()
        model = ExportDialog.ExportFormatModel(ui)
        model.ppi = 300
        self.assertEqual(model.export_category, "svg")
        self.assertEqual(model.effective_ppi, 96)
        model.export_category = "bitmap"
        self.assertEqual(model.effective_ppi, 300)


class TestExportDisplayHandler(unittest.TestCase):
    """Tests for the ppi-sync glue wiring between ExportFormatModel and ExportSizeModel."""

    def setUp(self) -> None:
        TestContext.begin_leaks()
        self._test_setup = TestContext.TestSetup()

    def tearDown(self) -> None:
        self._test_setup = typing.cast(typing.Any, None)
        TestContext.end_leaks(self)

    def _make_handler(self, initial_size_model_ppi: int | None = None) -> tuple[ExportDialog.ExportFormatModel, ExportDialog.ExportSizeModel, ExportDialog.ExportDisplayHandler]:
        with TestContext.create_memory_context() as test_context:
            document_controller = test_context.create_document_controller()
            document_model = document_controller.document_model
            data_item = DataItem.DataItem(numpy.zeros((8, 8), numpy.float32))
            document_model.append_data_item(data_item)
            display_item = document_model.get_display_item_for_data_item(data_item)
            ui = TestUI.UserInterface()
            format_model = ExportDialog.ExportFormatModel(ui)
            units_model = Model.PropertyModel(ExportDialog.pixel_unit_description.unit_id)
            if initial_size_model_ppi is None:
                initial_size_model_ppi = format_model.effective_ppi
            size_model = ExportDialog.ExportSizeModel(display_item, units_model, initial_size_model_ppi)
            handler = ExportDialog.ExportDisplayHandler(size_model, format_model, ui.get_font_metrics)
            return format_model, size_model, handler

    def test_size_model_ppi_starts_synced_at_construction(self) -> None:
        # construct size_model with a ppi that deliberately mismatches format_model.effective_ppi (96),
        # so this test actually proves the handler applies effective_ppi during __init__, rather than
        # merely observing a value the test itself supplied to the constructor.
        format_model, size_model, handler = self._make_handler(initial_size_model_ppi=300)
        self.assertEqual(size_model.ppi, 96)
        handler.close()

    def test_size_model_ppi_follows_format_model_ppi_when_bitmap(self) -> None:
        format_model, size_model, handler = self._make_handler()
        size_model.unit_index = 1  # inches; ppi only has an effect for physical units
        format_model.export_category = "bitmap"
        self.assertEqual(size_model.ppi, 96)  # default bitmap ppi is 96
        format_model.ppi = 300
        self.assertEqual(size_model.ppi, 300)
        handler.close()

    def test_size_model_ppi_reverts_to_96_when_switched_back_to_svg(self) -> None:
        format_model, size_model, handler = self._make_handler()
        size_model.unit_index = 1  # inches; ppi only has an effect for physical units
        format_model.export_category = "bitmap"
        format_model.ppi = 300
        self.assertEqual(size_model.ppi, 300)
        format_model.export_category = "svg"
        self.assertEqual(size_model.ppi, 96)
        handler.close()

    def test_size_model_ppi_stays_96_for_bitmap_with_pixel_unit(self) -> None:
        """Regression test: effective_ppi must stay fixed at 96 while the size unit is Pixels, even if
        the user previously chose a non-96 ppi while a physical unit was selected -- otherwise a stale
        ppi would silently affect font/line rendering and get embedded as misleading DPI metadata for a
        pixel-exact export where no physical size was specified."""
        format_model, size_model, handler = self._make_handler()
        format_model.export_category = "bitmap"
        format_model.ppi = 300
        self.assertTrue(size_model.is_pixel_unit)
        self.assertEqual(size_model.ppi, 96)
        self.assertEqual(handler.effective_ppi, 96)
        handler.close()

    def test_closing_handler_stops_sync(self) -> None:
        format_model, size_model, handler = self._make_handler()
        handler.close()
        format_model.export_category = "bitmap"
        format_model.ppi = 300
        # no more listener attached, so size_model should remain at its last-applied value (96.0)
        self.assertEqual(size_model.ppi, 96)

    def test_ppi_controls_visibility_transitions(self) -> None:
        """The PPI controls should only be shown when exporting a bitmap with a physical (non-pixel)
        size unit -- PPI has no effect on the output when the unit is Pixels (an exact pixel count has
        already been specified), so the controls stay hidden in that case, and always hidden for SVG.
        """
        format_model, size_model, handler = self._make_handler()
        self.assertFalse(handler.show_ppi_controls)  # svg
        format_model.export_category = "bitmap"
        self.assertTrue(size_model.is_pixel_unit)
        self.assertFalse(handler.show_ppi_controls)  # bitmap, but pixels
        size_model.unit_index = 1  # switch to inches
        self.assertTrue(handler.show_ppi_controls)  # bitmap, physical unit
        size_model.unit_index = 0  # switch back to pixels
        self.assertFalse(handler.show_ppi_controls)
        handler.close()

    def test_custom_ppi_controls_hide_when_pixel_unit_overrides_custom_ppi(self) -> None:
        """show_custom_ppi_controls must respect show_ppi_controls even when is_custom_ppi is True --
        e.g. a custom (non-preset) ppi is set while the unit is Pixels, where ppi controls are hidden."""
        format_model, size_model, handler = self._make_handler()
        size_model.unit_index = 1  # inches
        format_model.export_category = "bitmap"
        format_model.ppi = 133  # not a preset
        self.assertTrue(handler.show_custom_ppi_controls)
        size_model.unit_index = 0  # switch to pixels; custom ppi controls should hide regardless
        self.assertFalse(handler.show_custom_ppi_controls)
        handler.close()

    def test_custom_ppi_controls_enable_via_combo_selection_even_at_default_preset_ppi(self) -> None:
        """Regression test for the reported bug: choosing "Custom" from the PPI combo box must
        enable the custom-entry field immediately, even before the user types a new value (i.e. while
        ppi still equals a preset like the default 96)."""
        format_model, size_model, handler = self._make_handler()
        size_model.unit_index = 1  # inches
        format_model.export_category = "bitmap"
        self.assertFalse(handler.show_custom_ppi_controls)
        format_model.ppi_index = len(format_model.ppi_presets)  # select "Custom" in the combo box
        self.assertTrue(handler.show_custom_ppi_controls)
        handler.close()




if __name__ == '__main__':
    unittest.main()

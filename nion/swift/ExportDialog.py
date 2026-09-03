from __future__ import annotations

# standard libraries
import dataclasses
import datetime
import gettext
import logging
import os
import pathlib
import platform
import re
import subprocess
import traceback
import typing
import unicodedata

# third party libraries
# None

# local libraries
from nion.data import DataAndMetadata
from nion.swift.model import ImportExportManager
from nion.swift.model import Utility
from nion.swift import DocumentController
from nion.swift import DisplayPanel
from nion.ui import Declarative
from nion.ui import Dialog
from nion.ui import UserInterface
from nion.utils import Converter
from nion.utils import Geometry
from nion.utils import Model
from nion.utils import Observable
from nion.utils import Stream

if typing.TYPE_CHECKING:
    from nion.swift.model import DisplayItem

_ = gettext.gettext


@dataclasses.dataclass(frozen=True)
class ExportOptionsValidity:
    """Contains the  export validity result of compute_export_options_validity."""
    is_directory_valid: bool  # Is the directory a valid path
    invalid_reasons: tuple[str, ...]  # Reasons the export options are not valid


class ExportDialogViewModel:
    """Represents the export dialog model."""

    def __init__(self, title: bool, date: bool, dimensions: bool, sequence: bool, writer: ImportExportManager.ImportExportHandler | None, prefix: str | None, directory: str | None) -> None:
        self.include_title = Model.PropertyModel(title)
        self.include_date = Model.PropertyModel(date)
        self.include_dimensions = Model.PropertyModel(dimensions)
        self.include_sequence = Model.PropertyModel(sequence)
        self.prefix = Model.PropertyModel[str](prefix)
        self.directory = Model.PropertyModel(directory)
        self.directory_warning = Model.PropertyModel(str())
        self.export_button_enabled = Model.PropertyModel(False)
        self.export_button_tool_tip = Model.PropertyModel(str())
        self.writer = Model.PropertyModel(writer)

        directory_stream = Stream.PropertyChangedEventStream[str](self.directory, "value")

        def validate_directory(directory: str | None) -> bool:
            return directory is not None and pathlib.Path(directory).is_dir()

        self.__is_directory_valid = Model.StreamValueModel(Stream.MapStream(directory_stream, validate_directory))

        if not self.is_directory_valid:
            self.directory.value = None  # Clear the initial directory if it was invalid

        export_filename_option_streams: typing.Sequence[Stream.PropertyChangedEventStream[str | bool]] = [
            # Update the button when one of the options changes
            Stream.PropertyChangedEventStream(self.prefix, "value"),
            Stream.PropertyChangedEventStream(self.include_title, "value"),
            Stream.PropertyChangedEventStream(self.include_date, "value"),
            Stream.PropertyChangedEventStream(self.include_dimensions, "value"),
            Stream.PropertyChangedEventStream(self.include_sequence, "value"),
            # Also update the button when the directory changes validity
            Stream.PropertyChangedEventStream(self.__is_directory_valid, "value")
        ]

        self.__export_button_update_action = Stream.ValueStreamAction(
            Stream.CombineLatestStream(export_filename_option_streams, ExportDialogViewModel.compute_export_options_validity),
            self.__handle_export_options_validity_changed
        )
        self.update_options()

    @staticmethod
    def compute_export_options_validity(prefix_value: str | None, include_title: bool | None,
                                        include_date: bool | None, include_dimensions: bool | None,
                                        include_sequence: bool | None, is_directory_valid: bool | None) -> ExportOptionsValidity:
        """Use the combined values of the export filename options and the directory validity to get a list of invalid reasons."""
        invalid_reasons: list[str] = []

        prefix_str = prefix_value or str()
        prefix_enabled = bool(prefix_str)
        non_prefix_options_enabled = include_title or include_date or include_dimensions or include_sequence
        if prefix_enabled and non_prefix_options_enabled:
            # The prefix will only be part of the filename so only check that it is made up of valid characters
            errors = Utility.get_filename_illegal_chars_error(prefix_str)
            if errors is not None:
                invalid_reasons.append(_("Prefix was invalid:"))
                invalid_reasons.extend(errors)
        elif prefix_enabled and not non_prefix_options_enabled:
            # The prefix is the full filename so check it is allowed using the verify filename utility
            is_valid, errors = Utility.verify_filename_is_legal(prefix_str)
            if not is_valid and errors is not None:
                invalid_reasons.append(_("Prefix was not a valid filename:"))
                invalid_reasons.extend(errors)
        elif not prefix_enabled and not non_prefix_options_enabled:
            # There must be at least one option enabled otherwise the filenames will be empty
            invalid_reasons.append(_("Filename requires at least one option to be selected"))

        if not is_directory_valid:
            invalid_reasons.append(_("Directory does not exist"))

        return ExportOptionsValidity(bool(is_directory_valid), tuple(invalid_reasons))

    def __handle_export_options_validity_changed(self, export_validity: ExportOptionsValidity | None) -> None:
        """Update the export button's enabled state and tooltip based on the computed invalid reasons and directory validity."""
        export_validity = export_validity or ExportOptionsValidity(False, tuple())
        if not export_validity.is_directory_valid:
            self.directory.value = None  # Clear the directory if it is invalid

        if export_validity.invalid_reasons:
            self.export_button_enabled.value = False
            self.export_button_tool_tip.value = ", ".join(export_validity.invalid_reasons)
            self.directory_warning.value = "\n".join(export_validity.invalid_reasons)
        else:
            self.export_button_enabled.value = True
            self.export_button_tool_tip.value = None
            self.directory_warning.value = str()

    def update_options(self, prefix_value: str | None = None) -> None:
        """Directly refresh the validity of the export button's enabled state and tooltip."""
        export_options_validity = ExportDialogViewModel.compute_export_options_validity(
            prefix_value or self.prefix.value, self.include_title.value, self.include_date.value,
            self.include_dimensions.value, self.include_sequence.value, self.__is_directory_valid.value
        )
        self.__handle_export_options_validity_changed(export_options_validity)

    @property
    def directory_path_object(self) -> pathlib.Path:
        return pathlib.Path(self.directory.value or str())

    @property
    def is_directory_valid(self) -> bool:
        self.__is_directory_valid.value = self.directory.value is not None and pathlib.Path(self.directory.value).is_dir()
        return self.__is_directory_valid.value or False

    def build_filepath(self, displayed_title: str, date: datetime.datetime, dimensional_shape: DataAndMetadata.ShapeType | None, index: int) -> pathlib.Path:
        filename_components = list()

        if self.prefix.value is not None and self.prefix.value != '':
            filename_components.append(str(self.prefix.value))
        if self.include_title.value:
            title = unicodedata.normalize('NFKC', displayed_title)
            title = re.sub(r'[^\w\s-]', '', title, flags=re.U).strip()
            title = re.sub(r'[-\s]+', '-', title, flags=re.U)
            filename_components.append(title)
        if self.include_date.value:
            filename_components.append(date.isoformat().replace(':', '').replace('.', '_'))
        if self.include_dimensions.value and dimensional_shape:
            filename_components.append("x".join([str(shape_n) for shape_n in dimensional_shape]))
        if self.include_sequence.value:
            filename_components.append(str(index))

        directory_path = self.directory_path_object
        assert directory_path.is_dir()

        writer = self.writer.value
        assert writer is not None
        extension = writer.extensions[0]
        # if extension doesn't start with a '.', add one, so we always know it is there
        if not extension.startswith('.'):
            extension = '.' + extension

        # stick filename_components together for the first part of the filename, underscore delimited excluding blank component
        filename = "_".join(s for s in filename_components if s)
        filename = filename.replace(".", "_")
        filename = Utility.simplify_filename(str(pathlib.Path(filename).with_suffix(extension)))

        # check to see if filename is available, if so return that
        test_filepath = directory_path / pathlib.Path(filename)
        if not test_filepath.exists():
            return test_filepath

        # file must already exist
        next_index = 1
        max_index = 9999
        last_test_filepath: pathlib.Path | None = None
        while next_index <= max_index:
            filename_stem = pathlib.Path(filename).stem
            test_filepath = directory_path / pathlib.Path(f"{filename_stem} {next_index}").with_suffix(extension)
            if not test_filepath.exists():
                return test_filepath
            if test_filepath == last_test_filepath:
                break
            last_test_filepath = test_filepath  # in case we have a bug
            next_index = next_index + 1

        # We have no option here but to just overwrite, either we ran out of index options or had none to begin with
        print(f"Warning: Overwriting file {test_filepath}")
        return test_filepath


class ExportDialog(Declarative.Handler):

    def __init__(self, ui: UserInterface.UserInterface, document_controller: DocumentController.DocumentController, display_items: typing.Sequence[DisplayItem.DisplayItem]):
        super().__init__()

        self.ui = ui
        self.__document_controller = document_controller

        # configure the writers. ensure that the writer is set to the last used writer or the first writer if no last used.
        self.__writers = ImportExportManager.ImportExportManager().get_writers()
        io_handler_id = self.ui.get_persistent_string("export_io_handler_id", "png-io-handler")
        writer = ImportExportManager.ImportExportManager().get_writer_by_id(io_handler_id) or self.__writers[0]
        self.writer_index = self.__writers.index(writer)

        # set up directory needed for the viewmodel
        directory = self.ui.get_persistent_string("export_directory", self.ui.get_document_location())

        # the viewmodel is the data model for the dialog. no other variables are needed.
        self.viewmodel = ExportDialogViewModel(True, True, True, True, writer, None, directory)

        # build the UI
        u = Declarative.DeclarativeUI()
        self.__build_ui(u)

        # perform export, but save the last used writer
        def handle_export_clicked() -> bool:
            if not self.viewmodel.is_directory_valid:
                return False
            selected_writer = self.viewmodel.writer.value
            writer_id = selected_writer.io_handler_id if selected_writer else "png-io-handler"
            self.export_clicked(display_items, self.viewmodel, ui, document_controller)
            self.ui.set_persistent_string("export_io_handler_id", writer_id)
            return True

        # create the dialog and show it.
        export_text = _("Export")
        items_text = _("Items") if len(display_items) != 1 else _("Item")
        title_text = f"{export_text} ({len(display_items)} {items_text})"
        dialog = typing.cast(Dialog.ActionDialog, Declarative.construct(document_controller.ui, document_controller, u.create_modeless_dialog(self.ui_view, title=title_text), self))
        dialog.add_button(_("Cancel"), self.cancel)
        self.__export_button = dialog.add_button(_("Export"), handle_export_clicked)
        dialog.show()

        # manually update export button since it is not part of the declarative setup
        # the logic is still in the model.
        def update_export_button(__: typing.Any) -> None:
            self.__export_button.enabled = self.viewmodel.export_button_enabled.value or False
            self.__export_button.tool_tip = self.viewmodel.export_button_tool_tip.value or str()

        self.__export_button_enabled_action = Stream.ValueStreamAction(Stream.PropertyChangedEventStream(self.viewmodel.export_button_enabled, "value"), update_export_button)
        self.__export_button_tool_tip_action = Stream.ValueStreamAction(Stream.PropertyChangedEventStream(self.viewmodel.export_button_tool_tip, "value"), update_export_button)

        # initialize the export button state
        update_export_button(None)

    def choose_directory(self, widget: Declarative.UIWidget) -> None:
        directory = self.viewmodel.directory.value or str()
        selected_directory, directory = self.ui.get_existing_directory_dialog(_("Choose Export Directory"), directory)
        if selected_directory:
            self.viewmodel.directory.value = selected_directory
            self.ui.set_persistent_string("export_directory", selected_directory)

    def _handle_writer_changed(self, widget: Declarative.UIWidget, current_index: int) -> None:
        writer = self.__writers[current_index]
        self.viewmodel.writer.value = writer

    def handle_prefix_edited(self, widget: UserInterface.LineEditWidget, text: str) -> None:
        self.viewmodel.update_options(text)

    def __build_ui(self, u: Declarative.DeclarativeUI) -> None:
        """Build the UI and store it in self.ui_view. This is called from __init__."""

        writers_names = [getattr(writer, "name") for writer in self.__writers]

        # Export Folder
        directory_label = u.create_row(u.create_label(text="Location:", font='bold'))
        directory_text = u.create_row(u.create_column(
            u.create_label(text="@binding(viewmodel.directory.value)", min_width=280, height=48, word_wrap=True, size_policy_horizontal='min-expanding', text_alignment_vertical='top'),
            u.create_label(text="@binding(viewmodel.directory_warning.value)", color="red"),
        ))
        self.directory_text_label = directory_text
        directory_button = u.create_row(u.create_push_button(text=_("Select Path..."), on_clicked="choose_directory"), u.create_stretch())

        # Filename
        filename_label = u.create_row(u.create_label(text="Filename:", font='bold'), u.create_stretch())

        # Title
        title_checkbox = u.create_row(
            u.create_check_box(text="Include Title", checked="@binding(viewmodel.include_title.value)"), u.create_stretch())

        # Date
        date_checkbox = u.create_row(
            u.create_check_box(text="Include Date", checked="@binding(viewmodel.include_date.value)"), u.create_stretch())

        # Dimensions
        dimension_checkbox = u.create_row(
            u.create_check_box(text="Include Dimensions", checked="@binding(viewmodel.include_dimensions.value)"), u.create_stretch())

        # Sequence Number
        sequence_checkbox = u.create_row(
            u.create_check_box(text="Include Sequence Number", checked="@binding(viewmodel.include_sequence.value)"), u.create_stretch())

        # Prefix. Include a messy callback so that prefix gets updated during typing.
        prefix_label = u.create_label(text=_("Prefix:"))
        prefix_textbox = u.create_line_edit(text="@binding(viewmodel.prefix.value)", placeholder_text=_("None"), width=230, on_text_edited="handle_prefix_edited")
        prefix_row = u.create_row(prefix_label, prefix_textbox, u.create_stretch(), spacing=10)

        # File Type
        file_type_combobox = u.create_combo_box(
            items=writers_names,
            current_index="@binding(writer_index)",
            on_current_index_changed="_handle_writer_changed")
        file_type_label = u.create_label(text=_("File Format:"), font='bold')
        file_type_row = u.create_row(file_type_combobox, u.create_stretch())

        # Build final ui column
        column = u.create_column(directory_label,
                                 directory_text,
                                 directory_button,
                                 filename_label,
                                 prefix_row,
                                 title_checkbox,
                                 date_checkbox,
                                 dimension_checkbox,
                                 sequence_checkbox,
                                 file_type_label,
                                 file_type_row,
                                 spacing=12, margin=12)
        self.ui_view = column

    @staticmethod
    def export_clicked(display_items: typing.Sequence[DisplayItem.DisplayItem], viewmodel: ExportDialogViewModel,
                       ui: UserInterface.UserInterface, document_controller: DocumentController.DocumentController) -> None:
        writer = viewmodel.writer.value
        if writer:
            export_results = list()
            is_directory_valid = viewmodel.is_directory_valid
            for index, display_item in enumerate(display_items):
                if not is_directory_valid:
                    error_message = _("Directory does not exist")
                    export_results.append(ExportResult(display_item.displayed_title, f"{error_message}"))
                    continue

                data_item = display_item.data_item
                try:
                    displayed_title = display_item.displayed_title
                    # prefer the data item created date, but fall back to the display item created date.
                    date = data_item.created_local if data_item else display_item.created_local
                    dimensional_shape = data_item.dimensional_shape if data_item else None
                    filepath = viewmodel.build_filepath(displayed_title, date, dimensional_shape, index)
                    file_extension = filepath.suffix[1:].lower()
                    if writer.can_write_display_item(display_item, file_extension):
                        ImportExportManager.ImportExportManager().write_display_item_with_writer(writer, display_item, filepath)
                        export_results.append(ExportResult(display_item.displayed_title))
                    else:
                        error_message = _("Cannot export this data to file format")
                        export_results.append(ExportResult(display_item.displayed_title, f"{error_message} {writer.name}"))
                except Exception as e:
                    logging.debug("Could not export image %s / %s", str(data_item), str(e))
                    traceback.print_exc()
                    traceback.print_stack()
                    export_results.append(ExportResult(display_item.displayed_title, str(e)))

            ExportResultDialog(ui, document_controller, export_results, viewmodel.directory_path_object)

    def cancel(self) -> bool:
        return True


class UnitDescription:
    """A description of a unit. Read only."""

    def __init__(self, unit_id: str, title: str, conversion_factor: float) -> None:
        self.__unit_id = unit_id
        self.__title = title
        self.__conversion_factor = conversion_factor

    @property
    def unit_id(self) -> str:
        return self.__unit_id

    @property
    def title(self) -> str:
        return self.__title

    @property
    def conversion_factor(self) -> float:
        return self.__conversion_factor

    def convert_value_to_pixels(self, value: float) -> float:
        return value * self.__conversion_factor

    def convert_value_from_pixels(self, value: float) -> float:
        return value / self.__conversion_factor


class Quantity:
    """A quantity with a value and a unit description. Read only."""

    def __init__(self, value: float, unit_description: UnitDescription) -> None:
        self.__value = value
        self.__unit_description = unit_description

    def __str__(self) -> str:
        return f"{self.__value} {self.__unit_description.title}"

    def with_value(self, value: float) -> Quantity:
        return Quantity(value, self.__unit_description)

    def with_unit_description(self, unit_description: UnitDescription) -> Quantity:
        return Quantity(unit_description.convert_value_from_pixels(self.pixels), unit_description)

    def with_same_value_new_description(self, unit_description: UnitDescription) -> Quantity:
        """Return a new quantity with the same numeric value but a different unit description.

        Unlike `with_unit_description`, this does not reconvert through pixels. Use this when the
        unit id is unchanged but its conversion factor has changed (e.g. the ppi used for inches or
        centimeters changed) and the displayed value (e.g. "4" inches) should be preserved while the
        underlying pixel size changes to match the new conversion factor.
        """
        return Quantity(self.__value, unit_description)

    @property
    def value(self) -> float:
        return self.__value

    @property
    def is_pixels(self) -> bool:
        return self.__unit_description.unit_id == "pixels"

    @property
    def pixels(self) -> float:
        return self.__value * self.__unit_description.conversion_factor


def get_quantity_from_pixels(pixels: float, unit_description: UnitDescription) -> Quantity:
    """Return a quantity from pixels and a unit description."""
    return Quantity(unit_description.convert_value_from_pixels(pixels), unit_description)


# define the units. the conversion factor is the number of pixels per unit.
pixel_unit_description = UnitDescription("pixels", _("Pixels"), 1.0)
inch_unit_description = UnitDescription("inches", _("Inches"), 96.0)
centimeter_unit_description = UnitDescription("centimeters", _("Centimeters"), 37.795275591)


# the list of available units for SVG export
svg_export_unit_descriptions = [
    pixel_unit_description,
    inch_unit_description,
    centimeter_unit_description
]


def make_unit_descriptions_for_ppi(ppi: int) -> dict[str, UnitDescription]:
    """Return unit descriptions (keyed by unit id) scaled to the given ppi.

    The pixel unit never scales with ppi (a pixel is always a pixel); inches and centimeters
    scale their pixels-per-unit conversion factor with ppi, since that is the definition of dpi/ppi:
    the same physical size (in inches or centimeters) maps to more or fewer pixels depending on ppi.
    """
    return {
        pixel_unit_description.unit_id: pixel_unit_description,
        "inches": UnitDescription("inches", _("Inches"), ppi),
        "centimeters": UnitDescription("centimeters", _("Centimeters"), ppi / 2.54),
    }


def calculate_display_size_in_pixels(display_item: DisplayItem.DisplayItem) -> Geometry.IntSize:
    """Return the display size in pixels.

    If the display item is a line plot, use the hardcoded value of 5x3 inches.
    """
    display_info = display_item.display_info
    display_calibration_info = display_info.display_calibration_info if display_info else None
    display_data_shape = display_calibration_info.display_data_shape if display_calibration_info else None
    if display_data_shape and display_item.used_display_type != "line_plot":
        return Geometry.IntSize(height=display_data_shape[-2], width=display_data_shape[-1])
    return Geometry.IntSize(
        height=round(inch_unit_description.convert_value_to_pixels(3.0)),
        width=round(inch_unit_description.convert_value_to_pixels(5.0))
    )


class ExportSizeModel(Observable.Observable):
    def __init__(self, display_item: DisplayItem.DisplayItem, unit_id_model: Model.PropertyModel[str], ppi: int = 96) -> None:
        super().__init__()
        self.__display_item = display_item
        self.__unit_id_model = unit_id_model
        self.__ppi = ppi
        self.__unit_descriptions_by_id = make_unit_descriptions_for_ppi(ppi)
        display_size = calculate_display_size_in_pixels(display_item)
        self.__aspect_ratio = (display_size.width / display_size.height if display_size.height > 0 else 1.0) if display_size.width > 0 else 1.0
        self.aspect_ratio_mode = Model.PropertyModel("default")
        self.__float_to_string_converter = Converter.FloatToStringConverter()
        self.__primary_field = 'width'
        unit_description = self.__unit_descriptions_by_id.get(unit_id_model.value or str(), pixel_unit_description)
        self.aspect_ratio_locked = Model.PropertyModel(True)
        self.is_line_plot = (display_item.used_display_type == "line_plot")
        self.__width_quantity = get_quantity_from_pixels(display_size.width, unit_description)
        self.__height_quantity = get_quantity_from_pixels(display_size.height, unit_description)

    @property
    def title(self) -> typing.Optional[str]:
        """Return the display item title."""
        title_str = self.__display_item.displayed_title
        return title_str

    @property
    def shape_str(self) -> typing.Optional[str]:
        """Return the pixel shape as a string."""
        shape_str = "(" + self.__display_item.export_data_info.data_shape_str + ")"
        return shape_str

    @property
    def calibrated_shape_str(self) -> typing.Optional[str]:
        """Return the calculated shape as a string."""
        if self.__display_item.export_data_info.calibrated_dimensional_calibrations_str:
            calibration_str = "(" + self.__display_item.export_data_info.calibrated_dimensional_calibrations_str + ")"
            return calibration_str
        else:
            return ""

    @property
    def aspect_ratio_mode_index(self) -> int:
        modes = ["default", "16:9", "4:3", "1:1", "custom"]
        try:
            mode = self.aspect_ratio_mode.value or "default"
            return modes.index(mode)
        except ValueError:
            return 0

    @aspect_ratio_mode_index.setter
    def aspect_ratio_mode_index(self, index: int) -> None:
        modes = ["default", "16:9", "4:3", "1:1", "custom"]
        if 0 <= index < len(modes):
            self.set_aspect_ratio_mode(modes[index])

    @property
    def _width(self) -> float:
        """Return the width in pixels.

        If the primary field is width or aspect ratio unlocked, return the last quantity value directly.

        Otherwise, calculate the width from the last quantity value and the aspect ratio.

        If the last quantity is in pixels, round the value.
        """
        width_quant = self.__width_quantity
        if self.aspect_ratio_locked.value and self.__primary_field == 'height':
            width_quant = self.__width_quantity.with_value(self.__height_quantity.value * self.__aspect_ratio)
        return round(width_quant.value) if width_quant.is_pixels else width_quant.value

    @property
    def _height(self) -> float:
        """Return the height in pixels.

        If the primary field is height, return the last quantity value directly.

        Otherwise, calculated the height from the last quantity value and the aspect ratio.

        If the last quantity is in pixels, round the value.
        """
        height_quant = self.__height_quantity
        if self.aspect_ratio_locked.value and self.__primary_field == 'width':
            height_quant = self.__height_quantity.with_value(self.__width_quantity.value / self.__aspect_ratio)
        return round(height_quant.value) if height_quant.is_pixels else height_quant.value

    @property
    def width_text(self) -> typing.Optional[str]:
        """Return the width as a string if the primary field is width or aspect ratio unlocked,
         otherwise None."""
        if not self.aspect_ratio_locked.value:
            # editable even when not primary
            return self.__float_to_string_converter.convert(self._width)
        if self.__primary_field == 'width':
            return self.__float_to_string_converter.convert(self._width)
        return None

    @width_text.setter
    def width_text(self, value_str: typing.Optional[str]) -> None:
        """Sets the width from a string and sets the primary field to width.

              Else sets the width from string and updates the width quantity.

              Signals that all the text fields have changed.
              """
        if value_str is None or value_str == "":
            return
        value = self.__float_to_string_converter.convert_back(value_str)

        if value is None:
            return

        self.__primary_field = 'width'
        self.__width_quantity = self.__width_quantity.with_value(value)

        if self.aspect_ratio_locked.value:
            self.__height_quantity = self.__height_quantity.with_value(value / self.__aspect_ratio)

        self.notify_property_changed("width_text")
        self.notify_property_changed("height_text")
        self.notify_property_changed("placeholder_width_text")
        self.notify_property_changed("placeholder_height_text")

    @property
    def placeholder_width_text(self) -> str | None:
        """Return the width as a string."""
        return self.__float_to_string_converter.convert(self._width)

    @property
    def height_text(self) -> typing.Optional[str]:
        """Return the height as a string if the primary field is height or aspect ratio unlocked,
         otherwise None."""
        if not self.aspect_ratio_locked.value or self.__primary_field == 'height':
            # editable even when not primary
            return self.__float_to_string_converter.convert(self._height)
        return None

    @height_text.setter
    def height_text(self, value_str: typing.Optional[str]) -> None:
        """If aspect ratio locked sets the height from a string, sets the primary field to height
        and updates the height and width quantity.

        Else sets the height from string and updates the height quantity.

        Signals that all the text fields have changed.
        """
        if value_str is None or value_str == "":
            return
        value = self.__float_to_string_converter.convert_back(value_str)
        if value is None:
            return

        self.__primary_field = 'height'
        self.__height_quantity = self.__height_quantity.with_value(value)
        if self.aspect_ratio_locked.value:
            self.__width_quantity = self.__width_quantity.with_value(value * self.__aspect_ratio)
        self.notify_property_changed("width_text")
        self.notify_property_changed("height_text")
        self.notify_property_changed("placeholder_width_text")
        self.notify_property_changed("placeholder_height_text")

    @property
    def placeholder_height_text(self) -> str | None:
        """Return the height as a string."""
        return self.__float_to_string_converter.convert(self._height)

    @property
    def unit_description(self) -> UnitDescription:
        """Return the unit description for the current unit id."""
        return self.__unit_descriptions_by_id.get(self.__unit_id_model.value or str(), pixel_unit_description)

    @property
    def unit_index(self) -> int:
        """Return the unit index for the current unit description."""
        unit_id = self.unit_description.unit_id
        for index, unit_description_ in enumerate(svg_export_unit_descriptions):
            if unit_description_.unit_id == unit_id:
                return index
        return 0

    @unit_index.setter
    def unit_index(self, unit_index: int) -> None:
        """Set the unit index.

        Saves the unit index to the unit_id_model.

        Then converts the current quantity to the new unit description.

        Then signals that all the text fields have changed.
        """
        if 0 <= unit_index < len(svg_export_unit_descriptions):
            self.__unit_id_model.value = svg_export_unit_descriptions[unit_index].unit_id
        else:
            self.__unit_id_model.value = pixel_unit_description.unit_id
        self.__width_quantity = self.__width_quantity.with_unit_description(self.unit_description)
        self.__height_quantity = self.__height_quantity.with_unit_description(self.unit_description)

        self.notify_property_changed("width_text")
        self.notify_property_changed("height_text")
        self.notify_property_changed("placeholder_width_text")
        self.notify_property_changed("placeholder_height_text")
        self.notify_property_changed("is_pixel_unit")

    @property
    def is_pixel_unit(self) -> bool:
        """Return whether the currently selected unit is Pixels.

        PPI only affects the pixel output when the unit is a physical unit (inches, centimeters);
        when the unit is Pixels, an exact pixel count has been specified and PPI has no effect on
        the output dimensions.
        """
        return self.unit_description.unit_id == pixel_unit_description.unit_id

    @property
    def ppi(self) -> int:
        """Return the ppi used to convert between physical units (inches, centimeters) and pixels."""
        return self.__ppi

    def set_ppi(self, ppi: int) -> None:
        """Set the ppi used to convert between physical units (inches, centimeters) and pixels.

        Rebuilds the ppi-scaled unit descriptions. If the currently selected unit is ppi-dependent
        (inches or centimeters), the displayed value is preserved (e.g. "4" inches stays "4") while the
        underlying pixel size changes to match the new ppi. The pixel unit is unaffected by ppi, since a
        pixel-specified size means an exact pixel count regardless of ppi.
        """
        if ppi == self.__ppi:
            return
        self.__ppi = ppi
        self.__unit_descriptions_by_id = make_unit_descriptions_for_ppi(ppi)
        new_unit_description = self.unit_description
        self.__width_quantity = self.__width_quantity.with_same_value_new_description(new_unit_description)
        self.__height_quantity = self.__height_quantity.with_same_value_new_description(new_unit_description)
        self.notify_property_changed("width_text")
        self.notify_property_changed("height_text")
        self.notify_property_changed("placeholder_width_text")
        self.notify_property_changed("placeholder_height_text")
        self.notify_property_changed("shape_str")

    @property
    def pixel_shape(self) -> Geometry.IntSize:
        """Return the export pixel shape honoring the current units and aspect lock."""
        if not self.aspect_ratio_locked.value:
            h_pixels = self.__height_quantity.pixels
            w_pixels = self.__width_quantity.pixels
        else:
            if self.__primary_field == 'width':
                w_pixels = self.__width_quantity.pixels
                h_pixels = w_pixels / self.__aspect_ratio
            else:
                h_pixels = self.__height_quantity.pixels
                w_pixels = h_pixels * self.__aspect_ratio
        return Geometry.IntSize(height=round(h_pixels), width=round(w_pixels))

    def snap_dimensions_to_aspect_ratio(self) -> None:
        if self.__primary_field == 'width':
            self.__height_quantity = self.__height_quantity.with_value(self.__width_quantity.value / self.__aspect_ratio)
        else:
            self.__width_quantity = self.__width_quantity.with_value(self.__height_quantity.value * self.__aspect_ratio)
        self.notify_property_changed("width_text")
        self.notify_property_changed("height_text")
        self.notify_property_changed("placeholder_width_text")
        self.notify_property_changed("placeholder_height_text")

    def set_aspect_ratio_mode(self, mode: str) -> None:
        self.aspect_ratio_mode.value = mode
        if mode == "default":
            display_size = calculate_display_size_in_pixels(self.__display_item)
            self.__aspect_ratio = display_size.width / display_size.height
            self.aspect_ratio_locked.value = True
            self.snap_dimensions_to_aspect_ratio()

        elif mode == "16:9":
            self.__aspect_ratio = 16 / 9
            self.aspect_ratio_locked.value = True
            self.snap_dimensions_to_aspect_ratio()

        elif mode == "4:3":
            self.__aspect_ratio = 4 / 3
            self.aspect_ratio_locked.value = True
            self.snap_dimensions_to_aspect_ratio()

        elif mode == "1:1":
            self.__aspect_ratio = 1.0
            self.aspect_ratio_locked.value = True
            self.snap_dimensions_to_aspect_ratio()

        elif mode == "custom":
            # unlock
            self.aspect_ratio_locked.value = False

        self.notify_property_changed("aspect_ratio_mode")
        self.notify_property_changed("width_text")
        self.notify_property_changed("height_text")


class ExportFormatModel(Observable.Observable):
    """Holds the export-target state: SVG vs. Bitmap Image, the bitmap file format, and the target ppi.

    This model is intentionally decoupled from ExportSizeModel -- it knows nothing about physical size,
    units, or aspect ratio. It exposes `effective_ppi`, a fixed 96.0 while exporting SVG (matching
    today's behavior), or the user's chosen ppi while exporting a bitmap; note this does not yet account
    for the size unit being Pixels (see ExportDisplayHandler.effective_ppi for the fully-corrected value
    used for size math, rendering, and export metadata, which also forces 96 in that case). Callers
    (e.g. ExportDisplayHandler) are responsible for pushing the fully-corrected ppi into
    `ExportSizeModel.set_ppi(...)` whenever it changes; this model does not do that itself, to avoid any
    dependency between the two models.
    """

    # (format id, title, default file extension)
    bitmap_format_descriptions: typing.Sequence[tuple[str, str, str]] = (
        ("png", _("PNG"), "png"),
        ("bmp", _("BMP"), "bmp"),
        ("jpeg", _("JPEG"), "jpg"),
    )

    export_categories: typing.Sequence[tuple[str, str]] = (
        ("svg", _("SVG")),
        ("bitmap", _("Bitmap Image")),
    )

    ppi_presets: typing.Sequence[int] = (72, 96, 150, 300, 600)

    def __init__(self, ui: UserInterface.UserInterface) -> None:
        super().__init__()
        self.__int_to_string_converter = Converter.IntegerToStringConverter()
        self.__category_model = UserInterface.StringPersistentModel(ui=ui, storage_key="export_category", value="svg")
        self.__bitmap_format_model = UserInterface.StringPersistentModel(ui=ui, storage_key="export_bitmap_format", value="png")
        self.__ppi_model = UserInterface.IntegerPersistentModel(ui=ui, storage_key="export_ppi", value=96)
        # tracks whether "Custom" is the user's explicit selection in the PPI combo box. This is
        # distinct from "ppi is not a preset value": choosing "Custom" while ppi already happens to
        # equal a preset (e.g. the default 96) must still reveal the custom-entry field, even though
        # the underlying ppi value hasn't changed yet.
        self.__custom_ppi_selected = self.ppi not in self.ppi_presets

    @property
    def export_category(self) -> str:
        return self.__category_model.value or "svg"

    @export_category.setter
    def export_category(self, value: str) -> None:
        self.__category_model.value = value
        self.notify_property_changed("export_category")
        self.notify_property_changed("export_category_index")
        self.notify_property_changed("is_svg")
        self.notify_property_changed("is_bitmap")
        self.notify_property_changed("effective_ppi")
        self.notify_property_changed("show_custom_ppi")

    @property
    def export_category_index(self) -> int:
        ids = [category_id for category_id, _title in self.export_categories]
        try:
            return ids.index(self.export_category)
        except ValueError:
            return 0

    @export_category_index.setter
    def export_category_index(self, index: int) -> None:
        ids = [category_id for category_id, _title in self.export_categories]
        self.export_category = ids[index] if 0 <= index < len(ids) else "svg"

    @property
    def is_svg(self) -> bool:
        return self.export_category == "svg"

    @property
    def is_bitmap(self) -> bool:
        return self.export_category == "bitmap"

    @property
    def bitmap_format(self) -> str:
        return self.__bitmap_format_model.value or "png"

    @bitmap_format.setter
    def bitmap_format(self, value: str) -> None:
        self.__bitmap_format_model.value = value
        self.notify_property_changed("bitmap_format")
        self.notify_property_changed("bitmap_format_index")
        self.notify_property_changed("bitmap_format_extension")

    @property
    def bitmap_format_index(self) -> int:
        ids = [format_id for format_id, _title, _extension in self.bitmap_format_descriptions]
        try:
            return ids.index(self.bitmap_format)
        except ValueError:
            return 0

    @bitmap_format_index.setter
    def bitmap_format_index(self, index: int) -> None:
        ids = [format_id for format_id, _title, _extension in self.bitmap_format_descriptions]
        self.bitmap_format = ids[index] if 0 <= index < len(ids) else "png"

    @property
    def bitmap_format_extension(self) -> str:
        """Return the default file extension (without leading dot) for the current bitmap format."""
        for format_id, _title, extension in self.bitmap_format_descriptions:
            if format_id == self.bitmap_format:
                return extension
        return "png"

    @property
    def ppi(self) -> int:
        return self.__ppi_model.value or 96

    @ppi.setter
    def ppi(self, value: int) -> None:
        if value <= 0:
            return
        custom_ppi_selected_changed = (value not in self.ppi_presets) != self.__custom_ppi_selected
        self.__custom_ppi_selected = value not in self.ppi_presets
        if value == self.ppi:
            if custom_ppi_selected_changed:
                self.notify_property_changed("ppi_index")
                self.notify_property_changed("is_custom_ppi")
                self.notify_property_changed("show_custom_ppi")
            return
        self.__ppi_model.value = value
        self.notify_property_changed("ppi")
        self.notify_property_changed("ppi_text")
        self.notify_property_changed("ppi_index")
        self.notify_property_changed("is_custom_ppi")
        self.notify_property_changed("effective_ppi")
        self.notify_property_changed("show_custom_ppi")

    @property
    def ppi_text(self) -> str | None:
        return self.__int_to_string_converter.convert(self.ppi)

    @ppi_text.setter
    def ppi_text(self, value_str: str | None) -> None:
        if not value_str:
            return
        value = self.__int_to_string_converter.convert_back(value_str)
        if value is not None and value > 0:
            self.ppi = value

    @property
    def ppi_index(self) -> int:
        """Return the index of the current ppi in the presets list, or the "Custom" index if not a preset."""
        if self.__custom_ppi_selected:
            return len(self.ppi_presets)
        try:
            return self.ppi_presets.index(self.ppi)
        except ValueError:
            return len(self.ppi_presets)

    @ppi_index.setter
    def ppi_index(self, index: int) -> None:
        if 0 <= index < len(self.ppi_presets):
            self.ppi = self.ppi_presets[index]
        else:
            # "Custom" selected; the ppi value itself is unchanged (until the user types a new one
            # into the custom-entry field), but the "custom" state must be recorded explicitly here
            # since ppi may currently equal a preset value (e.g. the default 96) -- the custom entry
            # field still needs to be revealed in that case.
            self.__custom_ppi_selected = True
            self.notify_property_changed("ppi_index")
            self.notify_property_changed("is_custom_ppi")
            self.notify_property_changed("show_custom_ppi")

    @property
    def is_custom_ppi(self) -> bool:
        return self.__custom_ppi_selected

    @property
    def show_custom_ppi(self) -> bool:
        """Return whether the custom-ppi text entry should be shown (bitmap mode and a non-preset ppi)."""
        return self.is_bitmap and self.is_custom_ppi

    @property
    def effective_ppi(self) -> int:
        """Return the ppi that should currently be used for size math.

        Fixed at 96.0 while exporting SVG (matches today's fixed-96 SVG behavior); the user's chosen
        ppi while exporting a Bitmap Image.
        """
        return 96 if self.is_svg else self.ppi


class ExportDisplayHandler(Declarative.Handler):
    def __init__(self, model: ExportSizeModel, format_model: ExportFormatModel, get_font_metrics_fn: typing.Callable[[str, str], UserInterface.FontMetrics]) -> None:
        super().__init__()
        self.model = model
        self.format_model = format_model
        u = Declarative.DeclarativeUI()
        left_column_width = get_font_metrics_fn("normal", "Shape (calibrated units)").width + 20

        right_column_strings = [model.title, model.shape_str, model.calibrated_shape_str]
        right_column_width = max(get_font_metrics_fn("normal", s or str()).width for s in right_column_strings) + 20
        right_column_width = max(right_column_width, left_column_width)

        self.has_calibrated_shape_str = bool(model.calibrated_shape_str)

        unit_titles = [unit_description.title for unit_description in svg_export_unit_descriptions]
        unit_combo_box_width = max(get_font_metrics_fn("normal", s).width for s in unit_titles) + 72

        export_category_titles = [title for _category_id, title in ExportFormatModel.export_categories]
        bitmap_format_titles = [title for _format_id, title, _extension in ExportFormatModel.bitmap_format_descriptions]
        ppi_combo_titles = [str(int(ppi)) for ppi in ExportFormatModel.ppi_presets] + [_("Custom")]

        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Export As"), width=left_column_width),
                u.create_combo_box(
                    items=export_category_titles,
                    current_index="@binding(format_model.export_category_index)",
                    width=140
                ),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("File Format"), width=left_column_width),
                u.create_combo_box(
                    items=bitmap_format_titles,
                    current_index="@binding(format_model.bitmap_format_index)",
                    enabled="@binding(format_model.is_bitmap)",
                    width=140
                ),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text="Title", width=left_column_width),
                u.create_label(text="@binding(model.title)", width=right_column_width),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text="Data shape (Pixels) ", width=left_column_width),
                u.create_label(text="@binding(model.shape_str)", width=right_column_width),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text="Shape (calibrated units) ", width=left_column_width),
                u.create_label(text="@binding(model.calibrated_shape_str)", width=right_column_width),
                u.create_stretch(),
                spacing=8,
                visible="@binding(has_calibrated_shape_str)"
            ),
            u.create_row(
                u.create_label(text=_("Aspect Ratio"), width=left_column_width),
                u.create_combo_box(
                    items=["Default (5:3)", "16:9", "4:3", "1:1", "Custom"],
                    current_index="@binding(model.aspect_ratio_mode_index)",
                    on_current_index_changed="on_aspect_ratio_changed",
                    width=140
                ),
                u.create_stretch(),
                spacing=8,
                visible = "@binding(model.is_line_plot)"
            ),
            u.create_row(
                u.create_label(text=_("Width"), width=left_column_width),
                u.create_line_edit(
                    placeholder_text="@binding(model.placeholder_width_text)",
                    text="@binding(model.width_text)",
                    width=100
                ),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Height"), width=left_column_width),
                u.create_line_edit(
                    placeholder_text="@binding(model.placeholder_height_text)",
                    text="@binding(model.height_text)",
                    width=100
                ),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Units"), width=left_column_width),
                u.create_combo_box(
                    items=unit_titles,
                    current_index="@binding(model.unit_index)",
                    width=unit_combo_box_width
                ),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("PPI"), width=left_column_width),
                u.create_combo_box(
                    items=ppi_combo_titles,
                    current_index="@binding(format_model.ppi_index)",
                    enabled="@binding(show_ppi_controls)",
                    width=140
                ),
                u.create_stretch(),
                spacing=8
            ),
            u.create_row(
                u.create_label(text=_("Custom PPI"), width=left_column_width),
                u.create_line_edit(
                    text="@binding(format_model.ppi_text)",
                    enabled="@binding(show_custom_ppi_controls)",
                    width=100
                ),
                u.create_stretch(),
                spacing=8
            ),
            spacing=8,
            margin=12,
        )

        # keep the size model's ppi synced with effective_ppi (96 for SVG or when the size unit is
        # Pixels, the user's chosen ppi otherwise). this is the only coupling between the two models.
        self.__apply_effective_ppi()
        self.__format_property_changed_listener = format_model.property_changed_event.listen(self.__handle_format_property_changed)
        # the PPI controls are only meaningful (and only shown) when exporting a bitmap AND the size
        # unit is a physical unit (inches/centimeters); when the unit is Pixels, an exact pixel count
        # has been specified and PPI has no effect on the output dimensions, so hide it to avoid the
        # appearance of a dead control.
        self.__model_property_changed_listener = model.property_changed_event.listen(self.__handle_model_property_changed)

    def close(self) -> None:
        self.__model_property_changed_listener.close()
        self.__model_property_changed_listener = typing.cast(typing.Any, None)
        self.__format_property_changed_listener.close()
        self.__format_property_changed_listener = typing.cast(typing.Any, None)
        super().close()

    def __handle_format_property_changed(self, property_name: str) -> None:
        if property_name in ("export_category", "ppi", "effective_ppi"):
            self.__apply_effective_ppi()
        if property_name in ("export_category", "is_bitmap", "ppi", "is_custom_ppi"):
            self.notify_property_changed("show_ppi_controls")
            self.notify_property_changed("show_custom_ppi_controls")

    def __handle_model_property_changed(self, property_name: str) -> None:
        if property_name == "is_pixel_unit":
            self.__apply_effective_ppi()
            self.notify_property_changed("show_ppi_controls")
            self.notify_property_changed("show_custom_ppi_controls")

    def __apply_effective_ppi(self) -> None:
        self.model.set_ppi(self.effective_ppi)

    @property
    def effective_ppi(self) -> int:
        """Return the ppi that should currently be used for size math, rendering, and export metadata.

        Fixed at 96 while exporting SVG, or while exporting a Bitmap Image with the size unit set to
        Pixels (an exact pixel count has been specified, so there is no physical size for ppi to apply
        to -- using the user's last-chosen physical-unit ppi here would silently bake a stale, unrelated
        ppi into font/line rendering and the exported file's DPI metadata). Otherwise, the user's chosen
        ppi.
        """
        if self.format_model.is_svg or self.model.is_pixel_unit:
            return 96
        return self.format_model.ppi

    @property
    def show_ppi_controls(self) -> bool:
        """Return whether the PPI preset combo box should be shown.

        PPI only has a visible effect when exporting a bitmap with a physical (inches/centimeters)
        size unit; when the unit is Pixels, an exact pixel count has already been specified and PPI
        would have no effect on the output dimensions, so the control is hidden in that case.
        """
        return self.format_model.is_bitmap and not self.model.is_pixel_unit

    @property
    def show_custom_ppi_controls(self) -> bool:
        """Return whether the custom-ppi text entry should be shown."""
        return self.show_ppi_controls and self.format_model.is_custom_ppi

    def on_aspect_ratio_changed(self, widget: Declarative.UIWidget, current_index: int) -> None:
        modes = ["default", "16:9", "4:3", "1:1", "custom"]
        mode = modes[current_index] if 0 <= current_index < len(modes) else "default"
        self.model.set_aspect_ratio_mode(mode)

    def on_lock_check_changed(self, widget: Declarative.UIWidget, check_state: str) -> None:
        if check_state == "checked":
            self.model.snap_dimensions_to_aspect_ratio()


class ExportDisplayDialog:
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__units_model = UserInterface.StringPersistentModel(
            ui=document_controller.ui,
            storage_key="export_units",
            value=pixel_unit_description.unit_id
        )
        self.__format_model = ExportFormatModel(document_controller.ui)
        self.__model = ExportSizeModel(display_item, self.__units_model, self.__format_model.effective_ppi)
        self.__handler = ExportDisplayHandler(self.__model, self.__format_model, document_controller.ui.get_font_metrics)
        self.__init_ui()

    def __init_ui(self) -> None:
        u = Declarative.DeclarativeUI()
        dialog = typing.cast(Dialog.ActionDialog, Declarative.construct(
            self.__document_controller.ui,
            self.__document_controller,
            u.create_modeless_dialog(
                self.__handler.ui_view, title=_("Export SVG/Bitmap")
            ),
            self.__handler
        ))
        dialog.add_button(_("Cancel"), self.__cancel_clicked)
        dialog.add_button(_("Export"), self.__ok_clicked)
        dialog.show()

    def __ok_clicked(self) -> bool:
        pixel_shape = self.__model.pixel_shape
        ui = self.__document_controller.ui
        if self.__format_model.is_bitmap:
            extension = self.__format_model.bitmap_format_extension
            format_title = dict((format_id, title) for format_id, title, _extension in ExportFormatModel.bitmap_format_descriptions)[self.__format_model.bitmap_format]
            filter = f"{format_title} File (*.{extension});;All Files (*.*)"
        else:
            extension = "svg"
            filter = "SVG File (*.svg);;All Files (*.*)"
        export_dir = ui.get_persistent_string("export_directory", ui.get_document_location())
        export_dir = os.path.join(export_dir, self.__display_item.displayed_title)
        path, selected_filter, selected_directory = self.__document_controller.get_save_file_path(
            _("Export File"), export_dir, filter, None
        )
        if path and not os.path.splitext(path)[1]:
            path = path + os.path.extsep + extension
        if path:
            ui.set_persistent_string("export_directory", selected_directory)
            if self.__format_model.is_bitmap:
                self.__document_controller.export_bitmap_file(
                    DisplayPanel.DisplayPanelUISettings(ui),
                    self.__display_item,
                    pixel_shape,
                    self.__handler.effective_ppi,
                    pathlib.Path(path),
                    extension
                )
            else:
                self.__document_controller.export_svg_file(
                    DisplayPanel.DisplayPanelUISettings(ui),
                    self.__display_item,
                    pixel_shape,
                    pathlib.Path(path)
                )
        return True

    def __cancel_clicked(self) -> bool:
        return True


@dataclasses.dataclass
class ExportResult:
    data_item_title: str
    error: typing.Optional[str] = None


class ExportResultDialog(Declarative.Handler):
    def __init__(self, ui: UserInterface.UserInterface, document_controller: DocumentController.DocumentController,
                 exports: typing.Sequence[ExportResult], export_folder: pathlib.Path):
        super().__init__()

        self.ui = ui
        self.__document_controller = document_controller
        self.exports = exports
        self.export_folder = export_folder

        # build the UI
        u = Declarative.DeclarativeUI()
        self._build_ui(u)

        # create the dialog and show it.
        export_result_text = _("Export Results")
        items_text = _("Items")
        title_text = f"{export_result_text} ({len(exports)} {items_text})"
        dialog = typing.cast(Dialog.ActionDialog, Declarative.construct(document_controller.ui, document_controller,
                                                                        u.create_modeless_dialog(self.ui_view,
                                                                                                 title=title_text),
                                                                        self))

        dialog.add_button(_("OK"), self.ok_click)
        dialog.show()

    def open_export_folder(self, widget: Declarative.UIWidget) -> bool:
        if platform.system() == 'Windows':
            subprocess.run(['explorer', self.export_folder])
        elif platform.system() == 'Darwin':
            subprocess.Popen(['open', self.export_folder])
        elif platform.system() == 'linux':
            subprocess.Popen(['xdg-open', self.export_folder])
        return True

    def _build_ui(self, u: Declarative.DeclarativeUI) -> None:
        FILE_FIELD_WIDTH = 320
        STATUS_FIELD_WIDTH = 280
        COLUMN_SPACING = 12

        header_labels = [
            u.create_label(text=_('Data Item'), font='bold', width=FILE_FIELD_WIDTH),
            u.create_label(text=_('Error'), font='bold', width=STATUS_FIELD_WIDTH),
        ]

        file_name_labels = list()
        status_labels = list()

        for export in self.exports:
            if export.error:
                status_text = f"\N{WARNING SIGN} {export.error}"
                color = 'red'
                file_name_labels.append(u.create_label(text=export.data_item_title, tool_tip=export.data_item_title, width=FILE_FIELD_WIDTH))
                status_labels.append(u.create_label(text=status_text, tool_tip=export.error, color=color, width=STATUS_FIELD_WIDTH))

        num_errors = len(file_name_labels)
        total_exports = len(self.exports)
        num_successful = total_exports - num_errors
        info_row = u.create_row(u.create_label(text=f"{num_successful} of {total_exports} successful"))

        header_row = u.create_row(*header_labels, u.create_stretch(), spacing=COLUMN_SPACING)

        scroll_area_width = FILE_FIELD_WIDTH + STATUS_FIELD_WIDTH + COLUMN_SPACING * 2 + 24  # 24 is the estimated width of the scrollbar
        scroll_area_height = min(200, 28 + 28 * len(self.exports))  # 28 is the estimated height of a row

        data_row = u.create_scroll_area(
            u.create_column(
                u.create_row(
                    u.create_column(*file_name_labels, u.create_stretch(), spacing=8),
                    u.create_column(*status_labels, u.create_stretch(), spacing=8),
                    u.create_stretch(),
                    spacing=COLUMN_SPACING
                )
            ),
            min_width=scroll_area_width, min_height=scroll_area_height, max_height=240
        )

        path_title = u.create_label(text=_('Directory:'), font='bold')

        path_directory = u.create_label(text=str(self.export_folder), min_width=280, word_wrap=True, size_policy_horizontal='min-expanding', text_alignment_vertical='top')

        path_goto = u.create_row(u.create_push_button(text='Open Directory', on_clicked='open_export_folder'),
                                 u.create_stretch())

        if num_errors == 0:
            self.ui_view = u.create_column(info_row, path_title, path_directory, path_goto, spacing=8, margin=12)
        else:
            self.ui_view = u.create_column(info_row, path_title, path_directory, path_goto, header_row, data_row, spacing=8,
                                           margin=12)

    def ok_click(self) -> bool:
        return True

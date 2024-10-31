from __future__ import annotations

# standard libraries
import dataclasses
import enum
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

if typing.TYPE_CHECKING:
    from nion.swift.model import DisplayItem

_ = gettext.gettext


class ExportDialogViewModel:

    def __init__(self, title: bool, date: bool, dimensions: bool, sequence: bool, writer: typing.Optional[ImportExportManager.ImportExportHandler], prefix: str = "", directory: str = ""):
        self.include_title = Model.PropertyModel(title)
        self.include_date = Model.PropertyModel(date)
        self.include_dimensions = Model.PropertyModel(dimensions)
        self.include_sequence = Model.PropertyModel(sequence)
        self.include_prefix = Model.PropertyModel(prefix is not None)
        self.prefix = Model.PropertyModel(prefix)
        self.directory = Model.PropertyModel(directory)
        self.writer = Model.PropertyModel(writer)


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
        self.viewmodel = ExportDialogViewModel(True, True, True, True, writer, "", directory)

        # build the UI
        u = Declarative.DeclarativeUI()
        self._build_ui(u)

        # perform export, but save the last used writer
        def handle_export_clicked() -> bool:
            selected_writer = self.viewmodel.writer.value
            writer_id = selected_writer.io_handler_id if selected_writer else "png-io-handler"
            self.export_clicked(display_items, self.viewmodel, ui, document_controller)
            self.ui.set_persistent_string("export_io_handler_id", writer_id)
            return True

        # create the dialog and show it.
        export_text = _("Export")
        items_text = _("Items")
        title_text = f"{export_text} ({len(display_items)} {items_text})"
        dialog = typing.cast(Dialog.ActionDialog, Declarative.construct(document_controller.ui, document_controller, u.create_modeless_dialog(self.ui_view, title=title_text), self))
        dialog.add_button(_("Cancel"), self.cancel)
        dialog.add_button(_("Export"), handle_export_clicked)
        dialog.show()

    def choose_directory(self, widget: Declarative.UIWidget) -> None:
        directory = self.viewmodel.directory.value or str()
        selected_directory, directory = self.ui.get_existing_directory_dialog(_("Choose Export Directory"), directory)
        if selected_directory:
            self.viewmodel.directory.value = selected_directory
            self.ui.set_persistent_string("export_directory", selected_directory)

    def on_writer_changed(self, widget: Declarative.UIWidget, current_index: int) -> None:
        writer = self.__writers[current_index]
        self.viewmodel.writer.value = writer

    def _build_ui(self, u: Declarative.DeclarativeUI) -> None:
        writers_names = [getattr(writer, "name") for writer in self.__writers]

        # Export Folder
        directory_label = u.create_row(u.create_label(text="Location:", font='bold'))
        directory_text = u.create_row(u.create_column(u.create_label(text=f"@binding(viewmodel.directory.value)", min_width=280, height=48, word_wrap=True, size_policy_horizontal='min-expanding', text_alignment_vertical='top')))
        self.directory_text_label = directory_text
        directory_button = u.create_row(u.create_push_button(text=_("Select Path..."), on_clicked="choose_directory"), u.create_stretch())

        # Filename
        filename_label = u.create_row(u.create_label(text="Filename:", font='bold'), u.create_stretch())

        # Title
        title_checkbox = u.create_row(
            u.create_check_box(text="Include Title", checked=f"@binding(viewmodel.include_title.value)"), u.create_stretch())

        # Date
        date_checkbox = u.create_row(
            u.create_check_box(text="Include Date", checked=f"@binding(viewmodel.include_date.value)"), u.create_stretch())

        # Dimensions
        dimension_checkbox = u.create_row(
            u.create_check_box(text="Include Dimensions", checked=f"@binding(viewmodel.include_dimensions.value)"), u.create_stretch())

        # Sequence Number
        sequence_checkbox = u.create_row(
            u.create_check_box(text="Include Sequence Number", checked=f"@binding(viewmodel.include_sequence.value)"), u.create_stretch())

        # Prefix
        prefix_label = u.create_label(text=_("Prefix:"))
        prefix_textbox = u.create_line_edit(text=f"@binding(viewmodel.prefix.value)", placeholder_text=_("None"), width=230)
        prefix_row = u.create_row(prefix_label, prefix_textbox, u.create_stretch(), spacing=10)

        # File Type
        file_type_combobox = u.create_combo_box(
            items=writers_names,
            current_index=f"@binding(writer_index)",
            on_current_index_changed="on_writer_changed")
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
    def build_filepath(components: typing.List[str], extension: str, directory_path: pathlib.Path) -> pathlib.Path:
        assert directory_path.is_dir()

        # if extension doesn't start with a '.', add one, so we always know it is there
        if not extension.startswith('.'):
            extension = '.' + extension

        # stick components together for the first part of the filename, underscore delimited excluding blank component
        filename = "_".join(s for s in components if s)
        filename.replace(".", "_")

        filename = Utility.simplify_filename(str(pathlib.Path(filename).with_suffix(extension)))

        # check to see if filename is available, if so return that
        test_filepath = directory_path / pathlib.Path(filename)
        if not test_filepath.exists():
            return test_filepath

        # file must already exist
        next_index = 1
        max_index = 9999
        last_test_filepath: typing.Optional[pathlib.Path] = None
        while next_index <= max_index:
            filename_stem = pathlib.Path(filename).stem
            test_filepath = directory_path / pathlib.Path(f"{filename_stem} {next_index}").with_suffix(extension)
            if not test_filepath.exists():
                return test_filepath
            if test_filepath == last_test_filepath:
                break
            last_test_filepath = test_filepath  # in case we have a bug
            next_index = next_index + 1

        # We have no option here but to just go with the overwrite, either we ran out of index options or had none to begin with
        print(f"Warning: Overwriting file {test_filepath}")
        return test_filepath

    @staticmethod
    def export_clicked(display_items: typing.Sequence[DisplayItem.DisplayItem], viewmodel: ExportDialogViewModel,
                       ui: UserInterface.UserInterface, document_controller: DocumentController.DocumentController) -> None:
        directory_path = pathlib.Path(viewmodel.directory.value or str())
        writer_model = viewmodel.writer
        writer = writer_model.value
        if directory_path.is_dir() and writer:
            export_results = list()
            for index, display_item in enumerate(display_items):
                data_item = display_item.data_item
                file_name: str = ''
                try:
                    components = list()
                    if viewmodel.prefix.value is not None and viewmodel.prefix.value != '':
                        components.append(str(viewmodel.prefix.value))
                    if viewmodel.include_title.value:
                        title = unicodedata.normalize('NFKC', display_item.displayed_title)
                        title = re.sub(r'[^\w\s-]', '', title, flags=re.U).strip()
                        title = re.sub(r'[-\s]+', '-', title, flags=re.U)
                        components.append(title)
                    if viewmodel.include_date.value:
                        # prefer the data item created date, but fall back to the display item created date.
                        created_local = data_item.created_local if data_item else display_item.created_local
                        components.append(created_local.isoformat().replace(':', '').replace('.', '_'))
                    if viewmodel.include_dimensions.value and data_item:
                        components.append("x".join([str(shape_n) for shape_n in data_item.dimensional_shape]))
                    if viewmodel.include_sequence.value:
                        components.append(str(index))
                    filepath = ExportDialog.build_filepath(components, writer.extensions[0], directory_path=directory_path)
                    file_name = filepath.name
                    file_extension = filepath.suffix[1:].lower()
                    if writer.can_write_display_item(display_item, file_extension):
                        ImportExportManager.ImportExportManager().write_display_item_with_writer(writer, display_item, filepath)
                        export_results.append(ExportResult(file_name))
                    else:
                        error_message = _("Cannot export this data to file format")
                        export_results.append(ExportResult(file_name, f"{error_message} {writer.name}"))
                except Exception as e:
                    logging.debug("Could not export image %s / %s", str(data_item), str(e))
                    traceback.print_exc()
                    traceback.print_stack()
                    export_results.append(ExportResult(file_name, str(e)))

            if any(e.error for e in export_results):
                ExportResultDialog(ui, document_controller, export_results, directory_path)

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


def calculate_display_size_in_pixels(display_item: DisplayItem.DisplayItem) -> Geometry.IntSize:
    """Return the display size in pixels.

    If the display item is a line plot, use the hardcoded value of 5x3 inches.
    """
    if display_item.display_data_shape and display_item.used_display_type != "line_plot":
        return Geometry.IntSize(height=display_item.display_data_shape[-2], width=display_item.display_data_shape[-1])
    return Geometry.IntSize(
        height=round(inch_unit_description.convert_value_to_pixels(3.0)),
        width=round(inch_unit_description.convert_value_to_pixels(5.0))
    )


class ExportSizeModel(Observable.Observable):
    def __init__(self, display_item: DisplayItem.DisplayItem, unit_id_model: Model.PropertyModel[str]) -> None:
        super().__init__()
        self.__display_item = display_item
        self.__unit_id_model = unit_id_model
        display_size = calculate_display_size_in_pixels(display_item)
        self.__aspect_ratio = (display_size.width / display_size.height if display_size.height > 0 else 1.0) if display_size.width > 0 else 1.0
        self.__float_to_string_converter = Converter.FloatToStringConverter()
        self.__primary_field = 'width'
        unit_description = pixel_unit_description
        for unit_description_ in svg_export_unit_descriptions:
            if unit_description_.unit_id == unit_id_model.value:
                unit_description = unit_description_
                break
        min_pixels = inch_unit_description.convert_value_to_pixels(3.0)
        max_pixels = inch_unit_description.convert_value_to_pixels(12.0)
        self.__last_quantity = get_quantity_from_pixels(max(min_pixels, min(max_pixels, display_size.width)), unit_description)

    @property
    def title(self) -> typing.Optional[str]:
        """Return the display item title."""
        title_str = self.__display_item.displayed_title
        return title_str

    @property
    def shape_str(self) -> typing.Optional[str]:
        """Return the pixel shape as a string."""
        shape_str = "(" + self.__display_item.data_info.data_shape_str + ")"
        return shape_str

    @property
    def calibrated_shape_str(self) -> typing.Optional[str]:
        """Return the calculated shape as a string."""
        if self.__display_item.data_info.calibrated_dimensional_calibrations_str:
            calibration_str = "(" + self.__display_item.data_info.calibrated_dimensional_calibrations_str + ")"
            return calibration_str
        else:
            return ""

    @property
    def _width(self) -> float:
        """Return the width in pixels.

        If the primary field is width, return the last quantity value directly.

        Otherwise, calculated the width from the last quantity value and the aspect ratio.

        If the last quantity is in pixels, round the value.
        """
        if self.__last_quantity.is_pixels:
            if self.__primary_field == 'width':
                return round(self.__last_quantity.value)
            else:
                return round(self.__last_quantity.value * self.__aspect_ratio)
        else:
            if self.__primary_field == 'width':
                return self.__last_quantity.value
            else:
                return self.__last_quantity.value * self.__aspect_ratio

    @property
    def _height(self) -> float:
        """Return the height in pixels.

        If the primary field is height, return the last quantity value directly.

        Otherwise, calculated the height from the last quantity value and the aspect ratio.

        If the last quantity is in pixels, round the value.
        """
        if self.__last_quantity.is_pixels:
            if self.__primary_field == 'height':
                return round(self.__last_quantity.value)
            else:
                return round(self.__last_quantity.value / self.__aspect_ratio)
        else:
            if self.__primary_field == 'height':
                return self.__last_quantity.value
            else:
                return self.__last_quantity.value / self.__aspect_ratio

    @property
    def width_text(self) -> typing.Optional[str]:
        """Return the width as a string if the primary field is width, otherwise None."""
        if self.__primary_field == 'width':
            return self.__float_to_string_converter.convert(self._width)
        return None

    @width_text.setter
    def width_text(self, value_str: typing.Optional[str]) -> None:
        """Sets the width from a string and sets the primary field to width.

        Also updates the last quantity and signals that all the text fields have changed.
        """
        if value_str:
            value = self.__float_to_string_converter.convert_back(value_str) or 0.0
            self.__last_quantity = self.__last_quantity.with_value(value)
            self.__primary_field = 'width'
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
        """Return the height as a string if the primary field is height, otherwise None."""
        if self.__primary_field == 'height':
            return self.__float_to_string_converter.convert(self._height)
        return None

    @height_text.setter
    def height_text(self, value_str: typing.Optional[str]) -> None:
        """Sets the height from a string and sets the primary field to height.

        Also updates the last quantity and signals that all the text fields have changed.
        """
        if value_str:
            value = self.__float_to_string_converter.convert_back(value_str) or 0.0
            self.__last_quantity = self.__last_quantity.with_value(value)
            self.__primary_field = 'height'
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
        for unit_description in svg_export_unit_descriptions:
            if unit_description.unit_id == self.__unit_id_model.value:
                return unit_description
        return pixel_unit_description

    @property
    def unit_index(self) -> int:
        """Return the unit index for the current unit description."""
        return svg_export_unit_descriptions.index(self.unit_description)

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
        self.__last_quantity = self.__last_quantity.with_unit_description(self.unit_description)
        self.notify_property_changed("width_text")
        self.notify_property_changed("height_text")
        self.notify_property_changed("placeholder_width_text")
        self.notify_property_changed("placeholder_height_text")

    @property
    def pixel_shape(self) -> Geometry.IntSize:
        if self.__primary_field == 'width':
            return Geometry.IntSize(h=round(self.__last_quantity.pixels / self.__aspect_ratio), w=round(self.__last_quantity.pixels))
        else:
            return Geometry.IntSize(h=round(self.__last_quantity.pixels), w=round(self.__last_quantity.pixels * self.__aspect_ratio))


class ExportSVGHandler(Declarative.Handler):
    def __init__(self, model: ExportSizeModel, get_font_metrics_fn: typing.Callable[[str, str], UserInterface.FontMetrics]) -> None:
        super().__init__()
        self.model = model
        u = Declarative.DeclarativeUI()

        left_column_width = get_font_metrics_fn("normal", "Shape (calibrated units)").width + 20

        right_column_strings = [model.title, model.shape_str, model.calibrated_shape_str]
        right_column_width = max(get_font_metrics_fn("normal", s or str()).width for s in right_column_strings) + 20
        right_column_width = max(right_column_width, left_column_width)

        self.has_calibrated_shape_str = bool(model.calibrated_shape_str)

        unit_titles = [unit_description.title for unit_description in svg_export_unit_descriptions]
        unit_combo_box_width = max(get_font_metrics_fn("normal", s).width for s in unit_titles) + 72

        self.ui_view = u.create_column(
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
            spacing=8,
            margin=12,
        )


class ExportSVGDialog:
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
        self.__model = ExportSizeModel(display_item, self.__units_model)
        self.__handler = ExportSVGHandler(self.__model, document_controller.ui.get_font_metrics)
        self.__init_ui()

    def __init_ui(self) -> None:
        u = Declarative.DeclarativeUI()
        dialog = typing.cast(Dialog.ActionDialog, Declarative.construct(
            self.__document_controller.ui,
            self.__document_controller,
            u.create_modeless_dialog(
                self.__handler.ui_view, title=_("Export SVG")
            ),
            self.__handler
        ))
        dialog.add_button(_("Cancel"), self.__cancel_clicked)
        dialog.add_button(_("Export"), self.__ok_clicked)
        dialog.show()

    def __ok_clicked(self) -> bool:
        pixel_shape = self.__model.pixel_shape
        ui = self.__document_controller.ui
        filter = "SVG File (*.svg);;All Files (*.*)"
        export_dir = ui.get_persistent_string("export_directory", ui.get_document_location())
        export_dir = os.path.join(export_dir, self.__display_item.displayed_title)
        path, selected_filter, selected_directory = self.__document_controller.get_save_file_path(
            _("Export File"), export_dir, filter, None
        )
        if path and not os.path.splitext(path)[1]:
            path = path + os.path.extsep + "svg"
        if path:
            ui.set_persistent_string("export_directory", selected_directory)
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
    file: str
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
            u.create_label(text=_('File'), font='bold', width=FILE_FIELD_WIDTH),
            u.create_label(text=_('Status'), font='bold', width=STATUS_FIELD_WIDTH),
        ]

        file_name_labels = list()
        status_labels = list()

        for export in self.exports:
            status_text = _("Succeeded") if not export.error else f"\N{WARNING SIGN} {export.error}"
            color = 'green' if not export.error else 'red'
            file_name_labels.append(u.create_label(text=export.file, tool_tip=export.file, width=FILE_FIELD_WIDTH))
            status_labels.append(u.create_label(text=status_text, tool_tip=export.error, color=color, width=STATUS_FIELD_WIDTH))

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

        path_directory = u.create_label(text=str(self.export_folder), min_width=280, height=48, word_wrap=True, size_policy_horizontal='min-expanding', text_alignment_vertical='top')

        path_goto = u.create_row(u.create_push_button(text='Open Directory', on_clicked='open_export_folder'),
                                 u.create_stretch())

        self.ui_view = u.create_column(path_title, path_directory, path_goto, header_row, data_row, spacing=8,
                                       margin=12)

    def ok_click(self) -> bool:
        return True

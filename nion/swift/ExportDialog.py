from __future__ import annotations


# standard libraries
import functools
import enum
import gettext
import logging
import operator
import os
import pathlib
import re
import traceback
import typing
import unicodedata

# third party libraries
# None

# local libraries
from nion.swift.model import DisplayItem
from nion.swift.model import ImportExportManager
from nion.swift.model import Utility
from nion.swift import DocumentController
from nion.swift import DisplayPanel
from nion.ui import Declarative
from nion.ui import Dialog
from nion.ui import UserInterface
from nion.ui import Window
from nion.utils import Converter
from nion.utils import Geometry
from nion.utils import Model

if typing.TYPE_CHECKING:
    from nion.swift.model import DisplayItem

_ = gettext.gettext

CM_PER_INCH = 2.54
PIXELS_PER_INCH = 96


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
            self.export_clicked(display_items, self.viewmodel)
            self.ui.set_persistent_string("export_io_handler_id", writer_id)
            return True

        # create the dialog and show it.
        dialog = typing.cast(Dialog.ActionDialog, Declarative.construct(document_controller.ui, document_controller, u.create_modeless_dialog(self.ui_view, title=_("Export")), self))
        dialog.add_button(_("Cancel"), self.cancel)
        dialog.add_button(_("Export"), handle_export_clicked)
        dialog.show()

    def choose_directory(self, widget: Declarative.UIWidget) -> None:
        directory = self.viewmodel.directory.value or str()
        existing_directory, directory = self.ui.get_existing_directory_dialog(_("Choose Export Directory"), directory)
        if existing_directory:
            self.viewmodel.directory.value = directory
            self.ui.set_persistent_string("export_directory", directory)

    def on_writer_changed(self, widget: Declarative.UIWidget, current_index: int) -> None:
        writer = self.__writers[current_index]
        self.viewmodel.writer.value = writer

    def _build_ui(self, u: Declarative.DeclarativeUI) -> None:
        writers_names = [getattr(writer, "name") for writer in self.__writers]

        # Export Folder
        directory_label = u.create_row(u.create_label(text="Location:"), u.create_stretch())
        directory_text = u.create_row(u.create_label(text=f"@binding(viewmodel.directory.value)", width=480), u.create_stretch())
        self.directory_text_label = directory_text
        directory_button = u.create_row(u.create_push_button(text=_("Select Path..."), on_clicked="choose_directory"), u.create_stretch())

        # Filename
        filename_label = u.create_row(u.create_label(text="Filename:"), u.create_stretch())

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
        prefix_checkbox = u.create_row(
            u.create_check_box(text="Include Prefix", checked=f"@binding(viewmodel.include_prefix.value)"), u.create_stretch())
        prefix_textbox = u.create_row(u.create_line_edit(text=f"@binding(viewmodel.prefix.value)", placeholder_text=_("None"), width=280), u.create_stretch())

        # File Type
        file_type_combobox = u.create_combo_box(
            items=writers_names,
            current_index=f"@binding(writer_index)",
            on_current_index_changed="on_writer_changed")
        file_type_row = u.create_row(u.create_label(text=_("File Format")), file_type_combobox, u.create_stretch())

        # Build final ui column
        column = u.create_column(directory_label,
                                 directory_text,
                                 directory_button,
                                 filename_label,
                                 file_type_row,
                                 title_checkbox,
                                 date_checkbox,
                                 dimension_checkbox,
                                 sequence_checkbox,
                                 prefix_checkbox,
                                 prefix_textbox,
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

        # check to see if filename is available, if so return that
        test_filepath = directory_path / pathlib.Path(filename).with_suffix(extension)
        if not test_filepath.exists():
            return test_filepath

        # file must already exist
        next_index = 1
        max_index = 9999
        last_test_filepath: typing.Optional[pathlib.Path] = None
        while next_index <= max_index:
            test_filepath = directory_path / pathlib.Path(f"{filename} {next_index}").with_suffix(extension)
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
    def export_clicked(display_items: typing.Sequence[DisplayItem.DisplayItem], viewmodel: ExportDialogViewModel) -> None:
        directory_path = pathlib.Path(viewmodel.directory.value or str())
        writer = viewmodel.writer
        if directory_path.is_dir() and writer and writer.value:
            for index, display_item in enumerate(display_items):
                data_item = display_item.data_item
                if data_item:
                    try:
                        components = list()
                        if viewmodel.include_prefix.value:
                            components.append(str(viewmodel.prefix.value))
                        if viewmodel.include_title.value:
                            title = unicodedata.normalize('NFKC', data_item.title)
                            title = re.sub(r'[^\w\s-]', '', title, flags=re.U).strip()
                            title = re.sub(r'[-\s]+', '-', title, flags=re.U)
                            components.append(title)
                        if viewmodel.include_date.value:
                            components.append(data_item.created_local.isoformat().replace(':', '').replace('.', '_'))
                        if viewmodel.include_dimensions.value:
                            components.append(
                                "x".join([str(shape_n) for shape_n in data_item.dimensional_shape]))
                        if viewmodel.include_sequence.value:
                            components.append(str(index))
                        filepath = ExportDialog.build_filepath(components, writer.value.extensions[0], directory_path=directory_path)
                        ImportExportManager.ImportExportManager().write_display_item_with_writer(writer.value, display_item, filepath)
                    except Exception as e:
                        logging.debug("Could not export image %s / %s", str(data_item), str(e))
                        traceback.print_exc()
                        traceback.print_stack()

    def cancel(self) -> bool:
        return True


class UnitType(enum.Enum):
    INCHES = 0
    CENTIMETERS = 1
    PIXELS = 2


class ExportSVGHandler:
    def __init__(self, display_size: Geometry.IntSize) -> None:
        self.display_size = display_size
        self.aspect_ratio = display_size.width / display_size.height
        self.initial_width = str(display_size.width)
        self.initial_height = str(display_size.height)
        self.unit_model = UnitType.PIXELS  # Default to pixels
        self.float_converter = Converter.FloatToStringConverter()
        self.previous_unit_index = UnitType.PIXELS
        self.size = Geometry.IntSize(0, 0)  # Changed from FloatSize to IntSize
        self.width_model = Model.PropertyModel(self.initial_width)
        self.height_model = Model.PropertyModel(self.initial_height)
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Width:"), width=80),
                u.create_line_edit(
                    text="@binding(width_model.value)",
                    on_text_edited="width_value_updated",
                    background_color="white",
                ),
                spacing=12
            ),
            u.create_row(
                u.create_label(text=_("Height:"), width=80),
                u.create_line_edit(
                    text="@binding(height_model.value)",
                    on_text_edited="height_value_updated",
                    background_color="white",
                ),
                spacing=12
            ),
            u.create_row(
                u.create_label(text=_("Units:"), width=80),
                u.create_combo_box(
                    items=[_("Inches"), _("Centimeters"), _("Pixels")],
                    current_index="@binding(unit_model.value)",
                    on_current_index_changed="unit_changed"
                ),
                spacing=12
            ),
            spacing=12,
            margin=12
        )

    def width_value_updated(self, widget: UserInterface.LineEditWidget, text: str) -> None:
        try:
            new_width = float(text)
            new_height = new_width / self.aspect_ratio
            if self.unit_model == UnitType.PIXELS:
                new_height = round(new_height)
            self.height_model.value = str(new_height)
        except ValueError:
            pass  # Handle the case where the input is not a valid number

    def height_value_updated(self, widget: UserInterface.LineEditWidget, text: str) -> None:
        try:
            new_height = float(text)
            new_width = new_height * self.aspect_ratio
            if self.unit_model == UnitType.PIXELS:
                new_width = round(new_width)
            self.width_model.value = str(new_width)
        except ValueError:
            pass  # Handle the case where the input is not a valid number

    def unit_changed(self, widget: UserInterface.ComboBoxWidget, current_index: int) -> None:
        new_unit_type = UnitType(current_index)
        width_text = self.width_model.value
        height_text = self.height_model.value

        self.size = self.convert_to_pixels(
            Geometry.FloatSize(height=float(height_text or 0),
                               width=float(width_text or 0)),
            self.previous_unit_index
        )
        newshape = self.convert_from_pixels(self.size, new_unit_type)

        if new_unit_type == UnitType.PIXELS:
            new_width:float = round(newshape.width)
            new_height:float = round(newshape.height)
        else:
            new_width = round(newshape.width, 6)
            new_height = round(newshape.height, 6)
        self.width_model.value = str(new_width)
        self.height_model.value = str(new_height)
        self.previous_unit_index = new_unit_type

    def convert_to_pixels(self, size: Geometry.FloatSize, unit_type: UnitType) -> Geometry.IntSize:
        if size.height is None or size.width is None:
            return Geometry.IntSize(0, 0)
        if unit_type == UnitType.INCHES:
            return Geometry.IntSize(height=int(size.height * PIXELS_PER_INCH), width=int(size.width * PIXELS_PER_INCH))
        elif unit_type == UnitType.CENTIMETERS:
            return Geometry.IntSize(height=int(size.height * PIXELS_PER_INCH / CM_PER_INCH),
                                    width=int(size.width * PIXELS_PER_INCH / CM_PER_INCH))
        return Geometry.IntSize(height=int(round(size.height)), width=int(round(size.height)))  # Pixels

    def convert_from_pixels(self, size: Geometry.IntSize, unit_type: UnitType) -> Geometry.FloatSize:
        if size.height is None or size.width is None:
            return Geometry.FloatSize(0.0, 0.0)
        if unit_type == UnitType.INCHES:
            return Geometry.FloatSize(height=size.height / PIXELS_PER_INCH, width=size.width / PIXELS_PER_INCH)
        elif unit_type == UnitType.CENTIMETERS:
            return Geometry.FloatSize(height=size.height * CM_PER_INCH / PIXELS_PER_INCH,
                                      width=size.width * CM_PER_INCH / PIXELS_PER_INCH)
        return Geometry.FloatSize(width=size.width, height=size.height)  # Pixels

    def close(self) -> None:
        pass


class ExportSVGDialog:
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()
        self.__document_controller = document_controller
        u = Declarative.DeclarativeUI()
        if display_item.display_data_shape and len(display_item.display_data_shape) == 2:
            display_size = Geometry.IntSize(height=display_item.display_data_shape[0],
                                            width=display_item.display_data_shape[1])
        else:
            display_size = Geometry.IntSize(height=3, width=5)
        handler = ExportSVGHandler(display_size)

        def ok_clicked() -> bool:
            display_shape = handler.convert_to_pixels(
                Geometry.FloatSize(
                    height=float(handler.height_model.value or 0),
                    width=float(handler.width_model.value or 0)
                ),
                handler.previous_unit_index
            )
            ui = document_controller.ui
            filter = "SVG File (*.svg);;All Files (*.*)"
            export_dir = ui.get_persistent_string("export_directory", ui.get_document_location())
            export_dir = os.path.join(export_dir, display_item.displayed_title)
            path, selected_filter, selected_directory = document_controller.get_save_file_path(_("Export File"),export_dir, filter, None)
            if path and not os.path.splitext(path)[1]:
                path = path + os.path.extsep + "svg"
            if path:
                ui.set_persistent_string("export_directory", selected_directory)
                document_controller.export_svg_file(DisplayPanel.DisplayPanelUISettings(ui), display_item,
                                                    display_shape, pathlib.Path(path))
            return True

        def cancel_clicked() -> bool:
            return True

        dialog = typing.cast(Dialog.ActionDialog, Declarative.construct(document_controller.ui, document_controller, u.create_modeless_dialog(handler.ui_view, title=_("Export SVG")), handler))
        dialog.add_button(_("Cancel"), cancel_clicked)
        dialog.add_button(_("Export"), ok_clicked)

        dialog.show()

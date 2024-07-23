from __future__ import annotations

# standard libraries
import dataclasses
import enum
import functools
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

PIXELS_PER_INCH = 96.0
PIXELS_PER_CM = 37.795275591


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
        writer = viewmodel.writer
        if directory_path.is_dir() and writer and writer.value:
            export_results = list()
            for index, display_item in enumerate(display_items):
                data_item = display_item.data_item
                if data_item:
                    file_name: str = ''
                    try:
                        components = list()
                        if viewmodel.prefix.value is not None and viewmodel.prefix.value != '':
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

                        file_name = filepath.name
                        data_metadata = data_item.data_metadata if data_item else None
                        if data_metadata is not None and writer.value.can_write(data_metadata, filepath.suffix[1:].lower()):
                            ImportExportManager.ImportExportManager().write_display_item_with_writer(writer.value, display_item, filepath)
                            export_results.append(ExportResult(file_name))
                        else:
                            error_message = _("Cannot export this data to file format")
                            export_results.append(ExportResult(file_name, f"{error_message} {writer.value.name}"))
                    except Exception as e:
                        logging.debug("Could not export image %s / %s", str(data_item), str(e))
                        traceback.print_exc()
                        traceback.print_stack()
                        export_results.append(ExportResult(file_name, str(e)))
                else:
                    export_results.append(ExportResult(display_item.displayed_title, _("Cannot export items with multiple data items")))

            if any(e.error for e in export_results):
                ExportResultDialog(ui, document_controller, export_results, directory_path)

    def cancel(self) -> bool:
        return True


class UnitType(enum.Enum):
    PIXELS = 0
    INCHES = 1
    CENTIMETERS = 2


ConversionUnits = {
    UnitType.PIXELS: 1,
    UnitType.CENTIMETERS: 37,
    UnitType.INCHES: 96
}


class ExportSizeModel(Observable.Observable):
    def __init__(self, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()
        display_size = self.__determine_display_size(display_item)
        self.__width: int = display_size.width
        self.__height: int = display_size.height
        self.__aspect_ratio = self.__width / self.__height
        self.__units = UnitType.PIXELS

    def __determine_display_size(self, display_item: DisplayItem.DisplayItem) -> Geometry.IntSize:
        if display_item.display_data_shape and len(display_item.display_data_shape) == 2:
            return Geometry.IntSize(height=display_item.display_data_shape[0], width=display_item.display_data_shape[1])
        return Geometry.IntSize(height=3, width=5)

    @property
    def width(self) -> float:
        return self.__convert_from_pixels(self.__width)

    @width.setter
    def width(self, new_width: float) -> None:
        self.__width = self.__convert_to_pixels(new_width)
        self.__height = int(self.__width / self.__aspect_ratio)
        self.notify_property_changed("width")
        self.notify_property_changed("height")

    @property
    def height(self) -> float:
        return self.__convert_from_pixels(self.__height)

    @height.setter
    def height(self, new_height: float) -> None:
        self.__height = self.__convert_to_pixels(new_height)
        self.__width = int(self.__height * self.__aspect_ratio)
        self.notify_property_changed("width")
        self.notify_property_changed("height")

    @property
    def units(self) -> int:
        return self.__units.value

    @units.setter
    def units(self, new_units: int) -> None:
        new_enum = UnitType(new_units)
        if self.__units != new_enum:
            self.__units = new_enum
            self.notify_property_changed("width")
            self.notify_property_changed("height")

    def __convert_to_pixels(self, value: float) -> int:
        return int(round(value * ConversionUnits[self.__units]))

    def __convert_from_pixels(self, value: int) -> float:
        return value / ConversionUnits[self.__units]


class ExportSVGHandler(Declarative.Handler):
    width_value_line_edit: UserInterface.LineEditWidget
    height_value_line_edit: UserInterface.LineEditWidget

    def __init__(self, model: ExportSizeModel) -> None:
        super().__init__()
        self.model = model  # Ensure model is an attribute of the handler
        u = Declarative.DeclarativeUI()
        self._float_to_string_converter = Converter.FloatToStringConverter()

        self.ui_view = u.create_column(
            u.create_row(
                u.create_label(text=_("Width:"), width=80),
                u.create_line_edit(
                    text="@binding(model.width, converter=_float_to_string_converter)",
                    on_text_edited="value_updated",
                    background_color="white",
                    name="width_value_line_edit"

                ),
                spacing=12
            ),
            u.create_row(
                u.create_label(text=_("Height:"), width=80),
                u.create_line_edit(
                    text="@binding(model.height, converter=_float_to_string_converter)",
                    on_text_edited="value_updated",
                    background_color="white",
                    name="height_value_line_edit"

                ),
                spacing=12
            ),
            u.create_row(
                u.create_label(text=_("Units:"), width=80),
                u.create_combo_box(
                    items=[_("Pixels"), _("Inches"), _("Centimeters")],
                    current_index="@binding(model.units)",
                ),
                spacing=12
            ),
            spacing=12,
            margin=12
        )

    def value_updated(self, widget: UserInterface.LineEditWidget, text: str) -> None:

        if widget == self.width_value_line_edit:
            self.height_value_line_edit.background_color = "lightgray"
            self.width_value_line_edit.background_color = "white"
        elif widget == self.height_value_line_edit:
            self.width_value_line_edit.background_color = "lightgray"
            self.height_value_line_edit.background_color = "white"


class ExportSVGDialog:
    def __init__(self, document_controller: DocumentController.DocumentController,
                 display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__model = ExportSizeModel(display_item)
        self.__handler = ExportSVGHandler(self.__model)
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
        display_shape = Geometry.IntSize(width=int(self.__model.width), height=int(self.__model.height))
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
                display_shape,
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

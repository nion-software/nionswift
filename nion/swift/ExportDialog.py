from __future__ import annotations

# standard libraries
import functools
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

        # set up values needed for the viewmodel
        io_handler_id = self.ui.get_persistent_string("export_io_handler_id", "png-io-handler")
        writer = ImportExportManager.ImportExportManager().get_writer_by_id(io_handler_id)
        directory = self.ui.get_persistent_string("export_directory", self.ui.get_document_location())

        # the viewmodel is the data model for the dialog. no other variables are needed.
        self.viewmodel = ExportDialogViewModel(True, True, True, True, writer, "", directory)

        # use this in the UI to display the current directory
        self.writer_index = 0
        self.__writers = ImportExportManager.ImportExportManager().get_writers()

        # build the UI
        u = Declarative.DeclarativeUI()
        self._build_ui(u)

        # create the dialog and show it.
        dialog = typing.cast(Dialog.ActionDialog, Declarative.construct(document_controller.ui, document_controller, u.create_modeless_dialog(self.ui_view, title=_("Export")), self))
        dialog.add_button(_("Cancel"), self.cancel)
        dialog.add_button(_("Export"), functools.partial(self.export_clicked, display_items, self.viewmodel))
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
        directory_label = u.create_row(u.create_label(text="Location:"))
        directory_text = u.create_row(u.create_label(text=f"@binding(viewmodel.directory.value)"))
        self.directory_text_label = directory_text
        directory_button = u.create_row(u.create_push_button(text=_("Select Path..."), on_clicked="choose_directory"))

        # Filename
        filename_label = u.create_row(u.create_label(text="Filename:"))

        # Title
        title_checkbox = u.create_row(
            u.create_check_box(text="Include Title", checked=f"@binding(viewmodel.include_title.value)"))

        # Date
        date_checkbox = u.create_row(
            u.create_check_box(text="Include Date", checked=f"@binding(viewmodel.include_date.value)"))

        # Dimensions
        dimension_checkbox = u.create_row(
            u.create_check_box(text="Include Dimensions", checked=f"@binding(viewmodel.include_dimensions.value)"))

        # Sequence Number
        sequence_checkbox = u.create_row(
            u.create_check_box(text="Include Sequence Number", checked=f"@binding(viewmodel.include_sequence.value)"))

        # Prefix
        prefix_checkbox = u.create_row(
            u.create_check_box(text="Include Prefix", checked=f"@binding(viewmodel.include_prefix.value)"))
        prefix_textbox = u.create_row(u.create_text_edit(text=f"@binding(viewmodel.prefix.value)"))

        # File Type
        file_type_combobox = u.create_combo_box(
            items=writers_names,
            current_index=f"@binding(writer_index)",
            on_current_index_changed="on_writer_changed")

        # Build final ui column
        column = u.create_column(directory_label,
                                 directory_text,
                                 directory_button,
                                 filename_label,
                                 title_checkbox,
                                 date_checkbox,
                                 dimension_checkbox,
                                 sequence_checkbox,
                                 prefix_checkbox,
                                 prefix_textbox,
                                 file_type_combobox,
                                 spacing=12, margin=12)
        self.ui_view = column

    @staticmethod
    def build_filename(components: typing.List[str], extension: str, path: str = "") -> str:
        # if path doesn't end in a directory character, add one
        if path:
            if not (path.endswith('/') or path.endswith('\\')):
                path = path + '/'

        # if extension doesn't start with a '.', add one so we always know it is there
        if not extension.startswith('.'):
            extension = '.' + extension

        # stick components together for the first part of the filename, underscore delimited excluding blank component
        filename = "_".join(s for s in components if s)

        # check to see if filename is available, if so return that
        test_filename = filename + extension
        if path:
            test_filename = path + test_filename

        if not os.path.exists(test_filename):
            return test_filename

        # file must already exist
        suffix = "($)"
        found_available = False
        next_index = 1
        max_index = 999
        while not found_available and next_index <= max_index:
            test_suffix = "({0})".format(next_index)
            test_filename = filename + test_suffix + extension
            if path:
                test_filename = path + test_filename
            if not os.path.exists(test_filename):
                return test_filename
            next_index = next_index + 1

        # Well we have no option here but to just go with the overwrite, either we ran out of index options or had none to begin with
        return test_filename

    @staticmethod
    def export_clicked(display_items: typing.Sequence[DisplayItem.DisplayItem], viewmodel: ExportDialogViewModel) -> bool:
        directory = viewmodel.directory.value
        writer = viewmodel.writer
        if directory and writer and writer.value:
            for index, display_item in enumerate(display_items):
                data_item = display_item.data_item
                if data_item:
                    try:
                        components = list()
                        if viewmodel.include_prefix.value: # self.options.get("prefix", False):
                            components.append(str(viewmodel.prefix.value)) # prefix_edit_widget.text))
                        if viewmodel.include_title.value:
                            title = unicodedata.normalize('NFKC', data_item.title)
                            title = re.sub(r'[^\w\s-]', '', title, flags=re.U).strip()
                            title = re.sub(r'[-\s]+', '-', title, flags=re.U)
                            components.append(title)
                        if viewmodel.include_date.value:
                            components.append(data_item.created_local.isoformat().replace(':', ''))
                        if viewmodel.include_dimensions.value:
                            components.append(
                                "x".join([str(shape_n) for shape_n in data_item.dimensional_shape]))
                        if viewmodel.include_sequence.value:
                            components.append(str(index))
                        filename = ExportDialog.build_filename(components, writer.value.extensions[0], path=directory)
                        ImportExportManager.ImportExportManager().write_display_item_with_writer(writer.value, display_item, pathlib.Path(filename))
                    except Exception as e:
                        logging.debug("Could not export image %s / %s", str(data_item), str(e))
                        traceback.print_exc()
                        traceback.print_stack()
        return True

    def cancel(self) -> bool:
        return True


class ExportSVGHandler:
    def __init__(self, display_size: Geometry.IntSize) -> None:
        self.width_model = Model.PropertyModel(display_size.width)
        self.height_model = Model.PropertyModel(display_size.height)

        self.int_converter = Converter.IntegerToStringConverter()

        u = Declarative.DeclarativeUI()
        width_row = u.create_row(u.create_label(text=_("Width (in)"), width=80), u.create_line_edit(text="@binding(width_model.value, converter=int_converter)"), spacing=12)
        height_row = u.create_row(u.create_label(text=_("Height (in)"), width=80), u.create_line_edit(text="@binding(height_model.value, converter=int_converter)"), spacing=12)
        main_page = u.create_column(width_row, height_row, spacing=12, margin=12)

        self.ui_view = main_page

    def close(self) -> None:
        pass


class ExportSVGDialog:

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()

        self.__document_controller = document_controller

        u = Declarative.DeclarativeUI()

        if display_item.display_data_shape and len(display_item.display_data_shape) == 2:
            display_size = Geometry.IntSize(height=4, width=4)
        else:
            display_size = Geometry.IntSize(height=3, width=4)

        handler = ExportSVGHandler(display_size)

        def ok_clicked() -> bool:
            dpi = 96
            width_px = (handler.width_model.value or display_size.width) * dpi
            height_px = (handler.height_model.value or display_size.height) * dpi

            ui = document_controller.ui
            filter = "SVG File (*.svg);;All Files (*.*)"
            export_dir = ui.get_persistent_string("export_directory", ui.get_document_location())
            export_dir = os.path.join(export_dir, display_item.displayed_title)
            path, selected_filter, selected_directory = document_controller.get_save_file_path(_("Export File"), export_dir, filter, None)
            if path and not os.path.splitext(path)[1]:
                path = path + os.path.extsep + "svg"
            if path:
                ui.set_persistent_string("export_directory", selected_directory)
                display_shape = Geometry.IntSize(height=height_px, width=width_px)
                document_controller.export_svg_file(DisplayPanel.DisplayPanelUISettings(ui), display_item, display_shape, pathlib.Path(path))
            return True

        def cancel_clicked() -> bool:
            return True

        dialog = typing.cast(Dialog.ActionDialog, Declarative.construct(document_controller.ui, document_controller, u.create_modeless_dialog(handler.ui_view, title=_("Export SVG")), handler))
        dialog.add_button(_("Cancel"), cancel_clicked)
        dialog.add_button(_("Export"), ok_clicked)

        dialog.show()

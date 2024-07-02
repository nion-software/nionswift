from __future__ import annotations

# standard libraries
import dataclasses
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
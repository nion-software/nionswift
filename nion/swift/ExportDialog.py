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


class ExportDialog(Dialog.OkCancelDialog):
    def __init__(self, ui: UserInterface.UserInterface, parent_window: Window.Window):
        super().__init__(ui, ok_title=_("Export"), parent_window=parent_window)

        io_handler_id = self.ui.get_persistent_string("export_io_handler_id", "png-io-handler")

        self.directory = self.ui.get_persistent_string("export_directory", self.ui.get_document_location())
        self.writer = ImportExportManager.ImportExportManager().get_writer_by_id(io_handler_id)

        directory_column = self.ui.create_column_widget()

        title_row = self.ui.create_row_widget()
        title_row.add_spacing(13)
        title_row.add(self.ui.create_label_widget(_("Export Folder: "), properties={"font": "bold"}))
        title_row.add_stretch()
        title_row.add_spacing(13)

        show_directory_row = self.ui.create_row_widget()
        show_directory_row.add_spacing(26)
        directory_label = self.ui.create_label_widget(self.directory)
        show_directory_row.add(directory_label)
        show_directory_row.add_stretch()
        show_directory_row.add_spacing(13)

        choose_directory_row = self.ui.create_row_widget()
        choose_directory_row.add_spacing(26)
        choose_directory_button = self.ui.create_push_button_widget(_("Choose..."))
        choose_directory_row.add(choose_directory_button)
        choose_directory_row.add_stretch()
        choose_directory_row.add_spacing(13)

        directory_column.add(title_row)
        directory_column.add(show_directory_row)
        directory_column.add(choose_directory_row)

        file_types_column = self.ui.create_column_widget()

        title_row = self.ui.create_row_widget()
        title_row.add_spacing(13)
        title_row.add(self.ui.create_label_widget(_("File Type: "), properties={"font": "bold"}))
        title_row.add_stretch()
        title_row.add_spacing(13)

        file_types_row = self.ui.create_row_widget()
        file_types_row.add_spacing(26)
        writers = ImportExportManager.ImportExportManager().get_writers()
        file_types_combo_box = self.ui.create_combo_box_widget(items=writers, item_getter=operator.attrgetter("name"))
        file_types_combo_box.current_item = self.writer
        file_types_row.add(file_types_combo_box)
        file_types_row.add_stretch()
        file_types_row.add_spacing(13)

        file_types_column.add(title_row)
        file_types_column.add(file_types_row)

        option_descriptions = [
            (_("Include Title"), "title", True),
            (_("Include Date"), "date", True),
            (_("Include Dimensions"), "dimensions", True),
            (_("Include Sequence Number"), "sequence", True),
            (_("Include Prefix:"), "prefix", False)
        ]

        self.options = dict()

        options_column = self.ui.create_column_widget()

        title_row = self.ui.create_row_widget()
        title_row.add_spacing(13)
        title_row.add(self.ui.create_label_widget(_("Filename: "), properties={"font": "bold"}))
        title_row.add_stretch()
        title_row.add_spacing(13)

        individual_options_column = self.ui.create_column_widget()
        for option_decription in option_descriptions:
            label, option_id, default_value = option_decription
            self.options[option_id] = self.ui.get_persistent_string("export_option_" + option_id,
                                                                    str(default_value)).lower() == "true"
            check_box_widget = self.ui.create_check_box_widget(label)
            check_box_widget.checked = self.options[option_id]

            def checked_changed(option_id_: str, checked: bool) -> None:
                self.options[option_id_] = checked
                self.ui.set_persistent_string("export_option_" + option_id_, str(checked))

            check_box_widget.on_checked_changed = functools.partial(checked_changed, option_id)
            individual_options_column.add_spacing(4)
            individual_options_column.add(check_box_widget)
            if option_id == "prefix":
                self.prefix_edit_widget = self.ui.create_text_edit_widget(properties={"max-height": 35})
                individual_options_column.add(self.prefix_edit_widget)

        options_row = self.ui.create_row_widget()
        options_row.add_spacing(26)
        options_row.add(individual_options_column)
        options_row.add_stretch()
        options_row.add_spacing(13)

        options_column.add(title_row)
        options_column.add(options_row)

        column = self.ui.create_column_widget()
        column.add_spacing(12)
        column.add(directory_column)
        column.add_spacing(4)
        column.add(options_column)
        column.add_spacing(4)
        column.add(file_types_column)
        column.add_spacing(16)
        column.add_stretch()

        def choose() -> None:
            existing_directory, directory = self.ui.get_existing_directory_dialog(_("Choose Export Directory"),
                                                                                  self.directory)
            if existing_directory:
                self.directory = existing_directory
                directory_label.text = self.directory
                self.ui.set_persistent_string("export_directory", self.directory)

        choose_directory_button.on_clicked = choose

        def writer_changed(writer: ImportExportManager.ImportExportHandler) -> None:
            self.ui.set_persistent_string("export_io_handler_id", writer.io_handler_id)
            self.writer = writer

        file_types_combo_box.on_current_item_changed = writer_changed

        self.content.add(column)

    def do_export(self, display_items: typing.Sequence[DisplayItem.DisplayItem]) -> None:
        directory = self.directory
        writer = self.writer
        if directory and writer:
            for index, display_item in enumerate(display_items):
                data_item = display_item.data_item
                if data_item:
                    try:
                        components = list()
                        if self.options.get("prefix", False):
                            components.append(str(self.prefix_edit_widget.text))
                        if self.options.get("title", False):
                            title = unicodedata.normalize('NFKC', data_item.title)
                            title = re.sub(r'[^\w\s-]', '', title, flags=re.U).strip()
                            title = re.sub(r'[-\s]+', '-', title, flags=re.U)
                            components.append(title)
                        if self.options.get("date", False):
                            components.append(data_item.created_local.isoformat().replace(':', ''))
                        if self.options.get("dimensions", False):
                            components.append(
                                "x".join([str(shape_n) for shape_n in data_item.dimensional_shape]))
                        if self.options.get("sequence", False):
                            components.append(str(index))
                        filename = "_".join(components)
                        extension = writer.extensions[0]
                        path = os.path.join(directory, "{0}.{1}".format(filename, extension))
                        ImportExportManager.ImportExportManager().write_display_item_with_writer(writer, display_item, pathlib.Path(path))
                    except Exception as e:
                        logging.debug("Could not export image %s / %s", str(data_item), str(e))
                        traceback.print_exc()
                        traceback.print_stack()


class ExportSVGHandler:
    def __init__(self, display_item: DisplayItem.DisplayItem, display_size: Geometry.IntSize) -> None:
        self.display_item = display_item

        self.width_model = Model.PropertyModel(display_size.width)
        self.height_model = Model.PropertyModel(display_size.height)
        self.units = Model.PropertyModel(0)
        self.int_converter = Converter.IntegerToStringConverter()

        u = Declarative.DeclarativeUI()

        height_row = u.create_row(u.create_label(text=_("Height: "), width=80), u.create_line_edit(text="@binding(height_model.value, converter=int_converter)"),
                                  u.create_combo_box(items=["Inches", "Centimeters","Pixels"],
                                                     current_index="@binding(units.value)"), spacing=12)
        main_page = u.create_column(height_row, spacing=12, margin=12)

        self.ui_view = main_page

    def close(self) -> None:
        pass


class ExportSVGDialog:

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()

        self.__document_controller = document_controller

        u = Declarative.DeclarativeUI()

        display_item = display_item.snapshot()
        display_properties = display_item.display_properties
        display_properties["image_zoom"] = 1.0
        display_properties["image_position"] = (0.5, 0.5)
        display_properties["image_canvas_mode"] = "fit"
        display_item.display_properties = display_properties

        if display_item.display_data_shape and len(display_item.display_data_shape) == 2:
            display_size = Geometry.IntSize(height=4, width=4)
        else:
            display_size = Geometry.IntSize(height=3, width=4)

        handler = ExportSVGHandler(display_item, display_size)

        def ok_clicked() -> bool:
            pixels_per_unit: float = 96.0
            if handler.units.value == 1:
                pixels_per_unit = 37.7953
            elif handler.units.value == 2:
                pixels_per_unit = 1

            if display_item.display_data_shape is not None:
                display_item_ratio = display_item.display_data_shape[1] / display_item.display_data_shape[0]
            else:
                display_item_ratio = 1

            height_value = handler.height_model.value
            if height_value is not None:
                height_px = int(height_value * pixels_per_unit)
            else:
                # Handle the case where height_model.value is None
                height_px = 0  # or any other default value
            width_px = int(height_px * display_item_ratio)
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

# standard libraries
import functools
import gettext
import logging
import operator
import os
import re
import traceback
import unicodedata

# third party libraries
# None

# local libraries
from nion.swift.model import ImportExportManager
from nion.ui import Dialog

_ = gettext.gettext


class ExportDialog(Dialog.OkCancelDialog):
    def __init__(self, ui):
        super(ExportDialog, self).__init__(ui, ok_title=_("Export"))

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
            [_("Include Title"), "title", True],
            [_("Include Date"), "date", True],
            [_("Include Dimensions"), "dimensions", True],
            [_("Include Sequence Number"), "sequence", True],
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

            def checked_changed(option_id_, checked):
                self.options[option_id_] = checked
                self.ui.set_persistent_string("export_option_" + option_id_, str(checked))

            check_box_widget.on_checked_changed = functools.partial(checked_changed, option_id)
            individual_options_column.add_spacing(4)
            individual_options_column.add(check_box_widget)

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

        def writer_changed(writer) -> None:
            self.ui.set_persistent_string("export_io_handler_id", writer.io_handler_id)
            self.writer = writer

        file_types_combo_box.on_current_item_changed = writer_changed

        self.content.add(column)

    def do_export(self, data_items):
        directory = self.directory
        writer = self.writer
        if directory:
            for index, data_item in enumerate(data_items):
                try:
                    components = list()
                    if self.options.get("title", False):
                        title = unicodedata.normalize('NFKC', data_item.title)
                        title = re.sub('[^\w\s-]', '', title, flags=re.U).strip()
                        title = re.sub('[-\s]+', '-', title, flags=re.U)
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
                    ImportExportManager.ImportExportManager().write_data_items_with_writer(self.ui, writer, data_item,
                                                                                           path)
                except Exception as e:
                    logging.debug("Could not export image %s / %s", str(data_item), str(e))
                    traceback.print_exc()
                    traceback.print_stack()

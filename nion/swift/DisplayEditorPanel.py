# standard libraries
import copy
import functools
import gettext
import operator
import random
import string
import uuid
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DataItemThumbnailWidget
from nion.swift.model import DataItem
from nion.swift.model import Symbolic
from nion.ui import CanvasItem
from nion.ui import Dialog
from nion.utils import Binding
from nion.utils import Converter
from nion.utils import Event
from nion.utils import Geometry

_ = gettext.gettext


class DisplayEditorDialog(Dialog.ActionDialog):

    def __init__(self, document_controller, data_item):
        ui = document_controller.ui
        super().__init__(ui, _("Edit Display"), app=document_controller.app, parent_window=document_controller, persistent_id="EditDisplayDialog" + str(data_item.uuid))

        self.ui = ui
        self.document_controller = document_controller
        self.__display = data_item.maybe_data_source.displays[0]

        self._create_menus()

        text_edit_row = ui.create_row_widget()
        text_edit = ui.create_text_edit_widget(properties={"stylesheet": "min-width: 480; min-height: 200"})
        text_edit.placeholder_text = _("No Display Script")
        text_edit_row.add_spacing(8)
        text_edit_row.add(text_edit)
        text_edit_row.add_spacing(8)

        error_row = ui.create_row_widget(properties={"stylesheet": "min-width: 120"})  # the stylesheet allows it to shrink. guh.
        error_label = ui.create_label_widget("\n", properties={"stylesheet": "color: red; min-width: 120"})
        error_label.word_wrap = True
        error_row.add_spacing(8)
        error_row.add(error_label)
        error_row.add_spacing(8)

        update_button = ui.create_push_button_widget(_("Update"))
        button_row = ui.create_row_widget()
        button_row.add_stretch()
        button_row.add_spacing(8)
        button_row.add(update_button)
        button_row.add_spacing(8)

        def update_pressed():
            if text_edit.text:
                self.__display.display_script = text_edit.text
            else:
                self.__display.display_script = None

        def clear():
            text_edit.text = None

        update_button.on_clicked = update_pressed

        column = self.content
        column.add_spacing(6)
        column.add(text_edit_row)
        column.add_spacing(6)
        column.add(error_row)
        column.add_spacing(6)
        column.add(button_row)
        column.add_spacing(6)

        self.__error_label = error_label
        self.__text_edit = text_edit

        text_edit.text = self.__display.display_script

    def size_changed(self, width, height):
        self.__error_label.size = Geometry.IntSize(height=self.__error_label.size.height, width=self.__text_edit.size.width)

from __future__ import annotations

# standard libraries
import gettext
import typing

# third party libraries
# None

# local libraries
from nion.swift import DisplayPanel
from nion.ui import Dialog
from nion.utils import Geometry

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import DisplayItem

_ = gettext.gettext


class DisplayEditorDialog(Dialog.ActionDialog):

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        ui = document_controller.ui
        super().__init__(ui, _("Edit Display"), parent_window=document_controller, persistent_id="EditDisplayDialog" + str(display_item.uuid))

        self.ui = ui
        self.document_controller = document_controller

        # sizing in widget space (Qt) is difficult to get right and there seems to be bugs.
        # in this case, two different elements are used to effectively make a minimum window
        # size -- the text edit widget for the height and the error row for the width.
        # if both are done on the text edit widget itself, which would be preferred, Qt seems
        # to give up on layout when the scroll bar appears for too many lines.

        text_edit_row = ui.create_row_widget(properties={"min-height": 180})
        text_edit = ui.create_text_edit_widget()
        text_edit.placeholder = _("No Display Script")
        text_edit_row.add_spacing(8)
        text_edit_row.add(text_edit)
        text_edit_row.add_spacing(8)

        error_row = ui.create_row_widget(properties={"min-width": 320})  # the stylesheet allows it to shrink. guh.
        error_label = ui.create_label_widget("\n", properties={"min-width": 120})
        error_label.text_color = "red"
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

        def update_pressed() -> None:
            display_script = text_edit.text if text_edit.text else None
            command = DisplayPanel.ChangeDisplayCommand(document_controller.document_model, display_item, title=_("Change Display Script"), display_script=display_script)
            command.perform()
            document_controller.push_undo_command(command)

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

        text_edit.text = display_item.get_display_property("display_script")

    def size_changed(self, width: int, height: int) -> None:
        self.__error_label.size = Geometry.IntSize(height=self.__error_label.size.height, width=self.__text_edit.size.width)

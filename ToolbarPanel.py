# standard libraries
import gettext
import logging
import threading

# third party libraries
# None

# local libraries
from nion.swift.Decorators import ProcessingThread
from nion.swift import DataItem
from nion.swift import DocumentController
from nion.swift import Panel
from nion.ui import CanvasItem

_ = gettext.gettext


class ToolbarPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(ToolbarPanel, self).__init__(document_controller, panel_id, _("Toolbar"))

        self.widget = self.ui.create_column_widget()

        toolbar_row_widget = self.ui.create_row_widget()

        crop_tool_button = self.ui.create_push_button_widget(_("Crop Tool"))

        line_profile_tool_button = self.ui.create_push_button_widget(_("Line Profile Tool"))

        toggle_filter_button = self.ui.create_push_button_widget(_("Toggle Filter"))
        toggle_filter_button.on_clicked = lambda: document_controller.toggle_filter_action.trigger()

        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(crop_tool_button)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(line_profile_tool_button)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(toggle_filter_button)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add_stretch()

        self.widget.add_spacing(8)
        self.widget.add(toolbar_row_widget)
        self.widget.add_spacing(8)

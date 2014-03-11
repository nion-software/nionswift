# standard libraries
import gettext
import logging
import threading

# third party libraries
import numpy

# local libraries
from nion.swift import DataItem
from nion.swift.Decorators import relative_file
from nion.swift import DocumentController
from nion.swift import Panel
from nion.ui import CanvasItem

_ = gettext.gettext


class ToolbarPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(ToolbarPanel, self).__init__(document_controller, panel_id, _("Toolbar"))

        self.widget = self.ui.create_column_widget()

        toolbar_row_widget = self.ui.create_row_widget()

        # see https://www.iconfinder.com

        pointer_tool_button = self.ui.create_push_button_widget()
        pointer_tool_button.tool_tip = _("Pointer Tool")
        pointer_tool_button.icon = self.ui.load_rgba_data_from_file(":/Graphics/pointer_icon.png")
        pointer_tool_button.on_clicked = lambda: setattr(document_controller, "tool_mode", "pointer")

        hand_tool_button = self.ui.create_push_button_widget()
        hand_tool_button.tool_tip = _("Hand Tool")
        hand_tool_button.icon = self.ui.load_rgba_data_from_file(":/Graphics/hand_icon.png")
        hand_tool_button.on_clicked = lambda: setattr(document_controller, "tool_mode", "hand")

        crop_tool_button = self.ui.create_push_button_widget()
        crop_tool_button.tool_tip = _("Crop Tool")
        crop_tool_button.icon = self.ui.load_rgba_data_from_file(":/Graphics/crop_icon.png")
        crop_tool_button.on_clicked = lambda: setattr(document_controller, "tool_mode", "crop")

        line_profile_tool_button = self.ui.create_push_button_widget()
        line_profile_tool_button.tool_tip = _("Line Profile Tool")
        line_profile_tool_button.icon = self.ui.load_rgba_data_from_file(":/Graphics/line_profile_icon.png")
        line_profile_tool_button.on_clicked = lambda: setattr(document_controller, "tool_mode", "line-profile")

        new_group_button = self.ui.create_push_button_widget()
        new_group_button.tool_tip = _("New Group")
        new_group_button.icon = self.ui.load_rgba_data_from_file(":/Graphics/new_group_icon.png")
        new_group_button.on_clicked = lambda: document_controller.add_group_action.trigger()

        delete_button = self.ui.create_push_button_widget()
        delete_button.tool_tip = _("Delete")
        delete_button.icon = self.ui.load_rgba_data_from_file(":/Graphics/delete_icon.png")
        delete_button.on_clicked = lambda: document_controller.delete_action.trigger()

        export_button = self.ui.create_push_button_widget()
        export_button.tool_tip = _("Export")
        export_button.icon = self.ui.load_rgba_data_from_file(":/Graphics/export_icon.png")
        export_button.on_clicked = lambda: document_controller.export_action.trigger()

        fit_view_button = self.ui.create_push_button_widget()
        fit_view_button.text = _("Fit")
        fit_view_button.icon = numpy.zeros((24, 1), dtype=numpy.uint32)
        fit_view_button.on_clicked = lambda: document_controller.fit_view_action.trigger()

        fill_view_button = self.ui.create_push_button_widget()
        fill_view_button.text = _("Fill")
        fill_view_button.icon = numpy.zeros((24, 1), dtype=numpy.uint32)
        fill_view_button.on_clicked = lambda: document_controller.fill_view_action.trigger()

        one_view_button = self.ui.create_push_button_widget()
        one_view_button.text = _("1:1")
        one_view_button.icon = numpy.zeros((24, 1), dtype=numpy.uint32)
        one_view_button.on_clicked = lambda: document_controller.one_to_one_view_action.trigger()

        toggle_filter_button = self.ui.create_push_button_widget()
        toggle_filter_button.tool_tip = _("Toggle Filter Panel")
        toggle_filter_button.icon = self.ui.load_rgba_data_from_file(":/Graphics/filter_icon.png")
        toggle_filter_button.on_clicked = lambda: document_controller.toggle_filter_action.trigger()

        tool_group_widget = self.ui.create_row_widget()
        tool_group_widget.add(pointer_tool_button)
        tool_group_widget.add(hand_tool_button)
        tool_group_widget.add(crop_tool_button)
        tool_group_widget.add(line_profile_tool_button)

        commands_group_widget = self.ui.create_row_widget()
        commands_group_widget.add(new_group_button)
        commands_group_widget.add(delete_button)
        commands_group_widget.add(export_button)

        view_group_widget = self.ui.create_row_widget()
        view_group_widget.add(fit_view_button)
        view_group_widget.add(fill_view_button)
        view_group_widget.add(one_view_button)

        filter_group_widget = self.ui.create_row_widget()
        filter_group_widget.add(toggle_filter_button)

        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(tool_group_widget)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(commands_group_widget)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(view_group_widget)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(filter_group_widget)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add_stretch()

        self.widget.add(toolbar_row_widget)

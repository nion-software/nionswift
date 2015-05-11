# standard libraries
import gettext

# third party libraries
import numpy

# local libraries
from nion.swift import Panel
from nion.ui import CanvasItem
from nion.ui import Geometry

_ = gettext.gettext


class ToolbarPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(ToolbarPanel, self).__init__(document_controller, panel_id, _("Toolbar"))

        self.widget = self.ui.create_column_widget()

        toolbar_row_widget = self.ui.create_row_widget()

        # see https://www.iconfinder.com

        ui = document_controller.ui

        icon_size = Geometry.IntSize(height=24, width=32)
        border_color = "#CCC"

        margins = Geometry.Margins(left=2, right=2, top=3, bottom=3)

        self.tool_palette_canvas_item = CanvasItem.RootCanvasItem(ui, properties={"height": 54, "width": 164})
        self.tool_palette_canvas_item.layout = CanvasItem.CanvasItemGridLayout(size=Geometry.IntSize(height=2, width=5), margins=margins)

        pointer_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/pointer_icon.png"), border_color=border_color)
        pointer_tool_button.size = icon_size

        hand_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/hand_icon.png"), border_color=border_color)
        hand_tool_button.size = icon_size

        line_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/line_icon.png"), border_color=border_color)
        line_tool_button.size = icon_size

        rectangle_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/rectangle_icon.png"), border_color=border_color)
        rectangle_tool_button.size = icon_size

        ellipse_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/ellipse_icon.png"), border_color=border_color)
        ellipse_tool_button.size = icon_size

        point_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/point_icon.png"), border_color=border_color)
        point_tool_button.size = icon_size

        line_profile_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/line_profile_icon.png"), border_color=border_color)
        line_profile_tool_button.size = icon_size

        interval_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(":/Graphics/interval_icon.png"), border_color=border_color)
        interval_tool_button.size = icon_size

        self.tool_palette_canvas_item.add_canvas_item(pointer_tool_button, Geometry.IntPoint(x=0, y=0))
        self.tool_palette_canvas_item.add_canvas_item(hand_tool_button, Geometry.IntPoint(x=0, y=1))
        self.tool_palette_canvas_item.add_canvas_item(line_tool_button, Geometry.IntPoint(x=1, y=0))
        self.tool_palette_canvas_item.add_canvas_item(ellipse_tool_button, Geometry.IntPoint(x=1, y=1))
        self.tool_palette_canvas_item.add_canvas_item(rectangle_tool_button, Geometry.IntPoint(x=2, y=0))
        self.tool_palette_canvas_item.add_canvas_item(point_tool_button, Geometry.IntPoint(x=2, y=1))
        self.tool_palette_canvas_item.add_canvas_item(line_profile_tool_button, Geometry.IntPoint(x=3, y=0))
        self.tool_palette_canvas_item.add_canvas_item(interval_tool_button, Geometry.IntPoint(x=3, y=1))

        modes = "pointer", "hand", "line", "rectangle", "ellipse", "point", "line-profile", "interval"
        self.__tool_button_group = CanvasItem.RadioButtonGroup([pointer_tool_button, hand_tool_button, line_tool_button, rectangle_tool_button, ellipse_tool_button, point_tool_button, line_profile_tool_button, interval_tool_button])
        self.__tool_button_group.current_index = modes.index(document_controller.tool_mode)
        self.__tool_button_group.on_current_index_changed = lambda index: setattr(document_controller, "tool_mode", modes[index])

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
        tool_group_widget.add(self.tool_palette_canvas_item.canvas_widget)

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

# futures
from __future__ import absolute_import

# standard libraries
import gettext
import weakref

# third party libraries
import numpy

# local libraries
from nion.swift import Decorators
from nion.swift import Panel
from nion.ui import CanvasItem
from nion.utils import Geometry

_ = gettext.gettext


class ToolbarPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(ToolbarPanel, self).__init__(document_controller, panel_id, _("Toolbar"))

        self.widget = self.ui.create_column_widget()

        toolbar_row_widget = self.ui.create_row_widget()

        # see https://www.iconfinder.com

        ui = document_controller.ui

        document_controller_weak_ref = weakref.ref(document_controller)

        icon_size = Geometry.IntSize(height=24, width=32)
        border_color = "#CCC"

        margins = Geometry.Margins(left=2, right=2, top=3, bottom=3)

        tool_palette_grid_canvas_item = CanvasItem.CanvasItemComposition()
        tool_palette_grid_canvas_item.layout = CanvasItem.CanvasItemGridLayout(size=Geometry.IntSize(height=2, width=6), margins=margins)

        pointer_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/pointer_icon.png")), border_color=border_color)
        pointer_tool_button.size = icon_size
        pointer_tool_button.tool_tip = _("Pointer tool for selecting graphics")

        hand_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/hand_icon.png")), border_color=border_color)
        hand_tool_button.size = icon_size
        hand_tool_button.tool_tip = _("Hand tool for dragging images within panel")

        line_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/line_icon.png")), border_color=border_color)
        line_tool_button.size = icon_size
        line_tool_button.tool_tip = _("Line tool for making line regions on images")

        rectangle_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/rectangle_icon.png")), border_color=border_color)
        rectangle_tool_button.size = icon_size
        rectangle_tool_button.tool_tip = _("Rectangle tool for making rectangle regions on images")

        ellipse_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/ellipse_icon.png")), border_color=border_color)
        ellipse_tool_button.size = icon_size
        ellipse_tool_button.tool_tip = _("Ellipse tool for making ellipse regions on images")

        point_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/point_icon.png")), border_color=border_color)
        point_tool_button.size = icon_size
        point_tool_button.tool_tip = _("Point tool for making point regions on images")

        line_profile_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/line_profile_icon.png")), border_color=border_color)
        line_profile_tool_button.size = icon_size
        line_profile_tool_button.tool_tip = _("Line profile tool for making line profiles on images")

        interval_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/interval_icon.png")), border_color=border_color)
        interval_tool_button.size = icon_size
        interval_tool_button.tool_tip = _("Interval tool for making intervals on line plots")

        spot_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/spot_icon.png")), border_color=border_color)
        spot_tool_button.size = icon_size
        spot_tool_button.tool_tip = _("Spot tool for making spots on radial images")

        wedge_tool_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/wedge_icon.png")), border_color=border_color)
        wedge_tool_button.size = icon_size
        wedge_tool_button.tool_tip = _("Angle tool for specifying arcs on radial images")

        ring_tool_button = CanvasItem.BitmapButtonCanvasItem( ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/annular_ring.png")), border_color=border_color)
        ring_tool_button.size = icon_size
        ring_tool_button.tool_tip = _("Ring tool for selecting ranges on radial images")

        tool_palette_grid_canvas_item.add_canvas_item(pointer_tool_button, Geometry.IntPoint(x=0, y=0))
        tool_palette_grid_canvas_item.add_canvas_item(hand_tool_button, Geometry.IntPoint(x=0, y=1))
        tool_palette_grid_canvas_item.add_canvas_item(line_tool_button, Geometry.IntPoint(x=1, y=0))
        tool_palette_grid_canvas_item.add_canvas_item(ellipse_tool_button, Geometry.IntPoint(x=1, y=1))
        tool_palette_grid_canvas_item.add_canvas_item(rectangle_tool_button, Geometry.IntPoint(x=2, y=0))
        tool_palette_grid_canvas_item.add_canvas_item(point_tool_button, Geometry.IntPoint(x=2, y=1))
        tool_palette_grid_canvas_item.add_canvas_item(line_profile_tool_button, Geometry.IntPoint(x=3, y=0))
        tool_palette_grid_canvas_item.add_canvas_item(interval_tool_button, Geometry.IntPoint(x=3, y=1))
        tool_palette_grid_canvas_item.add_canvas_item(spot_tool_button, Geometry.IntPoint(x=4, y=0))
        tool_palette_grid_canvas_item.add_canvas_item(wedge_tool_button, Geometry.IntPoint(x=4, y=1))
        tool_palette_grid_canvas_item.add_canvas_item(ring_tool_button, Geometry.IntPoint(x=5, y=0))

        modes = "pointer", "hand", "line", "rectangle", "ellipse", "point", "line-profile", "interval", "spot", "wedge", "ring"
        self.__tool_button_group = CanvasItem.RadioButtonGroup([pointer_tool_button, hand_tool_button, line_tool_button, rectangle_tool_button, ellipse_tool_button, point_tool_button, line_profile_tool_button, interval_tool_button, spot_tool_button, wedge_tool_button, ring_tool_button])
        def tool_mode_changed(tool_mode):
            self.__tool_button_group.current_index = modes.index(tool_mode)
        self.__tool_mode_changed_event_listener = document_controller.tool_mode_changed_event.listen(tool_mode_changed)
        self.__tool_button_group.current_index = modes.index(document_controller.tool_mode)
        self.__tool_button_group.on_current_index_changed = lambda index: setattr(document_controller_weak_ref(), "tool_mode", modes[index])
        tool_mode_changed(document_controller.tool_mode)

        new_group_button = self.ui.create_push_button_widget()
        new_group_button.tool_tip = _("New Group")
        new_group_button.icon = self.ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/new_group_icon.png"))
        new_group_button.on_clicked = lambda: document_controller_weak_ref()._add_group_action.trigger()

        delete_button = self.ui.create_push_button_widget()
        delete_button.tool_tip = _("Delete")
        delete_button.icon = self.ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/delete_icon.png"))
        delete_button.on_clicked = lambda: document_controller_weak_ref()._delete_action.trigger()

        export_button = self.ui.create_push_button_widget()
        export_button.tool_tip = _("Export")
        export_button.icon = self.ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/export_icon.png"))
        export_button.on_clicked = lambda: document_controller_weak_ref()._export_action.trigger()

        view_palette_grid_canvas_item = CanvasItem.CanvasItemComposition()
        view_palette_grid_canvas_item.layout = CanvasItem.CanvasItemGridLayout(size=Geometry.IntSize(height=2, width=2), margins=margins)

        fit_view_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/fit_icon.png")), border_color=border_color)
        fit_view_button.size = icon_size
        fit_view_button.on_button_clicked = lambda: document_controller_weak_ref()._fit_view_action.trigger()
        fit_view_button.tool_tip = _("Zoom to fit to enclosing space")

        fill_view_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/fill_icon.png")), border_color=border_color)
        fill_view_button.size = icon_size
        fill_view_button.on_button_clicked = lambda: document_controller_weak_ref()._fill_view_action.trigger()
        fill_view_button.tool_tip = _("Zoom to fill enclosing space")

        one_to_one_view_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/1x1_icon.png")), border_color=border_color)
        one_to_one_view_button.size = icon_size
        one_to_one_view_button.on_button_clicked = lambda: document_controller_weak_ref()._one_to_one_view_action.trigger()
        one_to_one_view_button.tool_tip = _("Zoom to one image pixel per screen pixel")

        two_to_one_view_button = CanvasItem.BitmapButtonCanvasItem(ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/2x1_icon.png")), border_color=border_color)
        two_to_one_view_button.size = icon_size
        two_to_one_view_button.on_button_clicked = lambda: document_controller_weak_ref()._two_to_one_view_action.trigger()
        two_to_one_view_button.tool_tip = _("Zoom to two image pixels per screen pixel")

        view_palette_grid_canvas_item.add_canvas_item(fit_view_button, Geometry.IntPoint(x=0, y=0))
        view_palette_grid_canvas_item.add_canvas_item(fill_view_button, Geometry.IntPoint(x=0, y=1))
        view_palette_grid_canvas_item.add_canvas_item(one_to_one_view_button, Geometry.IntPoint(x=1, y=0))
        view_palette_grid_canvas_item.add_canvas_item(two_to_one_view_button, Geometry.IntPoint(x=1, y=1))

        toggle_filter_button = self.ui.create_push_button_widget()
        toggle_filter_button.tool_tip = _("Toggle Filter Panel")
        toggle_filter_button.icon = self.ui.load_rgba_data_from_file(Decorators.relative_file(__file__, "resources/filter_icon.png"))
        toggle_filter_button.on_clicked = lambda: document_controller_weak_ref()._toggle_filter_action.trigger()

        tool_palette_widget = ui.create_canvas_widget(properties={"height": 54, "width": 164})
        tool_palette_widget.canvas_item.add_canvas_item(tool_palette_grid_canvas_item)

        tool_group_widget = self.ui.create_row_widget()
        tool_group_widget.add(tool_palette_widget)

        commands_group_widget = self.ui.create_row_widget()
        commands_group_widget.add(new_group_button)
        commands_group_widget.add(delete_button)
        commands_group_widget.add(export_button)

        view_palette_widget = ui.create_canvas_widget(properties={"height": 54, "width": 68})
        view_palette_widget.canvas_item.add_canvas_item(view_palette_grid_canvas_item)

        view_group_widget = self.ui.create_row_widget()
        view_group_widget.add(view_palette_widget)

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

    def close(self):
        self.__tool_mode_changed_event_listener.close()
        self.__tool_mode_changed_event_listener = None

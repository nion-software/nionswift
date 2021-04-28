# standard libraries
import gettext
import pkgutil
import typing
import weakref

# third party libraries
# None

# local libraries
from nion.swift import DocumentController
from nion.swift import Panel
from nion.ui import CanvasItem
from nion.ui import Declarative
from nion.ui import Window
from nion.utils import Geometry
from nion.utils import Model
from nion.utils import Registry

_ = gettext.gettext


class ToolModeToolbarWidget:
    toolbar_widget_id = "nion.swift.tool-mode"

    def __init__(self, *, document_controller: DocumentController.DocumentController, **kwargs):
        self.radio_button_value: Model.PropertyModel[int] = Model.PropertyModel(0)

        u = Declarative.DeclarativeUI()

        top_row_items = list()
        bottom_row_items = list()
        modes = list()

        tool_actions = list()

        for action in Window.actions.values():
            if action.action_id.startswith("window.set_tool_mode"):
                tool_actions.append(typing.cast(DocumentController.SetToolModeAction, action))

        for i, tool_action in enumerate(tool_actions):
            tool_id = tool_action.tool_mode
            icon_png = tool_action.tool_icon
            tool_tip = tool_action.tool_tip
            key_shortcut = Window.action_shortcuts.get(tool_action.action_id, dict()).get("display_panel", None)
            if key_shortcut:
                tool_tip += f" ({key_shortcut})"
            modes.append(tool_id)
            assert icon_png is not None
            icon_data = CanvasItem.load_rgba_data_from_bytes(icon_png)
            icon_property = "icon_" + tool_id
            setattr(self, icon_property, icon_data)
            radio_button = u.create_radio_button(icon=f"@binding({icon_property})", value=i,
                                                 group_value="@binding(radio_button_value.value)", width=32, height=24,
                                                 tool_tip=tool_tip)
            if i % 2 == 0:
                top_row_items.append(radio_button)
            else:
                bottom_row_items.append(radio_button)

        top_row = u.create_row(*top_row_items)
        bottom_row = u.create_row(*bottom_row_items)

        self.ui_view = u.create_column(u.create_spacing(4), top_row, bottom_row, u.create_spacing(4), u.create_stretch())

        self.radio_button_value.value = modes.index(document_controller.tool_mode)

        def tool_mode_changed(tool_mode: str) -> None:
            self.radio_button_value.value = modes.index(tool_mode)

        self.__tool_mode_changed_event_listener = document_controller.tool_mode_changed_event.listen(tool_mode_changed)

        tool_mode_changed(document_controller.tool_mode)

        def radio_button_changed(property: str):
            if property == "value":
                mode_index = self.radio_button_value.value
                if mode_index is not None:
                    document_controller.tool_mode = modes[mode_index]

        self.__radio_button_value_listener = self.radio_button_value.property_changed_event.listen(radio_button_changed)

    def close(self) -> None:
        self.__tool_mode_changed_event_listener.close()
        self.__tool_mode_changed_event_listener = None


Registry.register_component(ToolModeToolbarWidget, {"toolbar-widget"})


class ToolbarPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, _("Toolbar"))

        self.__component_registered_listener = Registry.listen_component_registered_event(self.__component_registered)

        self.widget = self.ui.create_column_widget()

        # see https://www.iconfinder.com

        ui = document_controller.ui

        document_controller_weak_ref = weakref.ref(document_controller)

        icon_size = Geometry.IntSize(height=24, width=32)
        border_color = "#CCC"

        margins = Geometry.Margins(left=2, right=2, top=3, bottom=3)

        new_group_button = self.ui.create_push_button_widget()
        new_group_button.tool_tip = _("New Group")
        new_group_button.icon = CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/new_group_icon.png"))
        new_group_button.on_clicked = lambda: document_controller_weak_ref().perform_action("project.add_group")

        delete_button = self.ui.create_push_button_widget()
        delete_button.tool_tip = _("Delete")
        delete_button.icon = CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/delete_icon.png"))
        delete_button.on_clicked = lambda: document_controller_weak_ref().perform_action("window.delete")

        export_button = self.ui.create_push_button_widget()
        export_button.tool_tip = _("Export")
        export_button.icon = CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/export_icon.png"))
        export_button.on_clicked = lambda: document_controller_weak_ref().perform_action("file.export")

        view_palette_grid_canvas_item = CanvasItem.CanvasItemComposition()
        view_palette_grid_canvas_item.layout = CanvasItem.CanvasItemGridLayout(size=Geometry.IntSize(height=2, width=2), margins=margins)

        fit_view_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/fit_icon.png")), border_color=border_color)
        fit_view_button.size = icon_size
        fit_view_button.on_button_clicked = lambda: document_controller_weak_ref()._fit_view_action.trigger()
        fit_view_button.tool_tip = _("Zoom to fit to enclosing space")

        fill_view_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/fill_icon.png")), border_color=border_color)
        fill_view_button.size = icon_size
        fill_view_button.on_button_clicked = lambda: document_controller_weak_ref()._fill_view_action.trigger()
        fill_view_button.tool_tip = _("Zoom to fill enclosing space")

        one_to_one_view_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/1x1_icon.png")), border_color=border_color)
        one_to_one_view_button.size = icon_size
        one_to_one_view_button.on_button_clicked = lambda: document_controller_weak_ref()._one_to_one_view_action.trigger()
        one_to_one_view_button.tool_tip = _("Zoom to one image pixel per screen pixel")

        two_to_one_view_button = CanvasItem.BitmapButtonCanvasItem(CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/2x1_icon.png")), border_color=border_color)
        two_to_one_view_button.size = icon_size
        two_to_one_view_button.on_button_clicked = lambda: document_controller_weak_ref()._two_to_one_view_action.trigger()
        two_to_one_view_button.tool_tip = _("Zoom to two image pixels per screen pixel")

        view_palette_grid_canvas_item.add_canvas_item(fit_view_button, Geometry.IntPoint(x=0, y=0))
        view_palette_grid_canvas_item.add_canvas_item(fill_view_button, Geometry.IntPoint(x=0, y=1))
        view_palette_grid_canvas_item.add_canvas_item(one_to_one_view_button, Geometry.IntPoint(x=1, y=0))
        view_palette_grid_canvas_item.add_canvas_item(two_to_one_view_button, Geometry.IntPoint(x=1, y=1))

        toggle_filter_button = self.ui.create_push_button_widget()
        toggle_filter_button.tool_tip = _("Toggle Filter Panel")
        toggle_filter_button.icon = CanvasItem.load_rgba_data_from_bytes(pkgutil.get_data(__name__, "resources/filter_icon.png"))
        toggle_filter_button.on_clicked = lambda: document_controller_weak_ref()._toggle_filter_action.trigger()

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

        toolbar_row_widget = self.ui.create_row_widget()
        toolbar_row_widget.add_spacing(12)
        # note: "maximum" here means the size hint is maximum and the widget can be smaller. Qt layout is atrocious.
        self.__toolbar_widget_row = self.ui.create_row_widget(properties={"size-policy-horizontal": "maximum"})
        toolbar_row_widget.add(self.__toolbar_widget_row)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(commands_group_widget)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(view_group_widget)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(filter_group_widget)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add_stretch()

        self.widget.add(toolbar_row_widget)

        # handle any components that have already been registered.
        for component in Registry.get_components_by_type("toolbar-widget"):
            self.__component_registered(component, {"toolbar-widget"})

    def close(self):
        self.__component_registered_listener.close()
        self.__component_registered_listener = None
        super().close()

    def __component_registered(self, component, component_types: typing.Set[str]) -> None:
        if "toolbar-widget" in component_types:
            self.__toolbar_widget_row.add_spacing(12)
            self.__toolbar_widget_row.add(Declarative.DeclarativeWidget(self.ui, self.document_controller.event_loop, component(document_controller=self.document_controller)))

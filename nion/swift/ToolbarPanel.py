# standard libraries
import gettext
import typing

# third party libraries
# None

# local libraries
import numpy
from nion.swift import DocumentController
from nion.swift import Panel
from nion.ui import CanvasItem
from nion.ui import Declarative
from nion.ui import UserInterface
from nion.ui import Window
from nion.utils import Model
from nion.utils import Registry

_ = gettext.gettext


class ToolModeToolbarWidget:
    toolbar_widget_id = "nion.swift.toolbar-widget.tool-mode"
    toolbar_widget_title = _("Tools")

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


class ActionTableToolbarWidget:

    def __init__(self, actions: typing.Sequence[Window.Action], document_controller: DocumentController.DocumentController, **kwargs):
        self.__document_controller = document_controller
        u = Declarative.DeclarativeUI()
        top_row = [self.__create_action_button(actions[i]) for i in range(0, len(actions), 2)]
        bottom_row = [self.__create_action_button(actions[i]) for i in range(1, len(actions), 2)]
        self.ui_view = u.create_column(u.create_spacing(4),
                                       u.create_row(*top_row),
                                       u.create_row(*bottom_row),
                                       u.create_spacing(4), u.create_stretch())

    def __create_action_button(self, action: Window.Action) -> Declarative.UIDescription:
        action_id = action.action_id
        action_identifier = action_id.replace(".", "_")
        icon_png = getattr(action, "action_command_icon_png", None)
        if icon_png is not None:
            icon_data = CanvasItem.load_rgba_data_from_bytes(icon_png)
        else:
            icon_data = numpy.full((48, 64), 0x00FFFFFF, dtype=numpy.uint32)
            icon_data[8:40, 8:56] = 0xFFC0C0C0
        icon_property = "icon_" + action_identifier
        setattr(self, icon_property, icon_data)
        tool_tip = getattr(action, "action_tool_tip", getattr(action, "action_name", None))
        key_shortcut = Window.action_shortcuts.get(action_id, dict()).get("display_panel", None)
        if tool_tip and key_shortcut:
            tool_tip += f" ({key_shortcut})"
        u = Declarative.DeclarativeUI()
        perform_function = "perform_" + action_identifier
        def perform_action(widget: UserInterface.Widget) -> None:
            self.__document_controller.perform_action(action_id)
        setattr(self, perform_function, perform_action)
        return u.create_image(image=f"@binding({icon_property})", height=24, width=32, on_clicked=f"{perform_function}", tool_tip=tool_tip)


class RasterZoomToolbarWidget(ActionTableToolbarWidget):
    toolbar_widget_id = "nion.swift.toolbar-widget.raster-zoom"
    toolbar_widget_title = _("Zoom")  # ideally "Raster Zoom" but that makes the title wider than the controls

    def __init__(self, *, document_controller: DocumentController.DocumentController, **kwargs):
        super().__init__(
            [
                Window.actions["display_panel.fit_view"],
                Window.actions["display_panel.1_view"],
                Window.actions["display_panel.fill_view"],
                Window.actions["display_panel.2_view"],
            ],
            document_controller,
            **kwargs
        )


class WorkspaceToolbarWidget(ActionTableToolbarWidget):
    toolbar_widget_id = "nion.swift.toolbar-widget.workspace"
    toolbar_widget_title = _("Workspace")

    def __init__(self, *, document_controller: DocumentController.DocumentController, **kwargs):
        super().__init__(
            [
                Window.actions["workspace.split_horizontal"],
                Window.actions["workspace.split_vertical"],
                Window.actions["workspace.split_2x2"],
                Window.actions["workspace.split_3x2"],
                Window.actions["workspace.split_3x3"],
                Window.actions["workspace.split_4x3"],
                Window.actions["workspace.split_4x4"],
                Window.actions["workspace.split_5x4"],
                Window.actions["display_panel.select_siblings"],
                Window.actions["display_panel.clear"],
                Window.actions["workspace.1x1"],
                Window.actions["display_panel.close"],
            ],
            document_controller,
            **kwargs
        )


Registry.register_component(ToolModeToolbarWidget, {"toolbar-widget"})
Registry.register_component(RasterZoomToolbarWidget, {"toolbar-widget"})
Registry.register_component(WorkspaceToolbarWidget, {"toolbar-widget"})


class ToolbarPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super().__init__(document_controller, panel_id, _("Toolbar"))

        self.__component_registered_listener = Registry.listen_component_registered_event(self.__component_registered)

        self.widget = self.ui.create_column_widget()

        # note: "maximum" here means the size hint is maximum and the widget can be smaller. Qt layout is atrocious.
        self.__toolbar_widget_row = self.ui.create_row_widget(properties={"size-policy-horizontal": "maximum"})

        toolbar_row_widget = self.ui.create_row_widget()
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add(self.__toolbar_widget_row)
        toolbar_row_widget.add_spacing(12)
        toolbar_row_widget.add_stretch()

        self.widget.add(toolbar_row_widget)

        # make a map from widget_id to widget factory.
        widget_factories = dict()
        for component in Registry.get_components_by_type("toolbar-widget"):
            widget_factories[component.toolbar_widget_id] = component

        # define the order of widgets.
        # this part is hard coded for now; needs some work to make it dynamically order widgets as they become
        # available from packages.
        widget_id_list = [
            "nion.swift.toolbar-widget.tool-mode",
            "nion.swift.toolbar-widget.raster-zoom",
            "nion.swift.toolbar-widget.workspace"
        ]

        # add the widgets.
        for widget_id in widget_id_list:
            self.__toolbar_widget_row.add_spacing(12)
            widget_factory = widget_factories[widget_id]
            widget_handler = widget_factory(document_controller=self.document_controller)
            widget = Declarative.DeclarativeWidget(self.ui, self.document_controller.event_loop, widget_handler)
            widget_section_label = self.ui.create_label_widget(widget_handler.toolbar_widget_title)
            widget_section_label.text_color = "darkgrey"  # this is actually light gray due to an error in html specs at w3
            widget_section = self.ui.create_column_widget()
            widget_section.add(widget_section_label, alignment="left")
            widget_section.add(widget, alignment="left")
            self.__toolbar_widget_row.add(widget_section)

    def close(self):
        self.__component_registered_listener.close()
        self.__component_registered_listener = None
        super().close()

    def __component_registered(self, component, component_types: typing.Set[str]) -> None:
        if "toolbar-widget" in component_types:
            self.__toolbar_widget_row.add_spacing(12)
            self.__toolbar_widget_row.add(Declarative.DeclarativeWidget(self.ui, self.document_controller.event_loop, component(document_controller=self.document_controller)))

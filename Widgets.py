"""
A library of custom widgets.
"""

# standard libraries
# None

# third party libraries
# None

# local libraries
from nion.ui import CanvasItem


class CompositeWidgetBase:
    def __init__(self, content_widget):
        assert content_widget is not None
        self.__root_container = None  # the document window
        self.__content_widget = content_widget

    # subclasses should override to clear their variables.
    def close(self):
        self.__root_container = None

    @property
    def widget(self):
        """Pass through the widget for UI hosts that use it."""
        return self.__content_widget.widget

    @property
    def content_widget(self):
        return self.__content_widget

    @property
    def root_container(self):
        return self.__root_container

    def _set_root_container(self, root_container):
        self.__root_container = root_container

    # not thread safe
    def periodic(self):
        self.__content_widget.periodic()

    # thread safe
    # tasks are run periodically. if another task causes a widget to close,
    # the outstanding task may try to use a closed widget. any methods called
    # in a task need to verify that the widget is not yet closed. this can be
    # mitigated in several ways: 1) clear the task if possible; 2) do not queue
    # the task if widget is already closed; 3) check during task to make sure
    # widget was not already closed.
    def add_task(self, key, task):
        root_container = self.root_container
        if root_container:
            root_container.add_task(key + str(id(self)), task)

    # thread safe
    def clear_task(self, key):
        root_container = self.root_container
        if root_container:
            root_container.clear_task(key + str(id(self)))

    # thread safe
    def queue_task(self, task):
        root_container = self.root_container
        if root_container:
            root_container.queue_task(task)

    @property
    def focused(self):
        return self.__content_widget.focused

    @focused.setter
    def focused(self, focused):
        if focused != self.focused:
            self.__content_widget.focused = focused

    @property
    def visible(self):
        return self.__content_widget.visible

    @visible.setter
    def visible(self, visible):
        if visible != self.visible:
            self.__content_widget.visible = visible

    @property
    def enabled(self):
        return self.__content_widget.enabled

    @enabled.setter
    def enabled(self, enabled):
        if enabled != self.enabled:
            self.__content_widget.enabled = enabled

    @property
    def size(self):
        raise NotImplementedError()

    @size.setter
    def size(self, size):
        raise NotImplementedError()

    @property
    def tool_tip(self):
        return self.__content_widget.tool_tip

    @tool_tip.setter
    def tool_tip(self, tool_tip):
        if tool_tip != self.tool_tip:
            self.__delegate.tool_tip = tool_tip

    def drag(self, mime_data, thumbnail=None, hot_spot_x=None, hot_spot_y=None, drag_finished_fn=None):
        self.__content_widget.drag(mime_data, thumbnail, hot_spot_x, hot_spot_y, drag_finished_fn)

    def map_to_global(self, p):
        return self.__content_widget.map_to_global(p)


class SectionWidget(CompositeWidgetBase):
    """A widget representing a twist down section.

    The section is composed of a title in bold and then content.
    """

    def __init__(self, ui, section_title: str, section, section_id: str=None):
        super().__init__(ui.create_column_widget())

        section_widget = self.content_widget

        section_title_row = ui.create_row_widget()

        twist_down_canvas_item = CanvasItem.TwistDownCanvasItem()

        twist_down_canvas_widget = ui.create_canvas_widget_new(properties={"height": 20, "width": 20})
        twist_down_canvas_widget.canvas_item.add_canvas_item(twist_down_canvas_item)

        section_title_row.add(twist_down_canvas_widget)
        section_title_row.add(ui.create_label_widget(section_title, properties={"stylesheet": "font-weight: bold"}))
        section_title_row.add_stretch()
        section_widget.add(section_title_row)
        section_content_row = ui.create_row_widget()
        section_content_column = ui.create_column_widget()
        section_content_column.add_spacing(4)
        section_content_column.add(section)
        section_content_column.add_stretch()
        section_content_row.add_spacing(20)
        section_content_row.add(section_content_column)
        section_widget.add(section_content_row)
        section_widget.add_spacing(4)

        def toggle():
            twist_down_canvas_item.checked = not twist_down_canvas_item.checked
            section_content_column.visible = twist_down_canvas_item.checked
            if section_id:
                ui.set_persistent_string(section_id, "true" if twist_down_canvas_item.checked else "false")
        section_open = ui.get_persistent_string(section_id, "true") == "true" if section_id else True
        twist_down_canvas_item.checked = section_open
        section_content_column.visible = section_open
        twist_down_canvas_item.on_button_clicked = toggle

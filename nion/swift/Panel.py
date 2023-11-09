from __future__ import annotations

# standard libraries
import collections
import dataclasses
import functools
import gettext
import logging
import sys
import threading
import typing
import weakref

# third party libraries
# None

# local libraries
from nion.swift.model import Utility
from nion.ui import Application
from nion.ui import CanvasItem
from nion.ui import Declarative
from nion.ui import UserInterface
from nion.utils import Geometry
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import Persistence
    from nion.swift.model import UISettings
    from nion.ui import DrawingContext

_DocumentControllerWeakRefType = typing.Callable[[], "DocumentController.DocumentController"]

_ = gettext.gettext


class Panel:
    """
        Represents content within a dock widget. The dock widget owns
        the panel and will invoke close and periodic on it. The dock
        widget expects the widget property to contain the ui content.
    """
    count = 0  # useful for detecting leaks in tests

    @classmethod
    def get_monospace_text_font(cls) -> str:
        if sys.platform == "darwin":
            return "11px monospace"
        else:
            return "12px monospace"

    @classmethod
    def get_monospace_proportional_line_height(cls) -> float:
        return 1.1

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, display_name: str) -> None:
        Panel.count += 1
        self.__weak_document_controller = typing.cast(_DocumentControllerWeakRefType, weakref.ref(document_controller))
        self.ui = document_controller.ui
        self.panel_id = panel_id
        self.display_name = display_name
        self.widget = typing.cast(UserInterface.Widget, None)  # gets closed by the dock widget
        self.dock_widget = typing.cast(UserInterface.DockWidget, None)

    # subclasses can override to clean up when the panel closes.
    def close(self) -> None:
        if self.dock_widget:
            # added to a dock widget, closing dock widget will close the widget
            self.dock_widget.close()
        else:
            # never added to a dock widget, so explicitly close
            self.widget.close()
        self.widget = typing.cast(UserInterface.Widget, None)  # closed by the dock_widget
        Panel.count -= 1

    def create_dock_widget(self, title: str, positions: typing.Sequence[str], position: str) -> None:
        self.dock_widget = self.document_controller.create_dock_widget(self.widget, self.panel_id, title, positions, position)
        self.dock_widget.on_size_changed = self.size_changed
        self.dock_widget.on_focus_changed = self.focus_changed
        self.dock_widget.on_ui_activity = self.document_controller._register_ui_activity

    @property
    def document_controller(self) -> DocumentController.DocumentController:
        return self.__weak_document_controller()

    # not thread safe. always call from main thread.
    def periodic(self) -> None:
        self.dock_widget.periodic()

    def show(self) -> None:
        self.dock_widget.show()

    def hide(self) -> None:
        self.dock_widget.hide()

    # tasks can be added in two ways, queued or added
    # queued tasks are guaranteed to be executed in the order queued.
    # added tasks are only executed if not replaced before execution.
    # added tasks do not guarantee execution order or execution at all.

    def add_task(self, key: str, task: typing.Callable[[], None]) -> None:
        self.document_controller.add_task(key + str(id(self)), task)

    def clear_task(self, key: str) -> None:
        self.document_controller.clear_task(key + str(id(self)))

    def queue_task(self, task: typing.Callable[[], None]) -> None:
        self.document_controller.queue_task(task)

    def clear_queued_tasks(self) -> None:
        self.document_controller.clear_queued_tasks()

    def size_changed(self, width: int, height: int) -> None:
        pass

    def focus_changed(self, focused: bool) -> None:
        if focused:
            self.document_controller.request_refocus()

    def __str__(self) -> str:
        return self.display_name


class OutputPanel(Panel):

    __count = 0
    __old_stdout: typing.Optional[typing.TextIO] = None
    __old_stderr: typing.Optional[typing.TextIO] = None
    __stdout_listeners: typing.Dict[OutputPanel, typing.Callable[[str], None]] = dict()
    __stderr_listeners: typing.Dict[OutputPanel, typing.Callable[[str], None]] = dict()

    @classmethod
    def initialize(cls) -> None:
        """Configure standard output."""
        cls.__old_stdout = sys.stdout
        cls.__old_stderr = sys.stderr

        stdout_listeners = cls.__stdout_listeners

        class StdoutCatcher:
            def __init__(self, out: typing.TextIO) -> None:
                self.__out = out
            def write(self, stuff: typing.Any) -> None:
                for stdout_listener in stdout_listeners.values():
                    stdout_listener(stuff)
                self.__out.write(stuff)
            def flush(self) -> None:
                self.__out.flush()
            def getvalue(self) -> typing.Any:
                return typing.cast(typing.Any, self.__out).getvalue()
            @property
            def delegate(self) -> typing.Any:
                return typing.cast(typing.Any, self.__out).delegate

        # TODO: these casts are clearly wrong. spend more time in the future on this.
        sys.stdout = typing.cast(typing.TextIO, StdoutCatcher(cls.__old_stdout))
        sys.stderr = typing.cast(typing.TextIO, StdoutCatcher(cls.__old_stderr))

    @classmethod
    def deinitialize(cls) -> None:
        cls.__stdout_listeners = dict()
        cls.__stderr_listeners = dict()
        assert cls.__old_stdout
        assert cls.__old_stderr
        sys.stdout = cls.__old_stdout
        sys.stderr = cls.__old_stderr

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, "Output")
        properties["min-height"] = 180
        text_edit_widget = self.ui.create_text_edit_widget(properties)
        self.widget = text_edit_widget
        text_edit_widget.set_text_font(Panel.get_monospace_text_font())
        text_edit_widget.set_line_height_proportional(Panel.get_monospace_proportional_line_height())
        self.__lock = threading.RLock()
        self.__q = collections.deque()  # type: ignore  # Python 3.9+: collections.deque[str]

        def safe_emit() -> None:
            with self.__lock:
                while len(self.__q) > 0:
                    text_edit_widget.move_cursor_position("end")
                    text_edit_widget.append_text(self.__q.popleft())

        def queue_message(message: str) -> None:
            with self.__lock:
                self.__q.append(message.strip())
            if threading.current_thread().name == "MainThread":
                safe_emit()
            else:
                self.document_controller.queue_task(safe_emit)

        class OutputPanelHandler(logging.Handler):

            def __init__(self, queue_message_fn: typing.Callable[[str], None], records: typing.Sequence[logging.LogRecord]) -> None:
                super().__init__()
                self.queue_message_fn = queue_message_fn
                for record in records or list():
                    self.emit(record)

            def emit(self, record: logging.LogRecord) -> None:
                if record.levelno >= logging.INFO:
                    self.queue_message_fn(record.getMessage())

        self.__output_panel_handler = OutputPanelHandler(queue_message, Application.logging_handler.take_records())

        logging.getLogger().addHandler(self.__output_panel_handler)

        if OutputPanel.__count == 0:
            OutputPanel.initialize()

        OutputPanel.__stdout_listeners[self] = queue_message
        OutputPanel.__stderr_listeners[self] = queue_message

        OutputPanel.__count += 1

    def close(self) -> None:
        OutputPanel.__count -= 1
        OutputPanel.__stdout_listeners.pop(self)
        OutputPanel.__stderr_listeners.pop(self)

        if OutputPanel.__count == 0:
            OutputPanel.deinitialize()

        logging.getLogger().removeHandler(self.__output_panel_handler)
        super().close()


class HeaderCanvasItem(CanvasItem.CanvasItemComposition):

    # header_height = 20 if sys.platform == "win32" else 22

    def __init__(self, ui_settings: UISettings.UISettings, title: typing.Optional[str] = None,
                 label: typing.Optional[str] = None, display_close_control: bool = False) -> None:
        super().__init__()
        self.wants_mouse_events = True
        self.__title = title if title else ""
        self.__label = label if label else ""
        self.__display_close_control = display_close_control
        self.__ui_settings = ui_settings
        self.__set_default_style()
        self.update_sizing(self.sizing.with_fixed_height(self.header_height))
        self.on_select_pressed: typing.Optional[typing.Callable[[], None]] = None
        self.on_drag_pressed: typing.Optional[typing.Callable[[], None]] = None
        self.on_close_clicked: typing.Optional[typing.Callable[[], None]] = None
        self.on_context_menu_clicked: typing.Optional[typing.Callable[[int, int, int, int], bool]] = None
        self.on_double_clicked: typing.Optional[typing.Callable[[int, int, UserInterface.KeyboardModifiers], bool]] = None
        self.on_tool_tip: typing.Optional[typing.Callable[[], typing.Optional[str]]] = None
        self.__mouse_pressed_position: typing.Optional[Geometry.IntPoint] = None

    def close(self) -> None:
        self.on_select_pressed = None
        self.on_drag_pressed = None
        self.on_close_clicked = None
        self.on_context_menu_clicked = None
        self.__ui_settings = typing.cast(typing.Any, None)
        super().close()

    def __set_default_style(self) -> None:
        if sys.platform == "win32":
            self.__font = 'normal 11px system serif'
            self.__top_offset = 1
            self.__text_offset = 4
            self.__start_header_color = "#d9d9d9"
            self.__end_header_color = "#d9d9d9"
            self.__top_stroke_style = '#b8b8b8'
            self.__side_stroke_style = '#b8b8b8'
            self.__bottom_stroke_style = '#b8b8b8'
            self.__control_style = '#000000'
        else:
            self.__font = 'normal 10pt system serif'
            self.__top_offset = 0
            self.__text_offset = 7
            self.__start_header_color = "#ededed"
            self.__end_header_color = "#cacaca"
            self.__top_stroke_style = '#ffffff'
            self.__bottom_stroke_style = '#b0b0b0'
            self.__side_stroke_style = None
            self.__control_style = '#808080'

    def __str__(self) -> str:
        return self.__title

    @property
    def header_height(self) -> int:
        return self.__ui_settings.get_font_metrics(self.__font, "abc").height + 3 + self.__text_offset

    @property
    def title(self) -> str:
        return self.__title

    @title.setter
    def title(self, title: str) -> None:
        if self.__title != title:
            self.__title = title
            self.update()

    @property
    def label(self) -> str:
        return self.__label

    @label.setter
    def label(self, label: str) -> None:
        if self.__label != label:
            self.__label = label
            self.update()

    @property
    def start_header_color(self) -> str:
        return self.__start_header_color

    @start_header_color.setter
    def start_header_color(self, start_header_color: str) -> None:
        if self.__start_header_color != start_header_color:
            self.__start_header_color = start_header_color
            self.update()

    @property
    def end_header_color(self) -> str:
        return self.__end_header_color

    @end_header_color.setter
    def end_header_color(self, end_header_color: str) -> None:
        if self.__end_header_color != end_header_color:
            self.__end_header_color = end_header_color
            self.update()

    def reset_header_colors(self) -> None:
        self.__set_default_style()
        self.update()

    def mouse_entered(self) -> bool:
        if callable(self.on_tool_tip):
            self.tool_tip = self.on_tool_tip()
        return super().mouse_entered()

    def mouse_exited(self) -> bool:
        self.tool_tip = None
        return super().mouse_exited()

    def mouse_pressed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        self.__mouse_pressed_position = Geometry.IntPoint(y=y, x=x)
        return True

    def mouse_double_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if callable(self.on_double_clicked):
            return self.on_double_clicked(x, y, modifiers)
        return False

    def mouse_position_changed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        pt = Geometry.FloatPoint(y=y, x=x)
        mouse_pressed_pos = self.__mouse_pressed_position
        if mouse_pressed_pos and Geometry.distance(mouse_pressed_pos.to_float_point(), pt) > 12:
            on_drag_pressed = self.on_drag_pressed
            if callable(on_drag_pressed):
                self.__mouse_pressed_position = None
                on_drag_pressed()
                return True
        return False

    def mouse_released(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        canvas_size = self.canvas_size
        select_ok = self.__mouse_pressed_position is not None
        if canvas_size and self.__display_close_control:
            close_box_left = canvas_size.width - (20 - 4)
            close_box_right = canvas_size.width - (20 - 18)
            close_box_top = 2
            close_box_bottom = canvas_size.height - 2
            if x > close_box_left and x < close_box_right and y > close_box_top and y < close_box_bottom:
                on_close_clicked = self.on_close_clicked
                if callable(on_close_clicked):
                    on_close_clicked()
                    select_ok = False
        if select_ok:
            on_select_pressed = self.on_select_pressed
            if callable(on_select_pressed):
                on_select_pressed()
        self.__mouse_pressed_position = None
        return True

    def context_menu_event(self, x: int, y: int, gx: int, gy: int) -> bool:
        if callable(self.on_context_menu_clicked):
            return self.on_context_menu_clicked(x, y, gx, gy)
        return False

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        canvas_size = self.canvas_size
        if canvas_size:
            with drawing_context.saver():
                drawing_context.begin_path()
                drawing_context.move_to(0, 1)
                drawing_context.line_to(0, canvas_size.height)
                drawing_context.line_to(canvas_size.width, canvas_size.height)
                drawing_context.line_to(canvas_size.width, 1)
                drawing_context.close_path()
                gradient = drawing_context.create_linear_gradient(canvas_size.width, canvas_size.height, 0, 0, 0, canvas_size.height)
                gradient.add_color_stop(0, self.__start_header_color)
                gradient.add_color_stop(1, self.__end_header_color)
                drawing_context.fill_style = gradient
                drawing_context.fill()

            with drawing_context.saver():
                drawing_context.begin_path()
                # line is adjust 1/2 pixel down to align to pixel boundary
                drawing_context.move_to(0, 0.5 + self.__top_offset)
                drawing_context.line_to(canvas_size.width, 0.5 + self.__top_offset)
                drawing_context.stroke_style = self.__top_stroke_style
                drawing_context.stroke()

            with drawing_context.saver():
                drawing_context.begin_path()
                # line is adjust 1/2 pixel down to align to pixel boundary
                drawing_context.move_to(0, canvas_size.height-0.5)
                drawing_context.line_to(canvas_size.width, canvas_size.height-0.5)
                drawing_context.stroke_style = self.__bottom_stroke_style
                drawing_context.stroke()

            if self.__side_stroke_style:
                with drawing_context.saver():
                    drawing_context.begin_path()
                    # line is adjust 1/2 pixel down to align to pixel boundary
                    drawing_context.move_to(0.5, 1.5)
                    drawing_context.line_to(0.5, canvas_size.height - 0.5)
                    drawing_context.move_to(canvas_size.width - 0.5, 1.5)
                    drawing_context.line_to(canvas_size.width - 0.5, canvas_size.height - 0.5)
                    drawing_context.stroke_style = self.__side_stroke_style
                    drawing_context.stroke()

            if self.__display_close_control:
                with drawing_context.saver():
                    drawing_context.begin_path()
                    close_box_left = canvas_size.width - (20 - 7)
                    close_box_right = canvas_size.width - (20 - 13)
                    close_box_top = canvas_size.height // 2 - 3
                    close_box_bottom = canvas_size.height // 2 + 3
                    drawing_context.move_to(close_box_left, close_box_top)
                    drawing_context.line_to(close_box_right, close_box_bottom)
                    drawing_context.move_to(close_box_left, close_box_bottom)
                    drawing_context.line_to(close_box_right, close_box_top)
                    drawing_context.line_width = 1.5
                    drawing_context.line_cap = "round"
                    drawing_context.stroke_style = self.__control_style
                    drawing_context.stroke()

            with drawing_context.saver():
                drawing_context.font = self.__font
                drawing_context.text_align = 'left'
                drawing_context.text_baseline = 'bottom'
                drawing_context.fill_style = '#888'
                drawing_context.fill_text(self.label, 8, canvas_size.height - self.__text_offset)

            with drawing_context.saver():
                drawing_context.font = self.__font
                drawing_context.text_align = 'center'
                drawing_context.text_baseline = 'bottom'
                drawing_context.fill_style = '#000'
                drawing_context.fill_text(self.title, canvas_size.width // 2, canvas_size.height - self.__text_offset)


class PanelSectionFactory(typing.Protocol):
    COMPONENT_TYPE: str = "panel_section"

    panel_section_ids: typing.Set[str]

    def make_panel_section(self, panel_section_id: str, d: Persistence.PersistentDictType, document_controller: DocumentController.DocumentController, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        ...


class SectionPanelSection(Declarative.Handler):
    def __init__(self, panel_section_handler: Declarative.HandlerLike) -> None:
        super().__init__()
        self.panel_section_handler = panel_section_handler
        self.is_expanded = True
        panel_section_title = getattr(panel_section_handler, "title")
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_section(u.create_component_instance(identifier="panel_section_handler"), title=panel_section_title, expanded=f"@binding(is_expanded)")

    def create_handler(self, component_id: str, container: typing.Any = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        return self.panel_section_handler


class SectionPanelHandler(Declarative.Handler):
    def __init__(self, panel_section_handlers: typing.Sequence[Declarative.HandlerLike], properties: Persistence.PersistentDictType) -> None:
        super().__init__()
        self.panel_section_handlers = list(panel_section_handlers)
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_column(u.create_column(items="panel_section_handlers", item_component_id="section"), u.create_stretch(), **properties)

    def create_handler(self, component_id: str, container: typing.Any = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        return SectionPanelSection(item)


class SectionPanel(Panel):
    def __init__(self, panel_d: Persistence.PersistentDictType, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, "section-panel")
        panel_section_handlers: typing.List[Declarative.HandlerLike] = list()
        for panel_section_d in panel_d.get("panel_sections", list()):
            panel_section_id = panel_section_d.get("panel_section_id", str())
            for panel_section_factory in typing.cast(typing.Set[PanelSectionFactory], Registry.get_components_by_type(PanelSectionFactory.COMPONENT_TYPE)):
                panel_section_handler = panel_section_factory.make_panel_section(panel_section_id, panel_section_d, document_controller)
                if panel_section_handler:
                    panel_section_handlers.append(panel_section_handler)
                    break
        assert panel_section_handlers
        self.widget = Declarative.DeclarativeWidget(document_controller.ui, document_controller.event_loop, SectionPanelHandler(panel_section_handlers, properties))


PanelCreateFn = typing.Callable[["DocumentController.DocumentController", str, typing.Optional["Persistence.PersistentDictType"]], Panel]


@dataclasses.dataclass
class PanelTuple:
    panel_create_fn: PanelCreateFn
    panel_id: str
    name: str
    positions: typing.List[str]
    position: str
    properties: typing.Optional[Persistence.PersistentDictType]


class PanelManager(metaclass=Utility.Singleton):
    def __init__(self) -> None:
        self.__panel_tuples: typing.Dict[str, PanelTuple] = dict()

    def register_panel(self, panel_class: PanelCreateFn, panel_id: str, name: str,
                       positions: typing.Sequence[str], position: str,
                       properties: typing.Optional[Persistence.PersistentDictType] = None) -> None:
        self.__panel_tuples[panel_id] = PanelTuple(panel_class, panel_id, name, list(positions), position, properties)

    def unregister_panel(self, panel_id: str) -> None:
        del self.__panel_tuples[panel_id]

    def create_panel_content(self, document_controller: DocumentController.DocumentController, panel_id: str,
                             title: str, positions: typing.Sequence[str], position: str,
                             properties: typing.Optional[Persistence.PersistentDictType]) -> typing.Optional[Panel]:
        if panel_id in self.__panel_tuples:
            panel_tuple = self.__panel_tuples[panel_id]
            try:
                properties = properties if properties else {}
                panel: Panel = panel_tuple.panel_create_fn(document_controller, panel_id, properties)
                panel.create_dock_widget(title, positions, position)
                return panel
            except Exception as e:
                import traceback
                print("Exception creating panel '" + panel_id + "': " + str(e))
                traceback.print_exc()
                traceback.print_stack()
        return None

    def get_panel_info(self, panel_id: str) -> typing.Tuple[str, typing.Sequence[str], str, typing.Optional[Persistence.PersistentDictType]]:
        panel_tuple = self.__panel_tuples[panel_id]
        return panel_tuple.name, panel_tuple.positions, panel_tuple.position, panel_tuple.properties

    @property
    def panel_ids(self) -> typing.List[str]:
        return list(self.__panel_tuples.keys())

    def load(self, d: typing.Sequence[Persistence.PersistentDictType]) -> None:
        for panel_d in d:
            if panel_d.get("version", 0) == 1:
                section_panel_id = panel_d["panel_id"]
                section_panel_title = panel_d["title"]
                is_panel_valid = False
                for panel_section_d in panel_d.get("panel_sections", list()):
                    panel_section_id = panel_section_d.get("panel_section_id", str())
                    if self.is_panel_section_valid(panel_section_id):
                        is_panel_valid = True
                        break
                if is_panel_valid:
                    def create_panel(panel_d: Persistence.PersistentDictType,
                                     document_controller: DocumentController.DocumentController, panel_id: str,
                                     properties: Persistence.PersistentDictType) -> Panel:
                        return SectionPanel(panel_d, document_controller, panel_id, properties)

                    self.register_panel(typing.cast(PanelCreateFn, functools.partial(create_panel, panel_d)),
                                        section_panel_id, section_panel_title, ["left", "right"], "right",
                                        {"min_width": 320})

    def is_panel_section_valid(self, panel_section_id: str) -> bool:
        for panel_section_factory in typing.cast(typing.Set[PanelSectionFactory], Registry.get_components_by_type(PanelSectionFactory.COMPONENT_TYPE)):
            if panel_section_id in panel_section_factory.panel_section_ids:
                return True
        return False

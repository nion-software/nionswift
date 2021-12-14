"""Notification dialog.

Watches notification sources for new notifications.

The notification dialog is a global resource, shared between windows.

Notifications are constructed and posted via the Notification module.

Example:

from nion.swift.model import Notification
notification = Notification.Notification("notification", "\N{Earth Globe Americas} World Monitor", "Global Warming Happening Now", "Global warming is the unusually rapid increase in Earth's average surface temperature over the past century primarily due to the greenhouse gases released as people burn fossil fuels.")
Notification.notify(notification)

Notifications can be dismissed by the user or programmatically by calling `notification.dismiss()`.
"""

from __future__ import annotations

# standard libraries
import functools
import gettext
import sys
import typing

# third party libraries
# None

# local libraries
from nion.swift.model import Notification
from nion.ui import CanvasItem
from nion.ui import Declarative
from nion.utils import Model
from nion.utils import ListModel
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.ui import Application
    from nion.ui import DrawingContext
    from nion.ui import UserInterface
    from nion.ui import Window
    from nion.utils import Event

_ = gettext.gettext


class CharButtonCanvasItem(CanvasItem.TextButtonCanvasItem):

    def __init__(self, char: str) -> None:
        super().__init__()
        self.__char = char
        self.wants_mouse_events = True
        self.__mouse_inside = False
        self.__mouse_pressed = False
        self.fill_style_pressed = "rgb(192, 192, 192)"
        self.border_style_pressed = "rgb(192, 192, 192)"
        self.fill_style_hover = "rgb(224, 224, 224)"
        self.border_style_hover = "rgb(224, 224, 224)"
        self.stroke_style = "#3366CC"
        self.on_clicked : typing.Optional[typing.Callable[[], None]] = None

    def close(self) -> None:
        self.on_clicked = None
        super().close()

    def mouse_entered(self) -> bool:
        self.__mouse_inside = True
        self.update()
        return True

    def mouse_exited(self) -> bool:
        self.__mouse_inside = False
        self.update()
        return True

    def mouse_pressed(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        self.__mouse_pressed = True
        self.update()
        return True

    def mouse_released(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        self.__mouse_pressed = False
        self.update()
        return True

    def mouse_clicked(self, x: int, y: int, modifiers: UserInterface.KeyboardModifiers) -> bool:
        if self.enabled:
            if callable(self.on_clicked):
                self.on_clicked()
        return True

    def _repaint(self, drawing_context: DrawingContext.DrawingContext) -> None:
        canvas_size = self.canvas_size
        if not canvas_size:
            return
        with drawing_context.saver():
            center_x = int(canvas_size.width * 0.5)
            center_y = int(canvas_size.height * 0.5)
            drawing_context.begin_path()
            text_base = 4 if sys.platform == "win32" else 6
            drawing_context.begin_path()
            drawing_context.rect(0, 0, canvas_size.width, canvas_size.height)
            if self.enabled:
                if self.__mouse_inside:
                    if self.__mouse_pressed:
                        if self.fill_style_pressed:
                            drawing_context.fill_style = self.fill_style_pressed
                            drawing_context.fill()
                        if self.border_style_pressed:
                            drawing_context.stroke_style = self.border_style_pressed
                            drawing_context.stroke()
                    else:
                        if self.fill_style_hover:
                            drawing_context.fill_style = self.fill_style_hover
                            drawing_context.fill()
                        if self.border_style_hover:
                            drawing_context.stroke_style = self.border_style_hover
                            drawing_context.stroke()
            drawing_context.begin_path()
            drawing_context.text_align = "center"
            drawing_context.text_baseline = "bottom"
            drawing_context.fill_style = self.stroke_style
            drawing_context.fill_text(self.__char, center_x, center_y + text_base)


class CharButtonConstructor:
    def construct(self, d_type: str, ui: UserInterface.UserInterface, window: typing.Optional[Window.Window],
                  d: Declarative.UIDescription, handler: Declarative.HandlerLike,
                  finishes: typing.List[typing.Callable[[], None]]) -> typing.Optional[UserInterface.Widget]:
        if d_type == "notification_char_button":
            font = "normal 13px serif"
            text = d["text"]
            fm = ui.get_font_metrics(font, text)
            canvas_item = CharButtonCanvasItem(text)
            widget = ui.create_canvas_widget(properties={"height": fm.height + 4, "width": fm.width + 4})
            widget.canvas_item.add_canvas_item(canvas_item)
            if handler:
                Declarative.connect_name(widget, d, handler)
                Declarative.connect_attributes(widget, d, handler, finishes)
                Declarative.connect_event(widget, canvas_item, d, handler, "on_clicked", [])
            return widget
        return None


Registry.register_component(CharButtonConstructor(), {"declarative_constructor"})


class NotificationHandler(Declarative.HandlerLike):
    """Declarative component handler for a section in a multiple acquire method component."""

    def __init__(self, notification: Notification.Notification) -> None:
        self.notification = notification
        u = Declarative.DeclarativeUI()
        self.ui_view = u.create_row(
            u.create_column(
                u.create_row(
                    u.create_label(text="@binding(notification.task_name)", color="#3366CC"),
                    u.create_stretch(),
                    {"type": "notification_char_button", "text": " \N{MULTIPLICATION X} ", "on_clicked": "handle_dismiss"},
                    spacing=8
                ),
                u.create_row(
                    u.create_label(text="@binding(notification.title)", font="bold"),
                    u.create_stretch(),
                    spacing=8
                ),
                u.create_row(
                    u.create_label(text="@binding(notification.text)", word_wrap=True, width=440),
                    u.create_stretch(),
                    spacing=8
                ),
                u.create_divider(orientation="horizontal"),
                spacing=4,
            ),
        )

    def close(self) -> None:
        pass

    def handle_dismiss(self, widget: Declarative.UIWidget) -> None:
        self.notification.dismiss()



class NotificationComponentFactory(typing.Protocol):
    def make_component(self, notification: Notification.Notification) -> typing.Optional[Declarative.HandlerLike]: ...


class NotificationDialog(Declarative.WindowHandler):

    def __init__(self, app: Application.BaseApplication) -> None:
        super().__init__()

        notifications = ListModel.ListModel[Notification.Notification]()
        stack_index = Model.PropertyModel[int](0)

        self.notifications = notifications
        self.stack_index = stack_index

        def notification_changed(key: str, value: Notification.Notification, index: int) -> None:
            stack_index.value = 1 if len(notifications.items) > 0 else 0

        self.__notification_inserted_listener = self.notifications.item_inserted_event.listen(notification_changed)
        self.__notification_removed_listener = self.notifications.item_removed_event.listen(notification_changed)

        u = Declarative.DeclarativeUI()
        main_column = u.create_column(
            u.create_stack(
                u.create_column(
                    u.create_label(text=_("No notifications.")),
                    u.create_stretch(),
                ),
                u.create_column(
                    u.create_column(items="notifications.items", item_component_id="notification", spacing=6),
                    u.create_stretch(),
                ),
                current_index="@binding(stack_index.value)"
            ),
            u.create_stretch(),
            spacing=8,
            width=460,
            min_height=260,
        )

        window = u.create_window(main_column, title=_("Notifications"), margin=8, window_style="tool")
        self.run(window, app=app, persistent_id="notification_dialog")

    def close(self) -> None:
        global notification_dialog
        notification_dialog = None
        super().close()

    def create_handler(self, component_id: str, container: typing.Any = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        # this is called to construct contained declarative component handlers within this handler.
        if component_id == "notification":
            assert container is not None
            assert item is not None
            notification = typing.cast(Notification.Notification, item)
            for component in Registry.get_components_by_type("notification-component-factory"):
                notification_handler = typing.cast(NotificationComponentFactory, component)
                notification_component = notification_handler.make_component(notification)
                if notification_component:
                    return notification_component
            return NotificationHandler(notification)
        return None


notification_dialog: typing.Optional[NotificationDialog] = None

_notification_sources: typing.List[Notification.NotificationSourceLike] = list()
_notification_source_listeners: typing.List[Event.EventListener] = list()
_notification_dismiss_listeners: typing.List[Event.EventListener] = list()


def notification_dismissed(notification: Notification.Notification) -> None:
    notifications = notification_dialog.notifications if notification_dialog else None
    if notifications:
        index = list(notifications.items).index(notification)
        _notification_dismiss_listeners.pop(index).close()
        notifications.remove_item(index)


def append_notification(notification: Notification.Notification) -> None:
    async def append_notification_async(notification: Notification.Notification) -> None:
        open_notification_dialog()
        _notification_dismiss_listeners.append(notification.dismiss_event.listen(functools.partial(notification_dismissed, notification)))
        notifications = notification_dialog.notifications if notification_dialog else None
        if notifications:
            notifications.append_item(notification)

    if _app:
        _app.event_loop.create_task(append_notification_async(notification))


def component_registered(component: Registry._ComponentType, component_types: typing.Set[str]) -> None:
    if "notification-source" in component_types:
        notification_source = typing.cast(Notification.NotificationSourceLike, component)
        _notification_source_listeners.append(notification_source.notify_event.listen(append_notification))
        _notification_sources.append(notification_source)
        for notification in notification_source.notifications:
            append_notification(notification)


def component_unregistered(component: Registry._ComponentType, component_types: typing.Set[str]) -> None:
    if "notification-source" in component_types:
        notification_source = typing.cast(Notification.NotificationSourceLike, component)
        index = _notification_sources.index(notification_source)
        _notification_sources.pop(index)
        _notification_source_listeners.pop(index).close()


_component_registered_listener = Registry.listen_component_registered_event(component_registered)
_component_unregistered_listener = Registry.listen_component_unregistered_event(component_unregistered)

Registry.fire_existing_component_registered_events("notification-source")

_app: Application.BaseApplication = typing.cast(typing.Any, None)


def open_notification_dialog() -> None:
    global notification_dialog
    if not notification_dialog:
        notification_dialog = NotificationDialog(_app)


def close_notification_dialog() -> None:
    global notification_dialog
    if notification_dialog:
        notification_dialog.close()

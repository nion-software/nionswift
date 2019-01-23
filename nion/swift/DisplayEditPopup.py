# standard libraries
import gettext
import typing

# local libraries
from nion.swift.model import DisplayItem
from nion.swift import DocumentController
from nion.swift import Inspector
from nion.ui import Declarative
from nion.ui import Window
from nion.utils import Event
from nion.utils import Geometry


_ = gettext.gettext


class PopupWindow(Window.Window):

    def __init__(self, parent_window: Window.Window, ui_widget: Declarative.UIDescription, ui_handler):
        super().__init__(parent_window.ui, app=parent_window.app, parent_window=parent_window, window_style="popup")

        def request_close():
            # this may be called in response to the user clicking a button to close.
            # make sure that the button is not destructed as a side effect of closing
            # the window by queueing the close. and it is not possible to use event loop
            # here because the event loop limitations: not able to run both parent and child
            # event loops simultaneously.
            parent_window.queue_task(self.request_close)

        finishes = list()

        self.widget = Declarative.construct(parent_window.ui, None, ui_widget, ui_handler, finishes)

        self.attach_widget(self.widget)

        for finish in finishes:
            finish()
        if ui_handler and hasattr(ui_handler, "init_handler"):
            ui_handler.init_handler()
        if ui_handler and hasattr(ui_handler, "init_popup"):
            ui_handler.init_popup(request_close)

        # TODO: select all works, but edit commands don't work
        # TODO: tabs don't work

        self._create_menus()

        self.__ui_handler = ui_handler

    def about_to_close(self, geometry: str, state: str) -> None:
        # do this by overriding about_to_close because on_close is reserved for other purposes.
        ui_handler = self.__ui_handler
        if ui_handler and hasattr(ui_handler, "close"):
            ui_handler.close()
        super().about_to_close(geometry, state)

    def show(self, *, size: Geometry.IntSize=None, position: Geometry.IntPoint=None) -> None:
        super().show(size=size, position=position)
        ui_handler = self.__ui_handler
        if ui_handler and hasattr(ui_handler, "did_show"):
            self.__ui_handler.did_show()

    def close(self) -> None:
        super().close()


def pose_title_edit_popup(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, position: Geometry.IntPoint, size: Geometry.IntSize):

    class Handler:

        def __init__(self):
            self.property_changed_event = Event.Event()
            self.title_edit = None
            self.caption_edit = None
            self.__is_rejected = False
            self.__title = display_item.title
            self.__caption = display_item.caption

        def init_handler(self):
            self.title_edit.select_all()

        def init_popup(self, request_close_fn: typing.Callable[[], None]) -> None:
            self.__request_close_fn = request_close_fn

        def did_show(self):
            self.title_edit.focused = True

        @property
        def title(self):
            return self.__title

        @title.setter
        def title(self, value):
            self.__title = value
            self.property_changed_event.fire("title")

        @property
        def caption(self):
            return self.__caption

        @caption.setter
        def caption(self, value):
            self.__caption = value
            self.property_changed_event.fire("caption")

        def reject(self, widget):
            # receive this when the user hits escape. let the window handle the escape by returning False.
            # mark popup as rejected.
            self.__is_rejected = True
            return False

        def accept(self, widget):
            # receive this when the user hits return. need to request a close and return True to say we handled event.
            self.__request_close_fn()
            return True

        def handle_done(self, widget):
            self.__request_close_fn()

        def handle_cancel(self, widget):
            self.__is_rejected = True
            self.__request_close_fn()

        def close(self):
            # if not rejected and title has changed, change the title.
            if not self.__is_rejected:
                title = self.title_edit.text
                if title != display_item.title:
                    command = Inspector.ChangeDisplayItemPropertyCommand(document_controller.document_model, display_item, "title", title)
                    command.perform()
                    document_controller.push_undo_command(command)
                caption = self.caption_edit.text
                if caption != display_item.caption:
                    command = Inspector.ChangeDisplayItemPropertyCommand(document_controller.document_model, display_item, "caption", caption)
                    command.perform()
                    document_controller.push_undo_command(command)

    ui_handler = Handler()

    ui = Declarative.DeclarativeUI()

    title_edit = ui.create_line_edit(name="title_edit", text="title", placeholder_text=_("Title"), on_return_pressed="accept", on_escape_pressed="reject", width=320)

    caption_edit = ui.create_text_edit(name="caption_edit", text="caption", on_escape_pressed="reject", height=100, width=320)

    title_row = ui.create_row(ui.create_label(text=_("Title")), title_edit, spacing=8, margin=8)

    caption_row = ui.create_row(ui.create_label(text=_("Caption")), caption_edit, spacing=8, margin=8)

    button_row = ui.create_row(ui.create_stretch(), ui.create_push_button(text=_("Cancel"), on_clicked="handle_cancel"), ui.create_push_button(text=_("Done"), on_clicked="handle_done"), spacing=8, margin=8)

    column = ui.create_column(title_row, caption_row, button_row, margin=4)

    popup = PopupWindow(document_controller, column, ui_handler)

    popup.show(position=position, size=size)

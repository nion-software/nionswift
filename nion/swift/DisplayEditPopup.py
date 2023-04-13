from __future__ import annotations

# standard libraries
import copy
import gettext
import typing

# local libraries
from nion.swift.model import DisplayItem
from nion.swift import DocumentController
from nion.swift import Inspector
from nion.swift import Undo
from nion.swift.model import Persistence
from nion.ui import Declarative
from nion.ui import Dialog
from nion.ui import Window
from nion.utils import Geometry
from nion.utils import Model

if typing.TYPE_CHECKING:
    from nion.ui import UserInterface

_ = gettext.gettext

TOOL_TIP_STR = _("Use empty field for automatic title.")


class InfoModel:
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        self.title_model = Model.PropertyModel[str](display_item.title)
        self.title_placeholder_model = Model.PropertyModel[str](display_item.placeholder_title)
        self.caption_model = Model.PropertyModel[str](display_item.caption)


class SessionModel:
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        self.data_item = display_item.data_item
        self.session_data = self.data_item.session if self.data_item else dict()
        self.site_model = Model.PropertyModel[str](self.session_data.get("site", str()))
        self.instrument_model = Model.PropertyModel[str](self.session_data.get("instrument", str()))
        self.task_model = Model.PropertyModel[str](self.session_data.get("task", str()))
        self.microscopist_model = Model.PropertyModel[str](self.session_data.get("microscopist", str()))
        self.sample_model = Model.PropertyModel[str](self.session_data.get("sample", str()))
        self.sample_area_model = Model.PropertyModel[str](self.session_data.get("sample_area", str()))
        self.label_model = Model.PropertyModel[str](self.session_data.get("label", str()))

    @property
    def session(self) -> Persistence.PersistentDictType:
        session_data = copy.deepcopy(self.session_data)
        session_data["site"] = self.site_model.value
        session_data["instrument"] = self.instrument_model.value
        session_data["task"] = self.task_model.value
        session_data["microscopist"] = self.microscopist_model.value
        session_data["sample"] = self.sample_model.value
        session_data["sample_area"] = self.sample_area_model.value
        session_data["label"] = self.label_model.value
        return session_data


class DataModel:
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        self.info_model = InfoModel(document_controller, display_item)
        self.session_model = SessionModel(document_controller, display_item)


class InfoHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, model: DataModel, parent: Handler) -> None:
        super().__init__()
        self.info_model = model.info_model
        self.parent = parent
        self.title_edit: typing.Optional[UserInterface.LineEditWidget] = None
        self.ui_view = self.__make_ui()

    def did_show(self) -> None:
        if self.title_edit:
            self.title_edit.select_all()
            self.title_edit.focused = True

    def __make_ui(self) -> Declarative.UIDescription:
        u = Declarative.DeclarativeUI()

        title_edit = u.create_line_edit(name="title_edit", text="@binding(info_model.title_model.value)", placeholder_text="@binding(info_model.title_placeholder_model.value)",
                                        tool_tip=TOOL_TIP_STR, on_return_pressed="accept", width=320)

        caption_edit = u.create_text_edit(text="@binding(info_model.caption_model.value)", height=100, width=320)

        title_row = u.create_row(u.create_label(text=_("Title"), tool_tip=TOOL_TIP_STR), title_edit, spacing=8, margin=8)

        caption_row = u.create_row(u.create_label(text=_("Caption")), caption_edit, spacing=8, margin=8)

        return u.create_column(title_row, caption_row, u.create_stretch())

    def accept(self, widget: UserInterface.Widget) -> bool:
        return self.parent.accept(widget)


class SessionHandler(Declarative.Handler):
    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, model: DataModel, parent: Handler) -> None:
        super().__init__()
        self.session_model = model.session_model
        self.parent = parent
        self.ui_view = self.__make_ui()

    def __make_ui(self) -> Declarative.UIDescription:
        u = Declarative.DeclarativeUI()

        field_descriptions = [
            [_("Site"), _("Site Description"), "site"],
            [_("Instrument"), _("Instrument Description"), "instrument"],
            [_("Task"), _("Task Description"), "task"],
            [_("Microscopist"), _("Microscopist Name(s)"), "microscopist"],
            [_("Sample"), _("Sample Description"), "sample"],
            [_("Sample Area"), _("Sample Area Description"), "sample_area"],
            [_("Label"), _("Brief Label"), "label"],
        ]

        field_rows: typing.List[Declarative.UIDescription] = list()

        for field_description in field_descriptions:
            label, tool_tip, key = field_description
            field_line_edit = u.create_line_edit(text=f"@binding(session_model.{key}_model.value)", tool_tip=tool_tip, placeholder_text=tool_tip, on_return_pressed="accept", width=320)
            field_rows.append(u.create_row(u.create_label(text=label, tool_tip=tool_tip), field_line_edit, spacing=8, margin=8))

        return u.create_column(*field_rows, u.create_stretch())

    def accept(self, widget: UserInterface.Widget) -> bool:
        return self.parent.accept(widget)


class Handler(Declarative.Handler):

    def __init__(self, document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem) -> None:
        super().__init__()
        self.__document_controller = document_controller
        self.__display_item = display_item
        self.__is_rejected = True
        self.model = DataModel(document_controller, display_item)
        self.__info_handler = InfoHandler(self.__document_controller, self.__display_item, self.model, self)
        self.__session_handler = SessionHandler(self.__document_controller, self.__display_item, self.model, self)
        self.tabs: typing.Optional[UserInterface.TabWidget] = None
        self.ui_view = self.__make_ui()

    def __make_ui(self) -> Declarative.UIDescription:
        u = Declarative.DeclarativeUI()

        button_row = u.create_row(u.create_stretch(),
                                  u.create_push_button(text=_("Cancel"), on_clicked="handle_cancel"),
                                  u.create_push_button(text=_("Done"), on_clicked="handle_done"), spacing=8, margin=8)

        tabs = u.create_tabs(u.create_tab(_("Info"), u.create_component_instance(identifier="info_component")),
                             u.create_tab(_("Session"), u.create_component_instance(identifier="session_component")),
                             name="tabs",
                             style="minimal")

        return u.create_group(u.create_column(tabs, button_row))

    def init_popup(self, request_close_fn: typing.Callable[[], None]) -> None:
        self.__request_close_fn = request_close_fn

    def accept(self, widget: UserInterface.Widget) -> bool:
        # receive this when the user hits return. need to request a close and return True to say we handled event.
        self.__is_rejected = False
        self.__request_close_fn()
        return True

    def handle_done(self, widget: UserInterface.Widget) -> bool:
        # receive this when the user hits return. need to request a close and return True to say we handled event.
        # for some reason, Qt does not handle 'editingFinished' properly, so focus/unfocus to force it here for now.
        if self.__info_handler.title_edit:
            self.__info_handler.title_edit.focused = True
            self.__info_handler.title_edit.focused = False
        self.__is_rejected = False
        self.__request_close_fn()
        return True

    def handle_cancel(self, widget: UserInterface.Widget) -> bool:
        self.__request_close_fn()
        return True

    def did_show(self) -> None:
        self.__info_handler.did_show()

    def close(self) -> None:
        # if not rejected and title has changed, change the title.
        if not self.__is_rejected:
            command: Undo.UndoableCommand
            title = self.model.info_model.title_model.value
            if title != self.__display_item.title:
                command = Inspector.ChangeDisplayItemPropertyCommand(self.__document_controller.document_model, self.__display_item, "title", title)
                command.perform()
                self.__document_controller.push_undo_command(command)
            caption = self.model.info_model.caption_model.value
            if caption != self.__display_item.caption:
                command = Inspector.ChangeDisplayItemPropertyCommand(self.__document_controller.document_model, self.__display_item, "caption", caption)
                command.perform()
                self.__document_controller.push_undo_command(command)
            session = self.model.session_model.session
            data_item = self.__display_item.data_item
            if data_item and session != data_item.session:
                command = Inspector.ChangePropertyCommand(self.__document_controller.document_model, data_item, "session", session)
                command.perform()
                self.__document_controller.push_undo_command(command)
        super().close()

    def create_handler(self, component_id: str, container: typing.Any = None, item: typing.Any = None, **kwargs: typing.Any) -> typing.Optional[Declarative.HandlerLike]:
        if component_id == "info_component":
            return self.__info_handler
        if component_id == "session_component":
            return self.__session_handler
        return None


class SpecialWindow(Dialog.PopupWindow):
    def __init__(self, parent_window: Window.Window, ui_widget: Declarative.UIDescription, handler: Handler) -> None:
        super().__init__(parent_window, ui_widget, handler)
        self.handler = handler

    def key_pressed(self, key: UserInterface.Key) -> bool:
        assert self.handler.tabs
        if key.text == "1" and key.modifiers.only_control:
            self.handler.tabs.current_index = 0
            return True
        if key.text == "2" and key.modifiers.only_control:
            self.handler.tabs.current_index = 1
            return True
        return super().key_pressed(key)

def pose_title_edit_popup(document_controller: DocumentController.DocumentController, display_item: DisplayItem.DisplayItem, position: typing.Optional[Geometry.IntPoint], size: Geometry.IntSize) -> None:
    ui_handler = Handler(document_controller, display_item)
    popup = SpecialWindow(document_controller, ui_handler.ui_view, ui_handler)
    popup.show(position=position, size=size)

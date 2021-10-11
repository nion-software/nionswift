from __future__ import annotations

# standard libraries
import functools
import gettext
import typing

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import ApplicationData

if typing.TYPE_CHECKING:
    from nion.swift import DocumentController
    from nion.swift.model import Persistence
    from nion.ui import UserInterface
    from nion.utils import StructuredModel

_ = gettext.gettext


class SessionPanelController:

    def __init__(self) -> None:
        self.__property_changed_listener = ApplicationData.get_session_metadata_model().property_changed_event.listen(self.__property_changed)
        self.on_fields_changed: typing.Optional[typing.Callable[[StructuredModel.DictValue], None]] = None

    def close(self) -> None:
        self.__property_changed_listener.close()
        self.__property_changed_listener = typing.cast(typing.Any, None)
        self.on_fields_changed = None

    @property
    def field_values(self) -> StructuredModel.DictValue:
        return ApplicationData.get_session_metadata_model().to_dict_value()

    def __property_changed(self, key: str) -> None:
        if callable(self.on_fields_changed):
            self.on_fields_changed(self.field_values)

    def set_field(self, field_id: str, value: str) -> None:
        setattr(ApplicationData.get_session_metadata_model(), field_id, value)


class SessionPanel(Panel.Panel):

    def __init__(self, document_controller: DocumentController.DocumentController, panel_id: str, properties: Persistence.PersistentDictType) -> None:
        super().__init__(document_controller, panel_id, _("Session"))

        self.__controller = SessionPanelController()

        field_descriptions = [
            [_("Site"), _("Site Description"), "site"],
            [_("Instrument"), _("Instrument Description"), "instrument"],
            [_("Task"), _("Task Description"), "task"],
            [_("Microscopist"), _("Microscopist Name(s)"), "microscopist"],
            [_("Sample"), _("Sample Description"), "sample"],
            [_("Sample Area"), _("Sample Area Description"), "sample_area"],
        ]

        widget = self.ui.create_column_widget()

        intro_row = self.ui.create_row_widget()
        intro_row.add_stretch()
        intro_label_widget = self.ui.create_label_widget(_("Session metadata added to acquired data."))
        intro_label_widget.text_font = "italic"
        intro_label_widget.text_color = "gray"
        intro_row.add(intro_label_widget)
        intro_row.add_stretch()

        def line_edit_changed(line_edit_widget: UserInterface.LineEditWidget, field_id: str, text: str) -> None:
            self.__controller.set_field(field_id, text)
            line_edit_widget.request_refocus()

        field_line_edit_widget_map = dict()

        widget.add_spacing(8)
        for field_description in field_descriptions:
            title, placeholder, field_id = field_description
            row = self.ui.create_row_widget()
            row.add_spacing(8)
            row.add(self.ui.create_label_widget(title, properties={"width": 100}))
            line_edit_widget = self.ui.create_line_edit_widget(properties={"width": 200})
            line_edit_widget.placeholder_text = placeholder
            line_edit_widget.on_editing_finished = functools.partial(line_edit_changed, line_edit_widget, field_id)
            field_line_edit_widget_map[field_id] = line_edit_widget
            row.add(line_edit_widget)
            widget.add(row)
            widget.add_spacing(4)
        widget.add(intro_row)
        widget.add_spacing(8)
        widget.add_stretch()

        def fields_changed(fields: StructuredModel.DictValue) -> None:
            for field_id, line_edit_widget in field_line_edit_widget_map.items():
                line_edit_widget.text = typing.cast(typing.Dict[str, str], fields).get(field_id)

        self.__controller.on_fields_changed = fields_changed
        fields_changed(self.__controller.field_values)

        self.widget = widget

    def close(self) -> None:
        self.__controller.close()
        super().close()

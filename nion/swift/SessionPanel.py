# standard libraries
import functools
import gettext

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.model import DocumentModel


_ = gettext.gettext


class SessionPanelController:

    def __init__(self, document_model: DocumentModel.DocumentModel):
        self.__document_model = document_model
        self.__property_changed_listener = self.__document_model.property_changed_event.listen(self.__property_changed)
        self.on_fields_changed = None

    def close(self):
        self.__property_changed_listener.close()
        self.__property_changed_listener = None
        self.on_fields_changed = None

    def __property_changed(self, key):
        if key == 'session_metadata':
            if callable(self.on_fields_changed):
                self.on_fields_changed(self.__document_model.session_metadata)

    def set_field(self, field_id: str, value: str) -> None:
        self.__document_model.set_session_field(field_id, value)


class SessionPanel(Panel.Panel):

    def __init__(self, document_controller, panel_id, properties):
        super(SessionPanel, self).__init__(document_controller, panel_id, _("Session"))

        self.__controller = SessionPanelController(document_controller.document_model)

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
        intro_row.add(self.ui.create_label_widget(_("Session metadata added to acquired data."), properties={"stylesheet": "font: italic; color: gray"}))
        intro_row.add_stretch()

        def line_edit_changed(line_edit_widget, field_id, text):
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

        def fields_changed(fields):
            for field_id, line_edit_widget in field_line_edit_widget_map.items():
                line_edit_widget.text = fields.get(field_id)

        self.__controller.on_fields_changed = fields_changed
        fields_changed(document_controller.document_model.session_metadata)

        self.widget = widget

    def close(self):
        self.__controller.close()
        super(SessionPanel, self).close()

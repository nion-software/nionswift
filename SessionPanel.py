# standard libraries
import gettext

# third party libraries
# None

# local libraries
from nion.swift import Panel


_ = gettext.gettext


class SessionPanel(Panel.Panel):
    def __init__(self, document_controller, panel_id, properties):
        super(SessionPanel, self).__init__(document_controller, panel_id, _("Session"))
        self.widget = self.ui.create_column_widget()

        session_title_row = self.ui.create_row_widget()
        session_title_row.add_spacing(12)
        session_title_row.add(self.ui.create_label_widget(_("Title"), properties={"width": 60}))
        session_title_row.add(self.ui.create_line_edit_widget(properties={"width": 240}))

        self.widget.add_spacing(8)
        self.widget.add(session_title_row)
        self.widget.add_stretch()

    def close(self):
        super(SessionPanel, self).close()



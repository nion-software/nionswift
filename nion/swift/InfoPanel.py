# standard libraries
import gettext

# third party libraries
# None

# local libraries
from nion.swift import Panel

_ = gettext.gettext


class InfoPanel(Panel.Panel):
    """A panel to display cursor information.

    The info panel will display cursor information. User interface items that want to
    update the cursor info should called cursor_changed on the document controller.
    This info panel will listen to the document controller for cursor updates and update
    itself in response. all cursor update calls are thread safe. this class uses periodic
    to do ui updates from the main thread.
    """

    def __init__(self, document_controller, panel_id, properties):
        super(InfoPanel, self).__init__(document_controller, panel_id, _("Info"))

        ui = document_controller.ui

        position_label = ui.create_label_widget(_("Position:"))
        self.position_text = ui.create_label_widget()
        value_label = ui.create_label_widget(_("Value:"))
        self.value_text = ui.create_label_widget()

        position_row = ui.create_row_widget(properties={"spacing": 6})
        position_row.add(position_label)
        position_row.add(self.position_text)
        position_row.add_stretch()

        value_row = ui.create_row_widget(properties={"spacing": 6})
        value_row.add(value_label)
        value_row.add(self.value_text)
        value_row.add_stretch()

        properties["spacing"] = 2
        properties["margin"] = 6
        column = ui.create_column_widget(properties=properties)
        column.add(position_row)
        column.add(value_row)
        column.add_stretch()

        self.widget = column

        # connect self as listener. this will result in calls to cursor_changed
        self.__cursor_changed_event_listener = self.document_controller.cursor_changed_event.listen(self.__cursor_changed)

    def close(self):
        # disconnect self as listener
        self.__cursor_changed_event_listener.close()
        self.__cursor_changed_event_listener = None
        self.clear_task("position_and_value")
        # finish closing
        super(InfoPanel, self).close()

    # this message is received from the document controller.
    def __cursor_changed(self, position_text: str, value_text: str) -> None:
        def update_position_and_value(position_text, value_text):
            self.position_text.text = position_text
            self.value_text.text = value_text

        self.add_task("position_and_value", lambda: update_position_and_value(position_text, value_text))

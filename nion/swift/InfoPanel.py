# standard libraries
import gettext
import typing

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

        self.label = ui.create_label_widget()

        text_row = ui.create_row_widget(properties={"spacing": 6})
        text_row.add(self.label)
        text_row.add_stretch()

        properties["spacing"] = 2
        properties["margin"] = 6
        column = ui.create_column_widget(properties=properties)
        column.add(text_row)
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
    def __cursor_changed(self, text_vars: typing.List[str]) -> None:
        def update_position_and_value(text_vars: typing.List[str]):
            self.label.text = ""
            if text_vars:
                del text_vars[3:] # ensure text_vars is up to 3 elements to prevent a possible exception
                for key in text_vars:
                    self.label.text += key + "\n"

                # fill the rest of the info text with newlines to prevent a strange animation effect
                for filler_keys in range(3 - len(text_vars)):
                    self.label.text += "\n"

        self.add_task("position_and_value", lambda: update_position_and_value(text_vars))

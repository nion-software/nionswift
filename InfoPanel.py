# standard libraries
import gettext

# third party libraries
# None

# local libraries
from nion.swift import Panel
from nion.swift.ImagePanel import _
from nion.swift.model import Calibration

_ = gettext.gettext


class InfoPanel(Panel.Panel):
    """
    The info panel will display cursor information. user interface items that want to
    update the cursor info should called cursor_changed on the document controller.
    This info panel will listen to the document controller for cursor updates and update
    itself in response. all cursor update calls are thread safe. this class uses periodic
    to do ui updates from the main thread.
    """

    def __init__(self, document_controller, panel_id, properties):
        super(InfoPanel, self).__init__(document_controller, panel_id, _("Info"))

        ui = document_controller.ui

        # used to maintain the display when cursor is not moving
        self.__last_source = None

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
        column = ui.create_column_widget(properties)
        column.add(position_row)
        column.add(value_row)
        column.add_stretch()

        self.widget = column

        # connect self as listener. this will result in calls to cursor_changed
        self.document_controller.add_listener(self)

    def close(self):
        # disconnect self as listener
        self.document_controller.remove_listener(self)
        self.clear_task("position_and_value")
        # finish closing
        super(InfoPanel, self).close()

    # this message is received from the document controller.
    # it is established using add_listener
    def cursor_changed(self, source, data_and_calibration, display_calibrated_values, pos, data_size):
        def get_value_text(value, intensity_calibration):
            if value is not None:
                return unicode(intensity_calibration.convert_to_calibrated_value_str(value))
            elif value is None:
                return _("N/A")
            else:
                return str(value)

        position_text = ""
        value_text = ""
        if data_and_calibration and data_size:
            if display_calibrated_values:
                dimensional_calibrations = data_and_calibration.dimensional_calibrations
                intensity_calibration = data_and_calibration.intensity_calibration
            else:
                dimensional_calibrations = [Calibration.Calibration() for i in xrange(0, len(pos))]
                intensity_calibration = Calibration.Calibration()
            if pos and len(pos) == 3:
                # TODO: fix me 3d
                # 3d image
                # make sure the position is within the bounds of the image
                if 0 <= pos[0] < data_size[0] and 0 <= pos[1] < data_size[1] and 0 <= pos[2] < data_size[2]:
                    position_text = u"{0}, {1}, {2}".format(
                        dimensional_calibrations[2].convert_to_calibrated_value_str(pos[2]),
                        dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1]),
                        dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(data_and_calibration.get_data_value(pos), intensity_calibration)
            if pos and len(pos) == 2:
                # 2d image
                # make sure the position is within the bounds of the image
                if pos[0] >= 0 and pos[0] < data_size[0] and pos[1] >= 0 and pos[1] < data_size[1]:
                    position_text = u"{0}, {1}".format(
                        dimensional_calibrations[1].convert_to_calibrated_value_str(pos[1]),
                        dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(data_and_calibration.get_data_value(pos), intensity_calibration)
            if pos and len(pos) == 1:
                # 1d plot
                # make sure the position is within the bounds of the line plot
                if pos[0] >= 0 and pos[0] < data_size[0]:
                    position_text = u"{0}".format(dimensional_calibrations[0].convert_to_calibrated_value_str(pos[0]))
                    value_text = get_value_text(data_and_calibration.get_data_value(pos), intensity_calibration)
            self.__last_source = source
        if self.__last_source == source:
            def update_position_and_value(position_text, value_text):
                self.position_text.text = position_text
                self.value_text.text = value_text

            self.add_task("position_and_value", lambda: update_position_and_value(position_text, value_text))

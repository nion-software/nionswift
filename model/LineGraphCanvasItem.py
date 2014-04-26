# standard libraries
import logging
import math
import gettext

# third party libraries
import numpy

# local libraries
from nion.ui import CanvasItem
from nion.ui import Geometry

_ = gettext.gettext



def get_calibrated_data_limits(raw_data_min, raw_data_max, calibration=None):
    """ Return the calibrated values of raw data limits, if calibration exists, otherwise return raw data limits. """
    if calibration is not None:
        calibrated_data_min = calibration.convert_to_calibrated_value(raw_data_min)
        calibrated_data_max = calibration.convert_to_calibrated_value(raw_data_max)
    else:
        calibrated_data_min = raw_data_min
        calibrated_data_max = raw_data_max
    if calibrated_data_min > calibrated_data_max:
        temp = calibrated_data_min
        calibrated_data_min = calibrated_data_max
        calibrated_data_max = temp
    return calibrated_data_min, calibrated_data_max


def get_drawn_data_limits(raw_data_min, raw_data_max, min_specified, max_specified, calibration=None):
    """
        Return drawn data limits after converting calibrated limits to pretty values.

        If min/max specified are False, then drawn data limits will be adjusted to start
        from 0.0.

        Calibration is optional.
    """
    calibrated_data_min, calibrated_data_max = get_calibrated_data_limits(raw_data_min, raw_data_max, calibration)
    calibrated_data_min = 0.0 if calibrated_data_min > 0 and not min_specified else calibrated_data_min
    calibrated_data_max = 0.0 if calibrated_data_max < 0 and not max_specified else calibrated_data_max
    pretty_calibrated_data_max = Geometry.make_pretty(calibrated_data_max, round_up=True)
    pretty_calibrated_data_min = Geometry.make_pretty(calibrated_data_min, round_up=True)
    if calibration:
        drawn_data_min = calibration.convert_from_calibrated_value(pretty_calibrated_data_min)
        drawn_data_max = calibration.convert_from_calibrated_value(pretty_calibrated_data_max)
    else:
        drawn_data_min = pretty_calibrated_data_min
        drawn_data_max = pretty_calibrated_data_max
    return drawn_data_min, drawn_data_max



class LineGraphDataInfo(object):

    def __init__(self, data=None, data_min=None, data_max=None, data_left=None, data_right=None, spatial_calibration=None, intensity_calibration=None):
        self.data = data
        self.data_min = data_min
        self.data_max = data_max
        self.data_left = data_left
        self.data_right = data_right
        self.spatial_calibration = spatial_calibration
        self.intensity_calibration = intensity_calibration

    def get_drawn_data_limits(self):
        min_specified = self.data_min is not None
        max_specified = self.data_max is not None
        raw_data_min = self.data_min if min_specified else numpy.amin(self.data)
        raw_data_max = self.data_max if max_specified else numpy.amax(self.data)
        return get_drawn_data_limits(raw_data_min, raw_data_max, min_specified, max_specified, self.intensity_calibration)

    def calculate_y_ticks(self, height, drawn_data_min, drawn_data_range, tick_count=4):
        # calculate the intensity scale
        tick_size = height / tick_count
        # calculate y_ticks
        y_ticks = list()
        for i in range(tick_count+1):
            y = int(height - tick_size * i)
            if i == 0:
                y = height  # match it with the plot_rect
            elif i == tick_count:
                y = 0  # match it with the plot_rect
            value = drawn_data_min + drawn_data_range * float(i) / tick_count
            label = self.intensity_calibration.convert_to_calibrated_value_str(value, include_units=False) if self.intensity_calibration is not None else "{0:g}".format(value)
            y_ticks.append((y, label))
        return y_ticks

    def calculate_x_ticks(self, width, data_left, data_width):
        # approximate tick count
        horizontal_tick_count = min(max(2, int(width / 100)), 10)
        # calculate the horizontal tick spacing in spatial units
        horizontal_tick_spacing = float(width) / horizontal_tick_count
        horizontal_tick_spacing = data_width * horizontal_tick_spacing / width
        if self.spatial_calibration:
            horizontal_tick_spacing = self.spatial_calibration.convert_to_calibrated_value(horizontal_tick_spacing)
        # TODO: add test for horizontal_tick_spacing 0.0 and vertical space 0.0 too
        horizontal_tick_spacing = Geometry.make_pretty(horizontal_tick_spacing, round_up=True)  # never want this to round to 0.0
        if self.spatial_calibration:
            horizontal_tick_spacing = self.spatial_calibration.convert_from_calibrated_value(horizontal_tick_spacing)
        # calculate the horizontal minimum value in spatial units
        horizontal_tick_min = 0.0
        if self.spatial_calibration:
            horizontal_tick_min = self.spatial_calibration.convert_to_calibrated_value(horizontal_tick_min)
        horizontal_tick_min = Geometry.make_pretty(horizontal_tick_min)
        if self.spatial_calibration:
            horizontal_tick_min = self.spatial_calibration.convert_from_calibrated_value(horizontal_tick_min)
        # calculate the tick marks
        x = horizontal_tick_min
        x_ticks = list()
        while horizontal_tick_spacing > 0.0 and x < width:  # sanity check along with regular loop
            value = data_left + data_width * float(x) / width
            value_str = self.spatial_calibration.convert_to_calibrated_value_str(value, include_units=False) if self.spatial_calibration else "{0:g}".format(value)
            x_ticks.append((x, value_str))
            x += width * horizontal_tick_spacing / data_width
        return x_ticks


class LineGraphCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(LineGraphCanvasItem, self).__init__()
        self.data_info = None
        self.draw_grid = True
        self.draw_frame = True
        self.background_color = "#EEE"
        self.font_size = 12

    def map_mouse_to_position(self, mouse, data_size):
        plot_rect = self.canvas_bounds
        mouse_x = mouse[1] - plot_rect[0][1]  # 436
        mouse_y = mouse[0] - plot_rect[0][0]
        if mouse_x > 0 and mouse_x < plot_rect[1][1] and mouse_y > 0 and mouse_y < plot_rect[1][0]:
            return (data_size[0] * mouse_x / plot_rect[1][1], )
        # not in bounds
        return None

    def _repaint(self, drawing_context):

        # draw the data, if any
        if self.data_info is not None and self.data_info.data is not None:

            plot_rect = self.canvas_bounds
            plot_width = int(plot_rect[1][1]) - 1
            plot_height = int(plot_rect[1][0]) - 1
            plot_origin_x = int(plot_rect[0][1])
            plot_origin_y = int(plot_rect[0][0])

            drawing_context.save()
            drawing_context.begin_path()
            drawing_context.rect(plot_rect[0][1], plot_rect[0][0], plot_rect[1][1], plot_rect[1][0])
            drawing_context.fill_style = self.background_color
            drawing_context.fill()
            drawing_context.restore()

            # calculate the intensity scale
            drawn_data_min, drawn_data_max = self.data_info.get_drawn_data_limits()
            drawn_data_range = drawn_data_max - drawn_data_min
            y_ticks = self.data_info.calculate_y_ticks(plot_height, drawn_data_min, drawn_data_range, tick_count=4)
            # draw the y_ticks and labels
            if self.draw_grid:
                drawing_context.save()
                for y, label in y_ticks:
                    drawing_context.begin_path()
                    drawing_context.move_to(plot_origin_x, y)
                    drawing_context.line_to(plot_origin_x + plot_width, y)
                    drawing_context.line_width = 1
                    drawing_context.stroke_style = '#888'
                    drawing_context.stroke()
                drawing_context.restore()
            # draw the horizontal axis
            raw_data_right = self.data_info.data.shape[0]
            data_left = self.data_info.data_left if self.data_info.data_left is not None else 0.0
            data_right = self.data_info.data_right if self.data_info.data_right is not None else raw_data_right
            data_width = data_right - data_left
            x_ticks = self.data_info.calculate_x_ticks(plot_width, data_left, data_width)
            # draw the tick marks
            drawing_context.save()
            for x, label in x_ticks:
                drawing_context.begin_path()
                if self.draw_grid:
                    drawing_context.move_to(x, plot_origin_y)
                    drawing_context.line_to(x, plot_origin_y + plot_height)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
            drawing_context.restore()
            # draw the line plot itself
            drawing_context.save()
            drawing_context.begin_path()
            if drawn_data_range != 0.0:
                baseline = plot_origin_y + plot_height - (plot_height * float(0.0 - drawn_data_min) / drawn_data_range)
                baseline = min(plot_origin_y + plot_height, baseline)
                baseline = max(plot_origin_y, baseline)
                drawing_context.move_to(plot_origin_x, baseline)
                for i in xrange(0, plot_width, 2):
                    px = plot_origin_x + i
                    data_index = int(data_left + data_width * float(i) / plot_width)
                    data_value = float(self.data_info.data[data_index]) if data_index >= 0 and data_index < raw_data_right else 0.0
                    # plot_origin_y is the TOP of the drawing
                    # py extends DOWNWARDS
                    py = plot_origin_y + plot_height - (plot_height * (data_value - drawn_data_min) / drawn_data_range)
                    py = max(plot_origin_y, py)
                    py = min(plot_origin_y + plot_height, py)
                    drawing_context.line_to(px, py)
                    px = min(px + 2, plot_origin_x + plot_width)
                    drawing_context.line_to(px, py)
                # finish off last line
                px = plot_origin_x + plot_width
                data_index = data_right - 1
                data_value = float(self.data_info.data[data_index]) if data_index >= 0 and data_index < raw_data_right else 0.0
                py = plot_origin_y + plot_height - (plot_height * (data_value - drawn_data_min) / drawn_data_range)
                drawing_context.line_to(plot_origin_x + plot_width, baseline)
            else:
                drawing_context.move_to(plot_origin_x, plot_origin_y + plot_height * 0.5)
                drawing_context.line_to(plot_origin_x + plot_width, plot_origin_y + plot_height * 0.5)
            # close it up and draw
            drawing_context.close_path()
            drawing_context.fill_style = '#AFA'
            drawing_context.fill()
            drawing_context.line_width = 0.5
            drawing_context.line_cap = 'round'
            drawing_context.line_join = 'round'
            drawing_context.stroke_style = '#040'
            drawing_context.stroke()
            if self.draw_frame:
                drawing_context.begin_path()
                drawing_context.rect(plot_origin_x, plot_origin_y, plot_width, plot_height)
            drawing_context.line_width = 1
            drawing_context.stroke_style = '#888'
            drawing_context.stroke()
            drawing_context.restore()


class LineGraphHorizontalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(LineGraphHorizontalAxisTicksCanvasItem, self).__init__()
        self.data_info = None
        self.tick_height = 4
        self.sizing.minimum_height = self.tick_height
        self.sizing.maximum_height = self.tick_height

    def _repaint(self, drawing_context):

        # draw the data, if any
        if self.data_info is not None and self.data_info.data is not None:

            plot_width = int(self.canvas_size[1]) - 1

            # draw the horizontal axis
            raw_data_right = self.data_info.data.shape[0]
            data_left = self.data_info.data_left if self.data_info.data_left is not None else 0.0
            data_right = self.data_info.data_right if self.data_info.data_right is not None else raw_data_right
            data_width = data_right - data_left
            x_ticks = self.data_info.calculate_x_ticks(plot_width, data_left, data_width)
            # draw the tick marks
            drawing_context.save()
            for x, label in x_ticks:
                drawing_context.begin_path()
                drawing_context.move_to(x, 0)
                drawing_context.line_to(x, self.tick_height)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
            drawing_context.restore()


class LineGraphHorizontalAxisScaleCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(LineGraphHorizontalAxisScaleCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_height = self.font_size + 4
        self.sizing.maximum_height = self.font_size + 4

    def _repaint(self, drawing_context):

        # draw the data, if any
        if self.data_info is not None and self.data_info.data is not None:

            height = self.canvas_size[0]
            plot_width = int(self.canvas_size[1]) - 1

            # draw the horizontal axis
            raw_data_right = self.data_info.data.shape[0]
            data_left = self.data_info.data_left if self.data_info.data_left is not None else 0.0
            data_right = self.data_info.data_right if self.data_info.data_right is not None else raw_data_right
            data_width = data_right - data_left
            x_ticks = self.data_info.calculate_x_ticks(plot_width, data_left, data_width)
            # draw the tick marks
            drawing_context.save()
            for x, label in x_ticks:
                drawing_context.text_align = "center"
                drawing_context.text_baseline = "middle"
                drawing_context.fill_style = "#000"
                drawing_context.fill_text(label, x, height * 0.5)
            drawing_context.restore()


class LineGraphHorizontalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(LineGraphHorizontalAxisLabelCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_height = self.font_size + 4
        self.sizing.maximum_height = self.font_size + 4

    def _repaint(self, drawing_context):

        # draw the data, if any
        if self.data_info is not None and self.data_info.data is not None:

            # draw the horizontal axis
            if self.data_info.spatial_calibration and self.data_info.spatial_calibration.units:

                height = self.canvas_size[0]
                plot_width = int(self.canvas_size[1]) - 1

                drawing_context.save()
                drawing_context.text_align = "center"
                drawing_context.text_baseline = "middle"
                drawing_context.fill_style = "#000"
                value_str = u"({0})".format(self.data_info.spatial_calibration.units)
                drawing_context.fill_text(value_str, plot_width * 0.5, height * 0.5)
                drawing_context.restore()


class LineGraphVerticalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(LineGraphVerticalAxisTicksCanvasItem, self).__init__()
        self.data_info = None
        self.tick_width = 4
        self.sizing.minimum_width = self.tick_width
        self.sizing.maximum_width = self.tick_width

    def _repaint(self, drawing_context):

        # draw the data, if any
        if self.data_info is not None and self.data_info.data is not None:

            # canvas size
            width = self.canvas_size[1]
            plot_height = int(self.canvas_size[0]) - 1

            # calculate the intensity scale
            drawn_data_min, drawn_data_max = self.data_info.get_drawn_data_limits()
            drawn_data_range = drawn_data_max - drawn_data_min
            y_ticks = self.data_info.calculate_y_ticks(plot_height, drawn_data_min, drawn_data_range, tick_count=4)

            # draw the y_ticks and labels
            drawing_context.save()
            for y, label in y_ticks:
                drawing_context.begin_path()
                drawing_context.move_to(width, y)
                drawing_context.line_to(width - self.tick_width, y)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
            drawing_context.restore()


class LineGraphVerticalAxisScaleCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(LineGraphVerticalAxisScaleCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_width = 36
        self.sizing.maximum_width = 36

    def _repaint(self, drawing_context):

        # draw the data, if any
        if self.data_info is not None and self.data_info.data is not None:

            # canvas size
            width = self.canvas_size[1]
            plot_height = int(self.canvas_size[0]) - 1

            # calculate the intensity scale
            drawn_data_min, drawn_data_max = self.data_info.get_drawn_data_limits()
            drawn_data_range = drawn_data_max - drawn_data_min
            y_ticks = self.data_info.calculate_y_ticks(plot_height, drawn_data_min, drawn_data_range, tick_count=4)
            # draw the y_ticks and labels
            drawing_context.save()
            drawing_context.text_baseline = "middle"
            drawing_context.font = "{0:d}px".format(self.font_size)
            for y, label in y_ticks:
                drawing_context.begin_path()
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
                drawing_context.text_align = "right"
                drawing_context.fill_style = "#000"
                drawing_context.fill_text(label, width - 8, y)
            drawing_context.restore()


class LineGraphVerticalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):

    def __init__(self):
        super(LineGraphVerticalAxisLabelCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_width = self.font_size + 4
        self.sizing.maximum_width = self.font_size + 4

    def _repaint(self, drawing_context):

        # draw the data, if any
        if self.data_info is not None and self.data_info.data is not None:

            # draw
            if self.data_info.intensity_calibration and self.data_info.intensity_calibration.units:
                # canvas size
                width = self.canvas_size[1]
                plot_height = int(self.canvas_size[0]) - 1

                drawing_context.save()
                drawing_context.font = "{0:d}px".format(self.font_size)
                drawing_context.text_align = "center"
                drawing_context.text_baseline = "middle"
                drawing_context.fill_style = "#000"
                x = width * 0.5
                y = int(plot_height * 0.5)
                drawing_context.translate(x, y)
                drawing_context.rotate(-math.pi*0.5)
                drawing_context.translate(-x, -y)
                drawing_context.fill_text(u"{0} ({1})".format(_("Intensity"), self.data_info.intensity_calibration.units), x, y)
                drawing_context.translate(x, y)
                drawing_context.rotate(+math.pi*0.5)
                drawing_context.translate(-x, -y)
                drawing_context.restore()

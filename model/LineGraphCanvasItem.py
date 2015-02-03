"""
    A collection of classes facilitating drawing line graphs.

    LineGraphDataInfo is used to pass data, drawing limits, and calibrations to
    various canvas items.

    Several canvas items including the line graph itself, and tick marks, scale,
    and label are also available. All canvas items except for the canvas item
    are auto sizing in the appropriate direction. Canvas items are meant to be
    combined into a grid layout with the line graph.
"""

# standard libraries
import collections
import gettext
import math

# third party libraries
import numpy

# local libraries
from nion.ui import CanvasItem
from nion.ui import Geometry
from nion.swift.model import Image

_ = gettext.gettext


class LineGraphDataInfo(object):

    """ LineGraphDataInfo is used to pass data, drawing limits, and calibrations to various canvas items. """

    def __init__(self, data_fn=None, data_min=None, data_max=None, data_left=None, data_right=None, spatial_calibration=None, intensity_calibration=None):
        # these items are considered to be input items
        self.__data_fn = data_fn
        self.__data = None
        self.data_min = data_min
        self.data_max = data_max
        self.data_left = data_left
        self.data_right = data_right
        self.spatial_calibration = spatial_calibration
        self.intensity_calibration = intensity_calibration
        # these items are considered to be output items
        self.__x_axis_valid = False
        self.__y_axis_valid = False
        # y-axis
        self.__drawn_data_min = None
        self.__drawn_data_max = None
        self.__drawn_data_range = None
        self.__y_tick_precision = None
        self.__y_tick_division = None
        self.__y_tick_values = None
        self.__calibrated_data_min = None
        self.__calibrated_data_max = None
        # x-axis
        self.__drawn_left_channel = None
        self.__drawn_right_channel = None
        self.__x_tick_precision = None
        self.__x_tick_division = None
        self.__x_tick_values = None

    @property
    def data(self):
        if self.__data is None and self.__data_fn:
            import threading
            if threading.current_thread().getName() == "MainThread":
                import traceback
                # traceback.print_stack()
            self.__data = self.__data_fn()
        return self.__data

    def get_drawn_data_per_pixel(self, plot_height):
        y_properties = self.y_properties
        return float(y_properties.drawn_data_range) / plot_height

    def __prepare_y_axis(self):

        """
        Calculate various parameters relating to the y-axis.

        The specific parameters calculated from this method are: drawn_data_min, drawn_data_max, drawn_data_range,
        y_tick_precision, y_tick_division, y_tick_values, calibrated_data_min, calibrated_data_max.
        """

        if not self.__y_axis_valid:

            calibration = self.intensity_calibration

            min_specified = self.data_min is not None
            max_specified = self.data_max is not None
            raw_data_min = self.data_min if min_specified else numpy.amin(self.data)
            raw_data_max = self.data_max if max_specified else numpy.amax(self.data)

            calibrated_data_min = calibration.convert_to_calibrated_value(raw_data_min) if calibration is not None else raw_data_min
            calibrated_data_max = calibration.convert_to_calibrated_value(raw_data_max) if calibration is not None else raw_data_max
            calibrated_data_min, calibrated_data_max = min(calibrated_data_min, calibrated_data_max), max(calibrated_data_min, calibrated_data_max)
            calibrated_data_min = 0.0 if calibrated_data_min > 0 and not min_specified else calibrated_data_min
            calibrated_data_max = 0.0 if calibrated_data_max < 0 and not max_specified else calibrated_data_max

            graph_minimum, graph_maximum, tick_values, division, precision = Geometry.make_pretty_range(calibrated_data_min, calibrated_data_max)

            if min_specified:
                self.__drawn_data_min = raw_data_min
            else:
                self.__drawn_data_min = calibration.convert_from_calibrated_value(graph_minimum) if calibration else graph_minimum
            if max_specified:
                self.__drawn_data_max = raw_data_max
            else:
                self.__drawn_data_max = calibration.convert_from_calibrated_value(graph_maximum) if calibration else graph_maximum
            self.__drawn_data_range = self.__drawn_data_max - self.__drawn_data_min

            self.__y_tick_precision = precision
            self.__y_tick_division = division
            self.__y_tick_values = tick_values

            self.__calibrated_data_min = calibration.convert_to_calibrated_value(self.__drawn_data_min) if calibration else self.__drawn_data_min
            self.__calibrated_data_max = calibration.convert_to_calibrated_value(self.__drawn_data_max) if calibration else self.__drawn_data_max

            self.__y_axis_valid = True

    def calculate_y_ticks(self, plot_height):

        """ Calculate the y-axis items dependent on the plot height. """

        calibration = self.intensity_calibration

        y_properties = self.y_properties

        y_ticks = list()
        for tick_value in y_properties.y_tick_values:
            label = (u"{0:0." + u"{0:d}".format(y_properties.y_tick_precision) + "f}").format(tick_value)
            data_tick = calibration.convert_from_calibrated_value(tick_value) if calibration else tick_value
            if y_properties.drawn_data_range != 0.0:
                y_tick = plot_height - plot_height * (data_tick - y_properties.drawn_data_min) / y_properties.drawn_data_range
            else:
                y_tick = plot_height - plot_height * 0.5
            if y_tick >= 0 and y_tick <= plot_height:
                y_ticks.append((y_tick, label))

        return y_ticks

    @property
    def y_properties(self):
        if self.__data_fn is None:
            return None
        y_properties = collections.namedtuple("YProperties", ["drawn_data_min", "drawn_data_max", "drawn_data_range",
            "y_tick_precision", "y_tick_division", "y_tick_values", "calibrated_data_min", "calibrated_data_max"])
        self.__prepare_y_axis()
        return y_properties(self.__drawn_data_min, self.__drawn_data_max, self.__drawn_data_range,
                            self.__y_tick_precision, self.__y_tick_division, self.__y_tick_values,
                            self.__calibrated_data_min, self.__calibrated_data_max)

    def __prepare_x_axis(self):

        """
        Calculate various parameters relating to the x-axis.

        The specific parameters calculated from this method are: drawn_left_channel, drawn_right_channel,
        x_tick_precision, x_tick_division, x_tick_values.
        """

        if not self.__x_axis_valid:

            calibration = self.spatial_calibration

            left_specified = self.data_left is not None
            right_specified = self.data_right is not None
            raw_data_left = self.data_left if left_specified else 0.0
            raw_data_right = self.data_right if right_specified else self.data.shape[0]

            calibrated_data_left = calibration.convert_to_calibrated_value(raw_data_left) if calibration is not None else raw_data_left
            calibrated_data_right = calibration.convert_to_calibrated_value(raw_data_right) if calibration is not None else raw_data_right
            calibrated_data_left, calibrated_data_right = min(calibrated_data_left, calibrated_data_right), max(calibrated_data_left, calibrated_data_right)

            graph_left, graph_right, tick_values, division, precision = Geometry.make_pretty_range(calibrated_data_left, calibrated_data_right)

            if left_specified:
                self.__drawn_left_channel = raw_data_left
            else:
                self.__drawn_left_channel = calibration.convert_from_calibrated_value(graph_left) if calibration else graph_left
            if right_specified:
                self.__drawn_right_channel = raw_data_right
            else:
                self.__drawn_right_channel = calibration.convert_from_calibrated_value(graph_right) if calibration else graph_right

            self.__x_tick_precision = precision
            self.__x_tick_division = division
            self.__x_tick_values = tick_values

            self.__x_axis_valid = True

    def calculate_x_ticks(self, plot_width):

        """ Calculate the x-axis items dependent on the plot width. """

        calibration = self.spatial_calibration
        x_properties = self.x_properties
        drawn_data_width = x_properties.drawn_right_channel - x_properties.drawn_left_channel

        x_ticks = list()
        for tick_value in x_properties.x_tick_values:
            label = (u"{0:0." + u"{0:d}".format(x_properties.x_tick_precision) + "f}").format(tick_value)
            data_tick = calibration.convert_from_calibrated_value(tick_value) if calibration else tick_value
            x_tick = plot_width * (data_tick - x_properties.drawn_left_channel) / drawn_data_width
            if x_tick >= 0 and x_tick <= plot_width:
                x_ticks.append((x_tick, label))

        return x_ticks

    @property
    def x_properties(self):
        if self.__data_fn is None:
            return None
        x_properties = collections.namedtuple("XProperties",
                                              ["drawn_left_channel", "drawn_right_channel", "x_tick_precision",
                                                  "x_tick_division", "x_tick_values"])
        self.__prepare_x_axis()
        return x_properties(self.__drawn_left_channel, self.__drawn_right_channel, self.__x_tick_precision,
                            self.__x_tick_division, self.__x_tick_values)


class LineGraphCanvasItem(CanvasItem.AbstractCanvasItem):

    """ Canvas item to draw the line plot itself. """

    def __init__(self):
        super(LineGraphCanvasItem, self).__init__()
        self.__drawing_context = None
        self.__needs_update = True
        self.__data_info = None
        self.draw_grid = True
        self.draw_frame = True
        self.background_color = "#FFF"
        self.font_size = 12

    @property
    def data_info(self):
        return self.__data_info

    @data_info.setter
    def data_info(self, value):
        self.__data_info = value
        self.update()

    def map_mouse_to_position(self, mouse, data_size):
        """ Map the mouse to the 1-d position within the line graph. """
        x_properties = self.data_info.x_properties if self.data_info else None
        if x_properties and x_properties.drawn_left_channel is not None and x_properties.drawn_right_channel is not None:
            mouse = Geometry.IntPoint.make(mouse)
            plot_rect = self.canvas_bounds
            if plot_rect.contains_point(mouse):
                mouse = mouse - plot_rect.origin
                x = float(mouse.x) / plot_rect.width
                px = x_properties.drawn_left_channel + x * (x_properties.drawn_right_channel - x_properties.drawn_left_channel)
                return px,
        # not in bounds
        return None

    def _repaint(self, drawing_context):
        if not self.__drawing_context and self.canvas_widget:
            self.__drawing_context = self.canvas_widget.create_drawing_context()
        if self.__drawing_context:
            if self.__needs_update:
                self.__needs_update = False
                self.__drawing_context.clear()
                self.__paint(self.__drawing_context)
            drawing_context.add(self.__drawing_context)
        else: # handle the non-cache case
            self.__paint(drawing_context)

    def update(self):
        self.__needs_update = True
        super(LineGraphCanvasItem, self).update()

    def __paint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        y_properties = self.data_info.y_properties if data_info else None
        x_properties = self.data_info.x_properties if data_info else None
        if data_info and data_info.data is not None and y_properties and x_properties:

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

            # extract the data we need for drawing y-axis
            drawn_data_min = y_properties.drawn_data_min
            drawn_data_range = y_properties.drawn_data_range
            y_ticks = data_info.calculate_y_ticks(plot_height)

            # extract the data we need for drawing x-axis
            data_left = x_properties.drawn_left_channel
            data_width = x_properties.drawn_right_channel - x_properties.drawn_left_channel
            x_ticks = data_info.calculate_x_ticks(plot_width)

            # draw the horizontal grid lines
            if self.draw_grid:
                drawing_context.save()
                for y, _ in y_ticks:
                    drawing_context.begin_path()
                    drawing_context.move_to(plot_origin_x, y)
                    drawing_context.line_to(plot_origin_x + plot_width, y)
                    drawing_context.line_width = 1
                    drawing_context.stroke_style = '#DDD'
                    drawing_context.stroke()
                drawing_context.restore()

            # draw the vertical grid lines
            drawing_context.save()
            for x, _ in x_ticks:
                drawing_context.begin_path()
                if self.draw_grid:
                    drawing_context.move_to(x, plot_origin_y)
                    drawing_context.line_to(x, plot_origin_y + plot_height)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#DDD'
                drawing_context.stroke()
            drawing_context.restore()

            # draw the line plot itself
            drawing_context.save()
            drawing_context.begin_path()
            if drawn_data_range != 0.0:
                baseline = plot_origin_y + plot_height - (plot_height * float(0.0 - drawn_data_min) / drawn_data_range)
                baseline = min(plot_origin_y + plot_height, baseline)
                baseline = max(plot_origin_y, baseline)
                # rebin so that data_width corresponds to plot width
                binned_length = int(data_info.data.shape[0] * plot_width / data_width)
                binned_data = Image.rebin_1d(data_info.data, binned_length)
                binned_left = int(data_left * plot_width / data_width)
                # draw the plot
                for i in xrange(0, plot_width):
                    px = plot_origin_x + i
                    binned_index = binned_left + i
                    data_value = binned_data[binned_index] if binned_index >= 0 and binned_index < binned_length else 0.0
                    # plot_origin_y is the TOP of the drawing
                    # py extends DOWNWARDS
                    py = plot_origin_y + plot_height - (plot_height * (data_value - drawn_data_min) / drawn_data_range)
                    py = max(plot_origin_y, py)
                    py = min(plot_origin_y + plot_height, py)
                    drawing_context.move_to(px, baseline)
                    drawing_context.line_to(px, py)
            else:
                drawing_context.move_to(plot_origin_x, plot_origin_y + plot_height * 0.5)
                drawing_context.line_to(plot_origin_x + plot_width, plot_origin_y + plot_height * 0.5)
            drawing_context.line_width = 1.0
            drawing_context.stroke_style = '#1E90FF'  # dodger blue
            drawing_context.stroke()
            if self.draw_frame:
                drawing_context.begin_path()
                drawing_context.rect(plot_origin_x, plot_origin_y, plot_width, plot_height)
            drawing_context.line_width = 1
            drawing_context.stroke_style = '#888'
            drawing_context.stroke()
            drawing_context.restore()


def draw_marker(ctx, p, fill=None, stroke=None):
    ctx.save()
    ctx.begin_path()
    ctx.move_to(p[1] - 3, p[0] - 3)
    ctx.line_to(p[1] + 3, p[0] - 3)
    ctx.line_to(p[1] + 3, p[0] + 3)
    ctx.line_to(p[1] - 3, p[0] + 3)
    ctx.close_path()
    if fill:
        ctx.fill_style = fill
        ctx.fill()
    if stroke:
        ctx.stroke_style = stroke
        ctx.stroke()
    ctx.restore()


class LineGraphRegionsCanvasItem(CanvasItem.AbstractCanvasItem):

    """ Canvas item to draw the line plot itself. """

    def __init__(self):
        super(LineGraphRegionsCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.regions = list()

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        x_properties = self.data_info.x_properties if data_info else None
        if data_info and data_info.data is not None and x_properties:

            plot_rect = self.canvas_bounds
            plot_width = int(plot_rect[1][1]) - 1
            plot_height = int(plot_rect[1][0]) - 1
            plot_origin_y = int(plot_rect[0][0])

            # calculate the axes drawing info
            data_info.calculate_x_ticks(plot_width)

            data_left = x_properties.drawn_left_channel
            data_right = x_properties.drawn_right_channel

            def convert_coordinate_to_pixel(c):
                px = c * data_info.data.shape[0]
                return plot_rect.width * (px - data_left) / (data_right - data_left)

            for region in self.regions:
                region_channels = region.channels
                region_selected = region.selected
                index = region.index
                left_text = region.left_text
                right_text = region.right_text
                middle_text = region.middle_text
                level = plot_rect.bottom - plot_rect.height * 0.8 + index * 8
                drawing_context.save()
                drawing_context.begin_path()
                last_x = None
                for region_channel in region_channels:
                    x = convert_coordinate_to_pixel(region_channel)
                    drawing_context.move_to(x, plot_origin_y)
                    drawing_context.line_to(x, plot_origin_y + plot_height)
                    drawing_context.line_width = 1
                    drawing_context.stroke_style = '#F00'
                    if not region_selected:
                        drawing_context.line_dash = 2
                    drawing_context.stroke()
                    if last_x is not None:
                        mid_x = (last_x + x) * 0.5
                        drawing_context.move_to(last_x, level)
                        drawing_context.line_to(mid_x - 3, level)
                        drawing_context.move_to(mid_x + 3, level)
                        drawing_context.line_to(x - 3, level)
                        drawing_context.stroke()
                        drawing_context.line_dash = 0
                        if region_selected:
                            draw_marker(drawing_context, (level, mid_x), fill='#F00', stroke='#F00')
                            drawing_context.fill_style = '#F00'
                            drawing_context.font = "{0:d}px".format(self.font_size)
                            if middle_text:
                                drawing_context.text_align = "center"
                                drawing_context.text_baseline = "bottom"
                                drawing_context.fill_text(middle_text, mid_x, level - 6)
                            if left_text:
                                drawing_context.text_align = "right"
                                drawing_context.text_baseline = "center"
                                drawing_context.fill_text(left_text, last_x - 4, level)
                            if right_text:
                                drawing_context.text_align = "left"
                                drawing_context.text_baseline = "center"
                                drawing_context.fill_text(right_text, x + 4, level)
                        else:
                            draw_marker(drawing_context, (level, mid_x), stroke='#F00')
                    last_x = x
                drawing_context.restore()


class LineGraphHorizontalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):

    """ Canvas item to draw the horizontal tick marks. """

    def __init__(self):
        super(LineGraphHorizontalAxisTicksCanvasItem, self).__init__()
        self.data_info = None
        self.tick_height = 4
        self.sizing.minimum_height = self.tick_height
        self.sizing.maximum_height = self.tick_height

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info:

            plot_width = int(self.canvas_size[1]) - 1

            # extract the data we need for drawing x-axis
            x_ticks = data_info.calculate_x_ticks(plot_width)

            # draw the tick marks
            drawing_context.save()
            for x, _ in x_ticks:
                drawing_context.begin_path()
                drawing_context.move_to(x, 0)
                drawing_context.line_to(x, self.tick_height)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
            drawing_context.restore()


class LineGraphHorizontalAxisScaleCanvasItem(CanvasItem.AbstractCanvasItem):

    """ Canvas item to draw the horizontal scale. """

    def __init__(self):
        super(LineGraphHorizontalAxisScaleCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_height = self.font_size + 4
        self.sizing.maximum_height = self.font_size + 4

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info:

            height = self.canvas_size[0]
            plot_width = int(self.canvas_size[1]) - 1

            # extract the data we need for drawing x-axis
            x_ticks = data_info.calculate_x_ticks(plot_width)

            # draw the tick marks
            drawing_context.save()
            drawing_context.font = "{0:d}px".format(self.font_size)
            for x, label in x_ticks:
                drawing_context.text_align = "center"
                drawing_context.text_baseline = "middle"
                drawing_context.fill_style = "#000"
                drawing_context.fill_text(label, x, height * 0.5)
            drawing_context.restore()


class LineGraphHorizontalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):

    """ Canvas item to draw the horizontal label. """

    def __init__(self):
        super(LineGraphHorizontalAxisLabelCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_height = self.font_size + 4
        self.sizing.maximum_height = self.font_size + 4

    def size_to_content(self):
        """ Size the canvas item to the proper height. """
        self.sizing.minimum_height = 0
        self.sizing.maximum_height = 0
        data_info = self.data_info
        if data_info:
            if data_info.spatial_calibration and data_info.spatial_calibration.units:
                self.sizing.minimum_height = self.font_size + 4
                self.sizing.maximum_height = self.font_size + 4

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info:

            # draw the horizontal axis
            if data_info.spatial_calibration and data_info.spatial_calibration.units:

                height = self.canvas_size[0]
                plot_width = int(self.canvas_size[1]) - 1

                drawing_context.save()
                drawing_context.text_align = "center"
                drawing_context.text_baseline = "middle"
                drawing_context.fill_style = "#000"
                value_str = u"({0})".format(data_info.spatial_calibration.units)
                drawing_context.font = "{0:d}px".format(self.font_size)
                drawing_context.fill_text(value_str, plot_width * 0.5, height * 0.5)
                drawing_context.restore()


class LineGraphVerticalAxisTicksCanvasItem(CanvasItem.AbstractCanvasItem):

    """ Canvas item to draw the vertical tick marks. """

    def __init__(self):
        super(LineGraphVerticalAxisTicksCanvasItem, self).__init__()
        self.data_info = None
        self.tick_width = 4
        self.sizing.minimum_width = self.tick_width
        self.sizing.maximum_width = self.tick_width

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info:

            # canvas size
            width = self.canvas_size[1]
            plot_height = int(self.canvas_size[0]) - 1

            # extract the data we need for drawing y-axis
            y_ticks = data_info.calculate_y_ticks(plot_height)

            # draw the y_ticks and labels
            drawing_context.save()
            for y, _ in y_ticks:
                drawing_context.begin_path()
                drawing_context.move_to(width, y)
                drawing_context.line_to(width - self.tick_width, y)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
            drawing_context.restore()


class LineGraphVerticalAxisScaleCanvasItem(CanvasItem.AbstractCanvasItem):

    """ Canvas item to draw the vertical scale. """

    def __init__(self):
        super(LineGraphVerticalAxisScaleCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12

    def size_to_content(self, get_font_metrics_fn):
        """ Size the canvas item to the proper width, the maximum of any label. """
        self.sizing.minimum_width = 0
        self.sizing.maximum_width = 0

        y_properties = self.data_info.y_properties if self.data_info else None
        if y_properties:

            # calculate the width based on the label lengths
            font = "{0:d}px".format(self.font_size)

            max_width = 0
            y_range = y_properties.calibrated_data_max - y_properties.calibrated_data_min
            label = (u"{0:0." + u"{0:d}".format(y_properties.y_tick_precision) + "f}").format(
                y_properties.calibrated_data_max + y_range * 5)
            max_width = max(max_width, get_font_metrics_fn(font, label).width)
            label = (u"{0:0." + u"{0:d}".format(y_properties.y_tick_precision) + "f}").format(
                y_properties.calibrated_data_min - y_range * 5)
            max_width = max(max_width, get_font_metrics_fn(font, label).width)

            self.sizing.minimum_width = max_width
            self.sizing.maximum_width = max_width

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info:

            # canvas size
            width = self.canvas_size[1]
            plot_height = int(self.canvas_size[0]) - 1

            # extract the data we need for drawing y-axis
            y_ticks = data_info.calculate_y_ticks(plot_height)

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
                drawing_context.fill_text(label, width, y)
            drawing_context.restore()


class LineGraphVerticalAxisLabelCanvasItem(CanvasItem.AbstractCanvasItem):

    """ Canvas item to draw the vertical label. """

    def __init__(self):
        super(LineGraphVerticalAxisLabelCanvasItem, self).__init__()
        self.data_info = None
        self.font_size = 12
        self.sizing.minimum_width = self.font_size + 4
        self.sizing.maximum_width = self.font_size + 4

    def size_to_content(self):
        """ Size the canvas item to the proper width. """
        self.sizing.minimum_width = 0
        self.sizing.maximum_width = 0
        data_info = self.data_info
        if data_info:
            if data_info.intensity_calibration and data_info.intensity_calibration.units:
                self.sizing.minimum_width = self.font_size + 4
                self.sizing.maximum_width = self.font_size + 4

    def _repaint(self, drawing_context):

        # draw the data, if any
        data_info = self.data_info
        if data_info:

            # draw
            if data_info.intensity_calibration and data_info.intensity_calibration.units:
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
                drawing_context.font = "{0:d}px".format(self.font_size)
                drawing_context.fill_text(u"{0} ({1})".format(_("Intensity"), data_info.intensity_calibration.units), x, y)
                drawing_context.translate(x, y)
                drawing_context.rotate(+math.pi*0.5)
                drawing_context.translate(-x, -y)
                drawing_context.restore()

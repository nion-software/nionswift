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


def get_drawn_data_limits(raw_data_min, raw_data_max, calibration=None):
    """ Return drawn data limits after converting calibrated limits to pretty values. """
    calibrated_data_min, calibrated_data_max = get_calibrated_data_limits(raw_data_min, raw_data_max, calibration)
    calibrated_data_min = 0.0 if calibrated_data_min > 0 else calibrated_data_min
    calibrated_data_max = 0.0 if calibrated_data_max < 0 else calibrated_data_max
    pretty_calibrated_data_max = Geometry.make_pretty(calibrated_data_max, round_up=True)
    pretty_calibrated_data_min = Geometry.make_pretty(calibrated_data_min, round_up=True)
    if calibration:
        drawn_data_min = calibration.convert_from_calibrated_value(pretty_calibrated_data_min)
        drawn_data_max = calibration.convert_from_calibrated_value(pretty_calibrated_data_max)
    else:
        drawn_data_min = pretty_calibrated_data_min
        drawn_data_max = pretty_calibrated_data_max
    return drawn_data_min, drawn_data_max


class LineGraphCanvasItem(CanvasItem.AbstractCanvasItem):

    golden_ratio = 1.618

    def __init__(self):
        super(LineGraphCanvasItem, self).__init__()
        self.data = None
        self.data_min = None
        self.data_max = None
        self.spatial_calibration = None
        self.intensity_calibration = None
        self.draw_grid = True
        self.draw_captions = True
        self.draw_frame = True
        self.background_color = "#888"
        self.graph_background_color = "#FFF"

    def __get_plot_rect(self):
        rect = ((0, 0), self.canvas_size)
        rect = Geometry.fit_to_aspect_ratio(rect, self.golden_ratio)
        plot_origin_y = rect[0][0] + self.top_margin
        plot_origin_x = rect[0][1] + self.left_margin
        plot_height = rect[1][0] - self.bottom_caption_height - self.top_margin
        plot_width = rect[1][1] - self.left_margin - self.right_margin
        plot_rect = ((plot_origin_y, plot_origin_x), (plot_height, plot_width))
        return plot_rect
    plot_rect = property(__get_plot_rect)

    def update_layout(self, canvas_origin, canvas_size):
        super(LineGraphCanvasItem, self).update_layout(canvas_origin, canvas_size)
        # update internal size variables
        canvas_width = canvas_size[1]
        canvas_height = canvas_size[0]
        if self.draw_captions:
            self.font_size = max(9, min(13, int(canvas_height/25.0)))
            self.left_margin = max(36, min(60, int(canvas_width/8.0))) + (self.font_size + 4)
            self.top_margin = int((self.font_size + 4) / 2.0 + 1.5)
            self.bottom_caption_height = self.top_margin + int(self.font_size + 4) * 2
            self.right_margin = 12
        else:
            self.left_margin = 0
            self.top_margin = 0
            self.bottom_caption_height = 0
            self.right_margin = 1

    def map_mouse_to_position(self, mouse, data_size):
        plot_rect = self.plot_rect
        mouse_x = mouse[1] - plot_rect[0][1]  # 436
        mouse_y = mouse[0] - plot_rect[0][0]
        if mouse_x > 0 and mouse_x < plot_rect[1][1] and mouse_y > 0 and mouse_y < plot_rect[1][0]:
            return (data_size[0] * mouse_x / plot_rect[1][1], )
        # not in bounds
        return None

    def _repaint(self, drawing_context):

        # draw the data, if any
        if (self.data is not None and len(self.data) > 0):

            # canvas size
            canvas_width = self.canvas_size[1]
            canvas_height = self.canvas_size[0]

            rect = ((0, 0), (canvas_height, canvas_width))

            drawing_context.save()

            drawing_context.begin_path()
            drawing_context.rect(rect[0][1], rect[0][0], rect[1][1], rect[1][0])
            drawing_context.fill_style = self.background_color
            drawing_context.fill()

            rect = Geometry.fit_to_aspect_ratio(rect, self.golden_ratio)
            unit_offset = int(self.font_size + 4) if self.draw_captions else 0
            intensity_rect = ((rect[0][0] + self.top_margin, rect[0][1] + unit_offset), (rect[1][0] - self.bottom_caption_height - self.top_margin, self.left_margin - unit_offset))
            plot_rect = self.plot_rect
            plot_width = int(plot_rect[1][1])
            plot_height = int(plot_rect[1][0])
            plot_origin_x = int(plot_rect[0][1])
            plot_origin_y = int(plot_rect[0][0])

            # draw the background
            drawing_context.begin_path()
            drawing_context.rect(int(rect[0][1]), int(rect[0][0]), int(rect[1][1]), int(rect[1][0]))
            drawing_context.fill_style = self.graph_background_color
            drawing_context.fill()
            # calculate the intensity scale
            vertical_tick_count = 4
            raw_data_min = self.data_min if self.data_min else numpy.amin(self.data)
            raw_data_max = self.data_max if self.data_max else numpy.amax(self.data)
            drawn_data_min, drawn_data_max = get_drawn_data_limits(raw_data_min, raw_data_max, self.intensity_calibration)
            drawn_data_range = drawn_data_max - drawn_data_min
            tick_size = intensity_rect[1][0] / vertical_tick_count
            # calculate yticks
            yticks = list()
            for i in range(vertical_tick_count+1):
                y = int(intensity_rect[0][0] + intensity_rect[1][0] - tick_size * i)
                if i == 0:
                    y = plot_origin_y + plot_height  # match it with the plot_rect
                elif i == vertical_tick_count:
                    y = plot_origin_y  # match it with the plot_rect
                value = drawn_data_min + drawn_data_range * float(i) / vertical_tick_count
                label = self.intensity_calibration.convert_to_calibrated_value_str(value, include_units=False) if self.intensity_calibration is not None else "{0:g}".format(value)
                yticks.append((y, label))
            # draw the yticks and labels
            drawing_context.save()
            if self.draw_captions:
                drawing_context.text_baseline = "middle"
                drawing_context.font = "{0:d}px".format(self.font_size)
            for y, label in yticks:
                w = 4
                drawing_context.begin_path()
                if self.draw_grid:
                    drawing_context.move_to(plot_origin_x, y)
                    drawing_context.line_to(plot_origin_x + plot_width, y)
                if self.draw_captions:
                    drawing_context.move_to(intensity_rect[0][1] + intensity_rect[1][1], y)
                    drawing_context.line_to(intensity_rect[0][1] + intensity_rect[1][1] - w, y)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
                if self.draw_captions:
                    drawing_context.text_align = "right"
                    drawing_context.fill_style = "#000"
                    drawing_context.fill_text(label, intensity_rect[0][1] + intensity_rect[1][1] - 8, y)
            if self.draw_captions and self.intensity_calibration and self.intensity_calibration.units:
                drawing_context.text_align = "center"
                drawing_context.text_baseline = "bottom"
                drawing_context.fill_style = "#000"
                x = intensity_rect[0][1]
                y = int(intensity_rect[0][0] + intensity_rect[1][0] * 0.5)
                drawing_context.translate(x, y)
                drawing_context.rotate(-math.pi*0.5)
                drawing_context.translate(-x, -y)
                drawing_context.fill_text(u"{0} ({1})".format(_("Intensity"), self.intensity_calibration.units), x, y)
                drawing_context.translate(x, y)
                drawing_context.rotate(+math.pi*0.5)
                drawing_context.translate(-x, -y)
            drawing_context.restore()
            # draw the horizontal axis
            data_len = self.data.shape[0]
            drawing_context.save()
            if self.draw_captions:
                # approximate tick count
                horizontal_tick_count = min(max(2, int(plot_width / 100)), 10)
                # calculate the horizontal tick spacing in spatial units
                horizontal_tick_spacing = float(plot_width) / horizontal_tick_count
                horizontal_tick_spacing = data_len * horizontal_tick_spacing / plot_width
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
                # draw the tick marks
                x = horizontal_tick_min + plot_origin_x
                while horizontal_tick_spacing > 0.0 and x < plot_origin_x + plot_width:  # sanity check along with regular loop
                    drawing_context.begin_path()
                    if self.draw_grid:
                        drawing_context.move_to(x, plot_origin_y)
                        drawing_context.line_to(x, plot_origin_y + plot_height)
                    if self.draw_captions:
                        drawing_context.move_to(x, plot_origin_y + plot_height)
                        drawing_context.line_to(x, plot_origin_y + plot_height + 4)
                    drawing_context.line_width = 1
                    drawing_context.stroke_style = '#888'
                    drawing_context.stroke()
                    if self.draw_captions:
                        value = data_len * float(x - plot_origin_x) / plot_width
                        value_str = self.spatial_calibration.convert_to_calibrated_value_str(value, include_units=False) if self.spatial_calibration else "{0:g}".format(value)
                        drawing_context.text_align = "center"
                        drawing_context.fill_style = "#000"
                        drawing_context.fill_text(value_str, x, plot_origin_y + plot_height + unit_offset)
                    x += plot_width * horizontal_tick_spacing / data_len
                if self.draw_captions and self.spatial_calibration and self.spatial_calibration.units:
                    drawing_context.text_align = "center"
                    drawing_context.fill_style = "#000"
                    value_str = u"({0})".format(self.spatial_calibration.units)
                    drawing_context.fill_text(value_str, plot_origin_x + plot_width / 2, plot_origin_y + plot_height + unit_offset * 2)
            drawing_context.restore()
            # draw the line plot itself
            drawing_context.save()
            drawing_context.begin_path()
            if drawn_data_range != 0.0:
                baseline = plot_origin_y + plot_height - (plot_height * float(0.0 - drawn_data_min) / drawn_data_range)
                drawing_context.move_to(plot_origin_x, baseline)
                for i in xrange(0, plot_width, 2):
                    px = plot_origin_x + i
                    data_index = int(data_len*float(i)/plot_width)
                    # plot_origin_y is the TOP of the drawing
                    # py extends DOWNWARDS
                    py = plot_origin_y + plot_height - (plot_height * float(self.data[data_index] - drawn_data_min) / drawn_data_range)
                    py = max(plot_origin_y, py)
                    drawing_context.line_to(px, py)
                    drawing_context.line_to(px + 2, py)
                # finish off last line
                px = plot_origin_x + plot_width
                data_index = data_len - 1
                py = plot_origin_y + plot_height - (plot_height * float(self.data[data_index] - drawn_data_min) / drawn_data_range)
                drawing_context.line_to(plot_origin_x + plot_width, baseline)
            else:
                drawing_context.move_to(plot_origin_x, plot_origin_y + plot_height * 0.5)
                drawing_context.line_to(plot_origin_x + plot_width, plot_origin_y + plot_height * 0.5)
            drawing_context.restore()
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

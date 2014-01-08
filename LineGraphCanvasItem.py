# standard libraries
import logging

# third party libraries
import numpy

# local libraries
from nion.swift import CanvasItem
from nion.swift import Graphics


class LineGraphCanvasItem(CanvasItem.AbstractCanvasItem):

    golden_ratio = 1.618

    def __init__(self):
        super(LineGraphCanvasItem, self).__init__()
        self.data = None
        self.draw_grid = True
        self.draw_captions = True
        self.draw_frame = True
        self.background_color = "#888"
        self.graph_background_color = "#FFF"

    def __get_plot_rect(self):
        rect = ((0, 0), self.canvas_size)
        rect = Graphics.fit_to_aspect_ratio(rect, self.golden_ratio)
        plot_rect = ((rect[0][0] + self.top_margin, rect[0][1] + self.left_caption_width), (rect[1][0] - self.bottom_caption_height - self.top_margin, rect[1][1] - self.left_caption_width - self.right_margin))
        return plot_rect
    plot_rect = property(__get_plot_rect)

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

            if self.draw_captions:
                self.font_size = max(9, min(13, int(canvas_height/25.0)))
                self.left_caption_width = max(36, min(60, int(canvas_width/8.0)))
                self.top_margin = int((self.font_size + 4) / 2.0 + 1.5)
                self.bottom_caption_height = self.top_margin
                self.right_margin = 6
            else:
                self.left_caption_width = 0
                self.top_margin = 0
                self.bottom_caption_height = 0
                self.right_margin = 1

            rect = ((0, 0), (canvas_height, canvas_width))

            drawing_context.save()

            drawing_context.begin_path()
            drawing_context.rect(rect[0][1], rect[0][0], rect[1][1], rect[1][0])
            drawing_context.fill_style = self.background_color
            drawing_context.fill()

            rect = Graphics.fit_to_aspect_ratio(rect, self.golden_ratio)
            intensity_rect = ((rect[0][0] + self.top_margin, rect[0][1]), (rect[1][0] - self.bottom_caption_height - self.top_margin, self.left_caption_width))
            caption_rect = ((rect[0][0] + rect[1][0] - self.bottom_caption_height, rect[0][1] + self.left_caption_width), (self.bottom_caption_height, rect[1][1] - self.left_caption_width - self.right_margin))
            plot_rect = self.plot_rect
            plot_width = int(plot_rect[1][1])
            plot_height = int(plot_rect[1][0])
            plot_origin_x = int(plot_rect[0][1])
            plot_origin_y = int(plot_rect[0][0])

            data_min = numpy.amin(self.data)
            data_max = numpy.amax(self.data)
            data_len = self.data.shape[0]
            # draw the background
            drawing_context.begin_path()
            drawing_context.rect(int(rect[0][1]), int(rect[0][0]), int(rect[1][1]), int(rect[1][0]))
            drawing_context.fill_style = self.graph_background_color
            drawing_context.fill()
            # draw the intensity scale
            vertical_tick_count = 4
            data_max = Graphics.make_pretty(data_max, round_up=True)
            data_min = Graphics.make_pretty(data_min, round_up=True)
            data_min = data_min if data_min < 0 else 0.0
            data_range = data_max - data_min
            tick_size = intensity_rect[1][0] / vertical_tick_count
            if self.draw_captions:
                drawing_context.text_baseline = "middle"
                drawing_context.font = "{0:d}px".format(self.font_size)
            for i in range(vertical_tick_count+1):
                drawing_context.begin_path()
                y = int(intensity_rect[0][0] + intensity_rect[1][0] - tick_size * i)
                w = 3
                if i == 0:
                    y = plot_origin_y + plot_height  # match it with the plot_rect
                    w = 6
                elif i == vertical_tick_count:
                    y = plot_origin_y  # match it with the plot_rect
                    w = 6
                if self.draw_grid:
                    drawing_context.move_to(plot_rect[0][1], y)
                    drawing_context.line_to(plot_rect[0][1] + plot_rect[1][1], y)
                if self.draw_captions:
                    drawing_context.move_to(intensity_rect[0][1] + intensity_rect[1][1], y)
                    drawing_context.line_to(intensity_rect[0][1] + intensity_rect[1][1] - w, y)
                drawing_context.line_width = 1
                drawing_context.stroke_style = '#888'
                drawing_context.stroke()
                if self.draw_captions:
                    drawing_context.fill_style = "#000"
                    drawing_context.fill_text("{0:g}".format(data_min + data_range * float(i) / vertical_tick_count), 8, y)
                #logging.debug("i %s %s", i, data_max * float(i) / vertical_tick_count)
            if self.draw_captions:
                drawing_context.text_baseline = "alphabetic"
            drawing_context.line_width = 1
            # draw the horizontal axis
            # draw the line plot itself
            drawing_context.begin_path()
            if data_range != 0.0:
                baseline = plot_origin_y + plot_height - (plot_height * float(0.0 - data_min) / data_range)
                drawing_context.move_to(plot_origin_x, baseline)
                for i in xrange(0, plot_width, 2):
                    px = plot_origin_x + i
                    py = plot_origin_y + plot_height - (plot_height * float(self.data[int(data_len*float(i)/plot_width)] - data_min) / data_range)
                    drawing_context.line_to(px, py)
                    drawing_context.line_to(px + 2, py)
                # finish off last line
                px = plot_origin_x + plot_width
                py = plot_origin_y + plot_height - (plot_height * float(self.data[data_len-1] - data_min) / data_range)
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

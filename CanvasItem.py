# standard libraries
import logging
import threading

# third party libraries
import numpy

# local libraries
from nion.swift import Graphics


# represents an object to be drawn on a canvas
# the canvas object is responsible for drawing its content
# after which it tells its container that it has updated
# content. the container will send the updated content to
# the ui canvas which will schedule it to be drawn by the ui.
class AbstractCanvasItem(object):

    def __init__(self):
        self._canvas = None
        self.__layer = None
        self.__container = None
        self.__container_mutex = threading.RLock()
        self.__needs_update = True
        self.canvas_size = None
        self.canvas_origin = None

    def close(self):
        if self.__layer:
            self._canvas.remove_layer(self.__layer)
            self.__layer = None

    def __get_container(self):
        return self.__container
    def __set_container(self, container):
        with self.__container_mutex:
            self.__container = container
    container = property(__get_container, __set_container)

    # set the canvas
    def _set_canvas(self, canvas):
        self._canvas = canvas

    # update the layout (canvas_size for now)
    def update_layout(self, canvas_origin, canvas_size):
        self.canvas_origin = canvas_origin
        self.canvas_size = canvas_size

    # mark this object as needing an update
    def update(self):
        self.__needs_update = True

    # redraws the object if needed, then informs the container
    # that the item has been redrawn.
    # this should typically be called on a thread.
    def repaint_if_needed(self):
        if self.__needs_update and self.canvas_size is not None:
            if not self.__layer:
                self.__layer = self._canvas.create_layer()
            drawing_context = self._create_drawing_context()
            drawing_context.save()
            drawing_context.translate(self.canvas_origin[1], self.canvas_origin[0])
            self._repaint(drawing_context)
            drawing_context.restore()
            # TODO: this next statement should happen under a mutex
            self.__layer.drawing_context.copy_from(drawing_context)
            self.__needs_update = False
            self.draw()

    # create an extra drawing context
    def _create_drawing_context(self):
        return self._canvas.create_drawing_context()

    # repaint should typically be called on a thread
    # layout (canvas_size) will always be valid if this is invoked
    def _repaint(self, drawing_context):
        assert self.canvas_size is not None

    # default is to pass the draw message up the container hierarchy
    def draw(self):
        with self.__container_mutex:
            container = self.__container
        if container:
            container.draw()

    def is_point_inside(self, x, y):
        if x < self.canvas_origin[1] or x >= self.canvas_origin[1] + self.canvas_size[1]:
            return False
        if y < self.canvas_origin[0] or y >= self.canvas_origin[0] + self.canvas_size[0]:
            return False
        return True

    def mouse_clicked(self, x, y, modifiers):
        return False

    def mouse_double_clicked(self, x, y, modifiers):
        return False

    def mouse_entered(self):
        return False

    def mouse_exited(self):
        return False

    def mouse_pressed(self, x, y, modifiers):
        return False

    def mouse_released(self, x, y, modifiers):
        return False

    def mouse_position_changed(self, x, y, modifiers):
        return False

    def key_pressed(self, key):
        return False

    def drag_enter(self, mime_data):
        return "ignore"

    def drag_leave(self):
        return "ignore"

    def drag_move(self, mime_data, x, y):
        return "ignore"

    def drop(self, mime_data, x, y):
        return "ignore"


class CanvasItemLayout(object):

    def __init__(self):
        pass

    def layout(self, canvas_origin, canvas_size, canvas_items):
        for canvas_item in canvas_items:
            canvas_item.update_layout(canvas_origin, canvas_size)


class CanvasItemColumnLayout(object):

    def __init__(self, origin=None, spacing=None, fraction=None, min_width=None, max_width=None):
        self.origin = origin
        self.spacing = spacing if spacing else 0
        self.fraction = fraction
        self.min_width = min_width
        self.max_width = max_width

    def layout(self, canvas_origin, canvas_size, canvas_items):
        canvas_item_origin = self.origin if self.origin else (0, 0)
        # prefer min_width pixels wide, but not more than fraction of the canvas size, but a maximum of max_width pixels wide
        min_width = self.min_width if self.min_width else canvas_size[1]
        max_width = self.max_width if self.max_width else canvas_size[1]
        fraction = self.fraction if self.fraction else 1.0
        canvas_item_width = max(min(max_width, int(canvas_size[1] * fraction)), min_width)
        for canvas_item in canvas_items:
            # this is not a complete layout -- just something to get by for now
            if hasattr(canvas_item, "preferred_height"):
                canvas_item_height = canvas_item.preferred_height
            elif hasattr(canvas_item, "preferred_aspect_ratio"):
                canvas_item_height = int(canvas_item_width / canvas_item.preferred_aspect_ratio)
            else:  # use up remaining height
                canvas_item_height = canvas_size[1] - canvas_item_origin[1]
            canvas_item_size = (canvas_item_height, canvas_item_width)
            canvas_item.update_layout(canvas_item_origin, canvas_item_size)
            canvas_item_origin = (canvas_item_origin[0] + canvas_item_height + self.spacing, canvas_item_origin[1])


class CanvasItemRowLayout(object):

    def __init__(self, origin=None, spacing=None, fraction=None, min_height=None, max_height=None):
        self.origin = origin
        self.spacing = spacing if spacing else 0
        self.fraction = fraction
        self.min_height = min_height
        self.max_height = max_height

    def layout(self, canvas_origin, canvas_size, canvas_items):
        canvas_item_origin = self.origin if self.origin else (0, 0)
        # prefer min_height pixels wide, but not more than fraction of the canvas size, but a maximum of max_height pixels wide
        min_height = self.min_height if self.min_height else canvas_size[1]
        max_height = self.max_height if self.max_height else canvas_size[1]
        fraction = self.fraction if self.fraction else 1.0
        canvas_item_height = max(min(max_height, int(canvas_size[1] * fraction)), min_height)
        for canvas_item in canvas_items:
            # this is not a complete layout -- just something to get by for now
            if hasattr(canvas_item, "preferred_width"):
                canvas_item_width = canvas_item.preferred_width
            elif hasattr(canvas_item, "preferred_aspect_ratio"):
                canvas_item_width = int(canvas_item_height * canvas_item.preferred_aspect_ratio)
            else:  # use up remaining height
                canvas_item_width = canvas_size[0] - canvas_item_origin[0]
            canvas_item_size = (canvas_item_height, canvas_item_width)
            canvas_item.update_layout(canvas_item_origin, canvas_item_size)
            canvas_item_origin = (canvas_item_origin[0], canvas_item_origin[1] + canvas_item_width + self.spacing)


class CanvasItemComposition(AbstractCanvasItem):

    def __init__(self):
        super(CanvasItemComposition, self).__init__()
        self.__canvas_items = []
        self.layout = CanvasItemLayout()
        self.__mouse_canvas_item = None

    def close(self):
        for canvas_item in self.__canvas_items:
            canvas_item.close()
        super(CanvasItemComposition, self).close()

    def __get_canvas_items(self):
        return self.__canvas_items
    canvas_items = property(__get_canvas_items)

    def _set_canvas(self, canvas):
        super(CanvasItemComposition, self)._set_canvas(canvas)
        for canvas_item in self.__canvas_items:
            canvas_item._set_canvas(canvas)

    def update_layout(self, canvas_origin, canvas_size):
        super(CanvasItemComposition, self).update_layout(canvas_origin, canvas_size)
        self.layout.layout(canvas_origin, canvas_size, self.__canvas_items)

    def add_canvas_item(self, canvas_item):
        self.__canvas_items.append(canvas_item)
        canvas_item.container = self
        canvas_item._set_canvas(self._canvas)
        # update the layout if origin and size already known
        if self.canvas_origin and self.canvas_size:
            self.update_layout(self.canvas_origin, self.canvas_size)
            self.update()

    def remove_canvas_item(self, canvas_item):
        canvas_item.container = None
        self.__canvas_items.remove(canvas_item)
        # update the layout if origin and size already known
        if self.canvas_origin and self.canvas_size:
            self.update_layout(self.canvas_origin, self.canvas_size)
            self.update()

    def update(self):
        super(CanvasItemComposition, self).update()
        for canvas_item in self.__canvas_items:
            canvas_item.update()

    def repaint_if_needed(self):
        super(CanvasItemComposition, self).repaint_if_needed()
        for canvas_item in self.__canvas_items:
            canvas_item.repaint_if_needed()

    def mouse_clicked(self, x, y, modifiers):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.is_point_inside(x, y):
                x -= canvas_item.canvas_origin[1]
                y -= canvas_item.canvas_origin[0]
                if canvas_item.mouse_clicked(x, y, modifiers):
                    return True
        return False

    def mouse_double_clicked(self, x, y, modifiers):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.is_point_inside(x, y):
                x -= canvas_item.canvas_origin[1]
                y -= canvas_item.canvas_origin[0]
                if canvas_item.mouse_double_clicked(x, y, modifiers):
                    return True
        return False

    def mouse_entered(self):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.mouse_entered():
                return True
        return False

    def mouse_exited(self):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.mouse_exited():
                return True
        return False

    def mouse_pressed(self, x, y, modifiers):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.is_point_inside(x, y):
                x -= canvas_item.canvas_origin[1]
                y -= canvas_item.canvas_origin[0]
                if canvas_item.mouse_pressed(x, y, modifiers):
                    self.__mouse_canvas_item = canvas_item
                    return True
        return False

    def mouse_released(self, x, y, modifiers):
        # only the canvas item that accepted the mouse pressed gets mouse released
        if self.__mouse_canvas_item:
            x -= self.__mouse_canvas_item.canvas_origin[1]
            y -= self.__mouse_canvas_item.canvas_origin[0]
            self.__mouse_canvas_item.mouse_released(x, y, modifiers)
            self.__mouse_canvas_item = None
        return False

    def mouse_position_changed(self, x, y, modifiers):
        # always cgive the mouse canvas item priority (for tracking outside bounds)
        if self.__mouse_canvas_item:
            x -= self.__mouse_canvas_item.canvas_origin[1]
            y -= self.__mouse_canvas_item.canvas_origin[0]
            if self.__mouse_canvas_item.mouse_position_changed(x, y, modifiers):
                return True
        # now give other canvas items a chance
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.is_point_inside(x, y):
                x -= canvas_item.canvas_origin[1]
                y -= canvas_item.canvas_origin[0]
                if canvas_item.mouse_position_changed(x, y, modifiers):
                    return True
        return False

    def key_pressed(self, key):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.key_pressed(key):
                return True
        return False

    def drag_enter(self, mime_data):
        for canvas_item in reversed(self.__canvas_items):
            action = canvas_item.drag_enter(mime_data)
            if action != "ignore":
                return action
        return "ignore"

    def drag_leave(self):
        for canvas_item in reversed(self.__canvas_items):
            action = canvas_item.drag_leave()
            if action != "ignore":
                return action
        return "ignore"

    def drag_move(self, mime_data, x, y):
        for canvas_item in reversed(self.__canvas_items):
            action = canvas_item.drag_move(mime_data, x, y)
            if action != "ignore":
                return action
        return "ignore"

    def drop(self, mime_data, x, y):
        for canvas_item in reversed(self.__canvas_items):
            action = canvas_item.drop(mime_data, x, y)
            if action != "ignore":
                return action
        return "ignore"


class RootCanvasItem(CanvasItemComposition):

    def __init__(self, ui, properties=None):
        super(RootCanvasItem, self).__init__()
        self._canvas = ui.create_canvas_widget(properties)
        self._canvas.on_size_changed = lambda width, height: self.size_changed(width, height)
        self._canvas.on_mouse_clicked = lambda x, y, modifiers: self.mouse_clicked(x, y, modifiers)
        self._canvas.on_mouse_double_clicked = lambda x, y, modifiers: self.mouse_double_clicked(x, y, modifiers)
        self._canvas.on_mouse_entered = lambda: self.mouse_entered()
        self._canvas.on_mouse_exited = lambda: self.mouse_exited()
        self._canvas.on_mouse_pressed = lambda x, y, modifiers: self.mouse_pressed(x, y, modifiers)
        self._canvas.on_mouse_released = lambda x, y, modifiers: self.mouse_released(x, y, modifiers)
        self._canvas.on_mouse_position_changed = lambda x, y, modifiers: self.mouse_position_changed(x, y, modifiers)
        self._canvas.on_key_pressed = lambda key: self.key_pressed(key)
        self._canvas.on_focus_changed = lambda focused: self.__focus_changed(focused)
        self._canvas.on_drag_enter = lambda mime_data: self.drag_enter(mime_data)
        self._canvas.on_drag_leave = lambda: self.drag_leave()
        self._canvas.on_drag_move = lambda mime_data, x, y: self.drag_move(mime_data, x, y)
        self._canvas.on_drop = lambda mime_data, x, y: self.drop(mime_data, x, y)
        self.on_focus_changed = None

    def __get_canvas(self):
        return self._canvas
    canvas = property(__get_canvas)

    def __get_focusable(self):
        return self.canvas.focusable
    def __set_focusable(self, focusable):
        self.canvas.focusable = focusable
    focusable = property(__get_focusable, __set_focusable)

    def draw(self):
        self._canvas.draw()

    def size_changed(self, width, height):
        if width > 0 and height > 0:
            self.update_layout((0, 0), (height, width))
            self.update()
            self.repaint_if_needed()

    def __focus_changed(self, focused):
        if self.on_focus_changed:
            self.on_focus_changed(focused)


class FocusRingCanvasItem(AbstractCanvasItem):

    def __init__(self):
        super(FocusRingCanvasItem, self).__init__()

        self.focused = False
        self.selected = False
        self.selected_style = "#CCC"  # TODO: platform dependent
        self.focused_style = "#3876D6"  # TODO: platform dependent

    def _repaint(self, drawing_context):

        if self.selected:

            # canvas size
            canvas_width = self.canvas_size[1]
            canvas_height = self.canvas_size[0]

            stroke_style = self.selected_style
            if self.focused:
                stroke_style = self.focused_style

            drawing_context.save()

            drawing_context.begin_path()
            drawing_context.rect(2, 2, canvas_width - 4, canvas_height - 4)
            drawing_context.line_join = "miter"
            drawing_context.stroke_style = stroke_style
            drawing_context.line_width = 4.0
            drawing_context.stroke()

            drawing_context.restore()


class LineGraphCanvasItem(AbstractCanvasItem):

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


class BitmapCanvasItem(AbstractCanvasItem):

    def __init__(self):
        super(BitmapCanvasItem, self).__init__()
        self.rgba_bitmap_data = None

    def _repaint(self, drawing_context):

        # draw the data, if any
        if self.rgba_bitmap_data is not None:

            # canvas size
            canvas_width = self.canvas_size[1]
            canvas_height = self.canvas_size[0]

            if canvas_height > 0 and canvas_width > 0:

                image_size = self.rgba_bitmap_data.shape

                rect = ((0, 0), (canvas_height, canvas_width))

                display_rect = Graphics.fit_to_size(rect, image_size)

                drawing_context.save()

                drawing_context.begin_path()
                drawing_context.rect(rect[0][1], rect[0][0], rect[1][1], rect[1][0])
                drawing_context.fill_style = "#888"
                drawing_context.fill()

                if display_rect and display_rect[1][0] > 0 and display_rect[1][1] > 0:
                    drawing_context.draw_image(self.rgba_bitmap_data, display_rect[0][1], display_rect[0][0], display_rect[1][1], display_rect[1][0])

                drawing_context.restore()

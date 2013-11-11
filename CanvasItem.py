# standard libraries
import logging

# third party libraries
# None

# local libraries
# None


# represents an object to be drawn on a canvas
# the canvas object is responsible for drawing its content
# after which it tells its container that it has updated
# content. the container will send the updated content to
# the ui canvas which will schedule it to be drawn by the ui.
class AbstractCanvasItem(object):

    def __init__(self):
        self._canvas = None
        self.__layer = None
        self.container = None
        self.__needs_update = False
        self.canvas_size = None

    def close(self):
        pass

    # set the canvas
    def _set_canvas(self, canvas):
        self._canvas = canvas

    # update the layout (canvas_size for now)
    def update_layout(self, canvas_size):
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
            drawing_context = self.__layer.drawing_context
            self.repaint(drawing_context)
            self.__needs_update = False
            self.container.draw()

    # repaint should typically be called on a thread
    # layout (canvas_size) will always be valid if this is invoked
    def repaint(self, drawing_context):
        assert self.canvas_size is not None

    # default is to pass the draw message up the container hierarchy
    def draw(self):
        self.container.draw()

    def mouse_double_clicked(self, x, y, modifiers):
        return False

    def mouse_pressed(self, x, y, modifiers):
        return False

    def mouse_released(self, x, y, modifiers):
        return False

    def mouse_position_changed(self, x, y, modifiers):
        return False


class CanvasItemComposition(AbstractCanvasItem):

    def __init__(self):
        super(CanvasItemComposition, self).__init__()
        self.__canvas_items = []

    def close(self):
        for canvas_item in self.__canvas_items:
            canvas_item.close()
        super(CanvasItemComposition, self).close()

    def _set_canvas(self, canvas):
        super(CanvasItemComposition, self)._set_canvas(canvas)
        for canvas_item in self.__canvas_items:
            canvas_item._set_canvas(canvas)

    def update_layout(self, canvas_size):
        super(CanvasItemComposition, self).update_layout(canvas_size)
        for canvas_item in self.__canvas_items:
            canvas_item.update_layout(canvas_size)

    def add_canvas_item(self, canvas_item):
        self.__canvas_items.append(canvas_item)
        canvas_item.container = self
        canvas_item._set_canvas(self._canvas)

    def update(self):
        super(CanvasItemComposition, self).update()
        for canvas_item in self.__canvas_items:
            canvas_item.update()

    def repaint_if_needed(self):
        for canvas_item in self.__canvas_items:
            canvas_item.repaint_if_needed()

    def mouse_double_clicked(self, x, y, modifiers):
        for canvas_item in self.__canvas_items:
            if canvas_item.mouse_double_clicked(x, y, modifiers):
                return True
        return False

    def mouse_pressed(self, x, y, modifiers):
        for canvas_item in self.__canvas_items:
            if canvas_item.mouse_pressed(x, y, modifiers):
                return True
        return False

    def mouse_released(self, x, y, modifiers):
        for canvas_item in self.__canvas_items:
            if canvas_item.mouse_released(x, y, modifiers):
                return True
        return False

    def mouse_position_changed(self, x, y, modifiers):
        for canvas_item in self.__canvas_items:
            if canvas_item.mouse_position_changed(x, y, modifiers):
                return True
        return False


class RootCanvasItem(CanvasItemComposition):

    def __init__(self, ui, properties):
        super(RootCanvasItem, self).__init__()
        self._canvas = ui.create_canvas_widget(properties)
        self._canvas.on_size_changed = lambda width, height: self.size_changed(width, height)
        self._canvas.on_mouse_double_clicked = lambda x, y, modifiers: self.mouse_double_clicked(x, y, modifiers)
        self._canvas.on_mouse_pressed = lambda x, y, modifiers: self.mouse_pressed(x, y, modifiers)
        self._canvas.on_mouse_released = lambda x, y, modifiers: self.mouse_released(x, y, modifiers)
        self._canvas.on_mouse_position_changed = lambda x, y, modifiers: self.mouse_position_changed(x, y, modifiers)

    def __get_canvas(self):
        return self._canvas
    canvas = property(__get_canvas)

    def draw(self):
        self._canvas.draw()

    def size_changed(self, width, height):
        if width > 0 and height > 0:
            self.update_layout((width, height))
            self.update()

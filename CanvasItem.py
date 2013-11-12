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
        self.canvas_size = None  # (width, height)

    def close(self):
        pass

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
            drawing_context.translate(self.canvas_origin[0], self.canvas_origin[1])
            self._repaint(drawing_context)
            drawing_context.restore()
            # TODO: this next statement should happen under a mutex
            self.__layer.drawing_context.copy_from(drawing_context)
            self.__needs_update = False
            self.container.draw()

    # create an extra drawing context
    def _create_drawing_context(self):
        return self._canvas.create_drawing_context()

    # repaint should typically be called on a thread
    # layout (canvas_size) will always be valid if this is invoked
    def _repaint(self, drawing_context):
        assert self.canvas_size is not None

    # default is to pass the draw message up the container hierarchy
    def draw(self):
        self.container.draw()

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

    def update_layout(self, canvas_origin, canvas_size):
        super(CanvasItemComposition, self).update_layout(canvas_origin, canvas_size)
        for canvas_item in self.__canvas_items:
            canvas_item.update_layout(canvas_origin, canvas_size)

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

    def mouse_clicked(self, x, y, modifiers):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.mouse_clicked(x, y, modifiers):
                return True
        return False

    def mouse_double_clicked(self, x, y, modifiers):
        for canvas_item in reversed(self.__canvas_items):
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
            if canvas_item.mouse_pressed(x, y, modifiers):
                return True
        return False

    def mouse_released(self, x, y, modifiers):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.mouse_released(x, y, modifiers):
                return True
        return False

    def mouse_position_changed(self, x, y, modifiers):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.mouse_position_changed(x, y, modifiers):
                return True
        return False

    def key_pressed(self, key):
        for canvas_item in reversed(self.__canvas_items):
            if canvas_item.key_pressed(key):
                return True
        return False


class PositionedCanvasItem(AbstractCanvasItem):

    def __init__(self, canvas_item):
        super(PositionedCanvasItem, self).__init__()
        self.canvas_item = canvas_item
        self.canvas_item.container = self
        self.__translation = (20, 16)

    def close(self):
        self.canvas_item.close()
        super(PositionedCanvasItem, self).close()

    def _set_canvas(self, canvas):
        super(PositionedCanvasItem, self)._set_canvas(canvas)
        self.canvas_item._set_canvas(canvas)

    def update_layout(self, canvas_origin, canvas_size):
        super(PositionedCanvasItem, self).update_layout(canvas_origin, canvas_size)
        golden_ratio = 1.618
        height = max(int(canvas_size[1]/8), 48)
        width = int(height * golden_ratio)
        self.canvas_item.update_layout(self.__translation, (width, height))

    def update(self):
        super(PositionedCanvasItem, self).update()
        self.canvas_item.update()

    def repaint_if_needed(self):
        self.canvas_item.repaint_if_needed()

    def __mouse_inside(self, x, y):
        if x < self.__translation[0] or x >= self.__translation[0] + self.canvas_item.canvas_size[0]:
            return False
        if y < self.__translation[1] or y >= self.__translation[1] + self.canvas_item.canvas_size[1]:
            return False
        return True

    def mouse_clicked(self, x, y, modifiers):
        if self.__mouse_inside(x, y):
            x -= self.__translation[0]
            y -= self.__translation[1]
            return self.canvas_item.mouse_clicked(x, y, modifiers)
        return False

    def mouse_double_clicked(self, x, y, modifiers):
        if self.__mouse_inside(x, y):
            x -= self.__translation[0]
            y -= self.__translation[1]
            return self.canvas_item.mouse_double_clicked(x, y, modifiers)
        return False

    def mouse_entered(self):
        return False

    def mouse_exited(self):
        return False

    def mouse_pressed(self, x, y, modifiers):
        if self.__mouse_inside(x, y):
            x -= self.__translation[0]
            y -= self.__translation[1]
            return self.canvas_item.mouse_pressed(x, y, modifiers)
        return False

    def mouse_released(self, x, y, modifiers):
        if self.__mouse_inside(x, y):
            x -= self.__translation[0]
            y -= self.__translation[1]
            return self.canvas_item.mouse_released(x, y, modifiers)
        return False

    def mouse_position_changed(self, x, y, modifiers):
        if self.__mouse_inside(x, y):
            x -= self.__translation[0]
            y -= self.__translation[1]
            return self.canvas_item.mouse_position_changed(x, y, modifiers)
        return False

    def key_pressed(self, key):
        return self.canvas_item.key_pressed(key)


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
            self.update_layout((0, 0), (width, height))
            self.update()
            self.repaint_if_needed()

    def __focus_changed(self, focused):
        if self.on_focus_changed:
            self.on_focus_changed(focused)

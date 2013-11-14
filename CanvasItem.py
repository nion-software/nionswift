# standard libraries
import logging
import threading

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


class CanvasItemLayout(object):

    def __init__(self):
        pass

    def layout(self, canvas_origin, canvas_size, canvas_items):
        for canvas_item in canvas_items:
            canvas_item.update_layout(canvas_origin, canvas_size)


class CanvasItemColumnLayout(object):

    def __init__(self):
        pass

    def layout(self, canvas_origin, canvas_size, canvas_items):
        canvas_item_origin = (16, 20)
        # prefer 200 pixels wide, but not more than 1/8 of the canvas size, but a minimum of 120 pixels wide
        canvas_item_width = max(min(320, int(canvas_size[1]/4)), 200)
        for canvas_item in canvas_items:
            canvas_item_height = int(canvas_item_width / canvas_item.preferred_aspect_ratio)
            canvas_item_size = (canvas_item_height, canvas_item_width)
            canvas_item.update_layout(canvas_item_origin, canvas_item_size)
            canvas_item_origin = (canvas_item_origin[0] + canvas_item_height + 12, canvas_item_origin[1])


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
            self.update_layout((0, 0), (height, width))
            self.update()
            self.repaint_if_needed()

    def __focus_changed(self, focused):
        if self.on_focus_changed:
            self.on_focus_changed(focused)

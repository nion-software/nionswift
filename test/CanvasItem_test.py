# standard libraries
import unittest

# third party libraries
# None

# local libraries
from nion.swift import CanvasItem
from nion.swift import Graphics
from nion.swift import Test


class TestCanvasItem(CanvasItem.AbstractCanvasItem):
    def __init__(self):
        super(TestCanvasItem, self).__init__()
        self._mouse_released = False
    def mouse_pressed(self, x, y, modifiers):
        return True
    def mouse_released(self, x, y, modifiers):
        self._mouse_released = True

class TestCanvasItemClass(unittest.TestCase):

    def setUp(self):
        pass

    def tearDown(self):
        pass

    def simulate_drag(self, canvas_item, p1, p2, modifiers=None):
        modifiers = Test.KeyboardModifiers() if not modifiers else modifiers
        canvas_item.mouse_pressed(p1[1], p1[0], modifiers)
        canvas_item.mouse_position_changed(p1[1], p1[0], modifiers)
        midp = Graphics.midpoint(p1, p2)
        canvas_item.mouse_position_changed(midp[1], midp[0], modifiers)
        canvas_item.mouse_position_changed(p2[1], p2[0], modifiers)
        canvas_item.mouse_released(p2[1], p2[0], modifiers)

    def test_drag_outside(self):
        # drag inside bounds
        canvas_item = TestCanvasItem()
        canvas_item.update_layout((0, 0), (100, 100))
        self.simulate_drag(canvas_item, (50, 50), (30, 50))
        self.assertTrue(canvas_item._mouse_released)
        # drag outside bounds
        canvas_item = TestCanvasItem()
        canvas_item.update_layout((0, 0), (100, 100))
        self.simulate_drag(canvas_item, (50, 50), (-30, 50))
        self.assertTrue(canvas_item._mouse_released)
        # drag within a composition
        canvas_item = TestCanvasItem()
        container = CanvasItem.CanvasItemComposition()
        container.add_canvas_item(canvas_item)
        container.update_layout((0, 0), (100, 100))
        self.simulate_drag(container, (50, 50), (30, 50))
        self.assertTrue(canvas_item._mouse_released)
        # drag within a composition, but outside bounds
        canvas_item = TestCanvasItem()
        container = CanvasItem.CanvasItemComposition()
        container.add_canvas_item(canvas_item)
        container.update_layout((0, 0), (100, 100))
        self.simulate_drag(container, (50, 50), (-30, 50))
        self.assertTrue(canvas_item._mouse_released)

if __name__ == '__main__':
    unittest.main()

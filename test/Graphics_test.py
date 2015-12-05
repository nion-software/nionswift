# futures
from __future__ import absolute_import
from __future__ import division

# standard libraries
import collections
import copy
import logging
import unittest

# third party libraries
import numpy

# local libraries
from nion.swift import Application
from nion.swift import DocumentController
from nion.swift.model import DataItem
from nion.swift.model import DocumentModel
from nion.swift.model import Graphics
from nion.swift.model import Region
from nion.ui import CanvasItem
from nion.ui import Geometry
from nion.ui import Test


class TestGraphicsClass(unittest.TestCase):

    def setUp(self):
        self.app = Application.Application(Test.UserInterface(), set_global=False)

    def tearDown(self):
        pass

    class Mapping(object):
        def __init__(self, size):
            self.size = size
        def map_point_image_norm_to_widget(self, p):
            return (p[0] * self.size[0], p[1] * self.size[1])
        def map_size_image_norm_to_widget(self, s):
            return (s[0] * self.size[0], s[1] * self.size[1])
        def map_point_widget_to_image_norm(self, p):
            return (s[0]/self.size[0], s[1]/self.size[1])

    def test_copy_graphic(self):
        rect_graphic = Graphics.RectangleGraphic()
        copy.deepcopy(rect_graphic)
        ellipse_graphic = Graphics.EllipseGraphic()
        copy.deepcopy(ellipse_graphic)
        line_graphic = Graphics.LineGraphic()
        copy.deepcopy(line_graphic)

    def test_rect_test(self):
        mapping = TestGraphicsClass.Mapping((1000, 1000))
        rect_graphic = Graphics.RectangleGraphic()
        rect_graphic.bounds = (0.25, 0.25), (0.5, 0.5)
        def get_font_metrics(font, text):
            FontMetrics = collections.namedtuple("FontMetrics", ["width", "height", "ascent", "descent", "leading"])
            return FontMetrics(width=(len(text) * 7.0), height=18, ascent=15, descent=3, leading=0)
        self.assertEqual(rect_graphic.test(mapping, get_font_metrics, (500, 500), move_only=False), ("all", False))
        self.assertEqual(rect_graphic.test(mapping, get_font_metrics, (250, 250), move_only=False)[0], "top-left")
        self.assertEqual(rect_graphic.test(mapping, get_font_metrics, (750, 750), move_only=False)[0], "bottom-right")
        self.assertEqual(rect_graphic.test(mapping, get_font_metrics, (250, 750), move_only=False)[0], "top-right")
        self.assertEqual(rect_graphic.test(mapping, get_font_metrics, (750, 250), move_only=False)[0], "bottom-left")
        self.assertEqual(rect_graphic.test(mapping, get_font_metrics, (250, 500), move_only=False), ("all", True))
        self.assertEqual(rect_graphic.test(mapping, get_font_metrics, (750, 500), move_only=False), ("all", True))
        self.assertEqual(rect_graphic.test(mapping, get_font_metrics, (500, 250), move_only=False), ("all", True))
        self.assertEqual(rect_graphic.test(mapping, get_font_metrics, (500, 750), move_only=False), ("all", True))
        self.assertIsNone(rect_graphic.test(mapping, get_font_metrics, (0, 0), move_only=False)[0])

    def test_line_test(self):
        mapping = TestGraphicsClass.Mapping((1000, 1000))
        line_graphic = Graphics.LineGraphic()
        line_graphic.start = (0.25,0.25)
        line_graphic.end = (0.75,0.75)
        def get_font_metrics(font, text):
            FontMetrics = collections.namedtuple("FontMetrics", ["width", "height", "ascent", "descent", "leading"])
            return FontMetrics(width=(len(text) * 7.0), height=18, ascent=15, descent=3, leading=0)
        self.assertEqual(line_graphic.test(mapping, get_font_metrics, (500, 500), move_only=True)[0], "all")
        self.assertEqual(line_graphic.test(mapping, get_font_metrics, (250, 250), move_only=True)[0], "start")
        self.assertEqual(line_graphic.test(mapping, get_font_metrics, (750, 750), move_only=True)[0], "end")
        self.assertEqual(line_graphic.test(mapping, get_font_metrics, (250, 250), move_only=False)[0], "start")
        self.assertEqual(line_graphic.test(mapping, get_font_metrics, (750, 750), move_only=False)[0], "end")
        self.assertIsNone(line_graphic.test(mapping, get_font_metrics, (240, 240), move_only=False)[0])
        self.assertIsNone(line_graphic.test(mapping, get_font_metrics, (760, 760), move_only=False)[0])
        self.assertIsNone(line_graphic.test(mapping, get_font_metrics, (0, 0), move_only=False)[0])

    def test_point_test(self):
        mapping = TestGraphicsClass.Mapping((1000, 1000))
        point_graphic = Graphics.PointGraphic()
        point_graphic.position = (0.25,0.25)
        def get_font_metrics(font, text):
            FontMetrics = collections.namedtuple("FontMetrics", ["width", "height", "ascent", "descent", "leading"])
            return FontMetrics(width=(len(text) * 7.0), height=18, ascent=15, descent=3, leading=0)
        self.assertEqual(point_graphic.test(mapping, get_font_metrics, (250, 250), move_only=True)[0], "all")
        self.assertEqual(point_graphic.test(mapping, get_font_metrics, (250 - 18, 250), move_only=True)[0], None)
        point_graphic.label = "Test"
        self.assertEqual(point_graphic.test(mapping, get_font_metrics, (250 - 18 - 6, 250), move_only=True)[0], "all")

    def assertAlmostEqualPoint(self, p1, p2, e=0.00001):
        if not(Geometry.distance(p1, p2) < e):
            logging.debug("%s != %s", p1, p2)
        self.assertTrue(Geometry.distance(p1, p2) < e)

    def assertAlmostEqualSize(self, s1, s2, e=0.00001):
        if not(abs(s2.height - s1.height) < e) or not(abs(s2.width - s1.width) < e):
            logging.debug("%s != %s", s1, s2)
        self.assertTrue(abs(s2.height - s1.height) < e and abs(s2.width - s1.width) < e)

    def assertAlmostEqualRect(self, r1, r2, e=0.00001):
        if not(Geometry.distance(r1[0], r2[0]) < e and Geometry.distance(r1[1], r2[1]) < e):
            logging.debug("%s != %s", r1, r2)
        self.assertTrue(Geometry.distance(r1[0], r2[0]) < e and Geometry.distance(r1[1], r2[1]) < e)

    def test_dragging_regions(self):
        # make the document controller
        document_model = DocumentModel.DocumentModel()
        document_controller = DocumentController.DocumentController(self.app.ui, document_model, workspace_id="library")
        display_panel = document_controller.selected_display_panel
        data_item = DataItem.DataItem(numpy.zeros((10, 10)))
        document_model.append_data_item(data_item)
        display_panel.set_displayed_data_item(data_item)
        header_height = display_panel._content_for_test.header_canvas_item.header_height
        display_panel.canvas_item.root_container.canvas_widget.on_size_changed(1000, 1000 + header_height)
        display_specifier = DataItem.DisplaySpecifier.from_data_item(data_item)

        def get_extended_attr(object, extended_name):
            initial_value = object
            for sub_property in extended_name.split("."):
                initial_value = getattr(initial_value, sub_property)
            return initial_value

        def map_string(s, m1, m2):
            for k, v in m1.items():
                s = s.replace(k, v)
            for k, v in m2.items():
                s = s.replace(k, v)
            return s

        class ScalarCoordinate(object):

            def __init__(self, v_value=None, h_value=None):
                self.v_value = v_value
                self.h_value = h_value

            @property
            def value(self):
                return self.v_value if self.v_value is not None else self.h_value

        def reflect_rect(r, v, h):
            if v and not h:
                return Geometry.FloatRect(Geometry.FloatPoint(1.0 - r.bottom, r.left), r.size)
            elif v and h:
                return Geometry.FloatRect(Geometry.FloatPoint(1.0 - r.bottom, 1.0 - r.right), r.size)
            elif not v and h:
                return Geometry.FloatRect(Geometry.FloatPoint(r.top, 1.0 - r.right), r.size)
            else:
                return r

        def reflect_point(p, v, h):
            y = 1.0 - p.y if v else p.y
            x = 1.0 - p.x if h else p.x
            return Geometry.FloatPoint(y, x)

        def reflect_size(s, v, h):
            height = 1.0 - s.height if v else s.height
            width = 1.0 - s.width if h else s.width
            return Geometry.FloatSize(height, width)

        def reflect_scalar(s, v, h):
            v_value = 1.0 - s.v_value if s.v_value is not None and v else s.v_value
            h_value = 1.0 - s.h_value if s.h_value is not None and h else s.h_value
            return ScalarCoordinate(v_value, h_value)

        def reflect_value(value, v, h, mapping_v1, mapping_v2, mapping_h1, mapping_h2):
            if isinstance(value, Geometry.FloatRect):
                return reflect_rect(value, v, h)
            elif isinstance(value, Geometry.FloatPoint):
                return reflect_point(value, v, h)
            elif isinstance(value, Geometry.FloatSize):
                return reflect_size(value, v, h)
            elif isinstance(value, ScalarCoordinate):
                return reflect_scalar(value, v, h)
            elif isinstance(value, str):
                if v:
                    value = map_string(value, mapping_v1, mapping_v2)
                if h:
                    value = map_string(value, mapping_h1, mapping_h2)
                return value
            raise Exception("Unknown value type %s", type(value))
            return None

        def reflect(d, v, h):
            mapping_v1 = {"top": "was_top", "bottom": "was_bottom"}
            mapping_v2 = {"was_top": "bottom", "was_bottom": "top"}
            mapping_h1 = {"left": "was_left", "right": "was_right"}
            mapping_h2 = {"was_left": "right", "was_right": "left"}
            # name
            if v:
                d["name"] = map_string(d["name"], mapping_v1, mapping_v2)
            if h:
                d["name"] = map_string(d["name"], mapping_h1, mapping_h2)
            # input
            old_input = d["input"]["properties"]
            new_input = dict()
            for property, expected_value in old_input.items():
                if v:
                    property = map_string(property, mapping_v1, mapping_v2)
                if h:
                    property = map_string(property, mapping_h1, mapping_h2)
                new_input[property] = reflect_value(expected_value, v, h, mapping_v1, mapping_v2, mapping_h1, mapping_h2)
            d["input"]["properties"] = new_input
            # drag
            drag = d["drag"]
            c0, c1 = drag[0:2]
            if v:
                c0 = 1000 - c0[0], c0[1]
                c1 = 1000 - c1[0], c1[1]
            if h:
                c0 = c0[0], 1000 - c0[1]
                c1 = c1[0], 1000 - c1[1]
            new_drag = list((c0, c1))
            new_drag.extend(drag[2:])
            d["drag"] = tuple(new_drag)
            # output
            old_output = d["output"]["properties"]
            new_output = dict()
            for property, expected_value in old_output.items():
                if v:
                    property = map_string(property, mapping_v1, mapping_v2)
                if h:
                    property = map_string(property, mapping_h1, mapping_h2)
                new_output[property] = reflect_value(expected_value, v, h, mapping_v1, mapping_v2, mapping_h1, mapping_h2)
            d["output"]["properties"] = new_output
            return d

        def do_drag_test(d):
            # logging.debug("test %s", d["name"])
            region = Region.region_factory(lambda t: d["input"]["type"])
            for property, initial_value in d["input"]["properties"].items():
                setattr(region, property, initial_value)
            initial_values = dict()
            for property, expected_value in d["output"]["properties"].items():
                if isinstance(expected_value, str):
                    initial_values[expected_value] = get_extended_attr(region, expected_value)
            for constraint in d["input"].get("constraints", list()):
                if constraint == "bounds":
                    region.is_bounds_constrained = True
                elif constraint == "shape":
                    region.is_shape_locked = True
                elif constraint == "position":
                    region.is_position_locked = True
            display_specifier.buffered_data_source.add_region(region)
            display_specifier.display.graphic_selection.set(0)
            display_panel.display_canvas_item.simulate_drag(*d["drag"])
            for property, expected_value in d["output"]["properties"].items():
                actual_value = get_extended_attr(region, property)
                # logging.debug("%s: %s == %s ?", property, actual_value, expected_value)
                if isinstance(expected_value, str):
                    if isinstance(actual_value, Geometry.FloatRect):
                        self.assertAlmostEqualRect(actual_value, initial_values[expected_value])
                    elif isinstance(actual_value, Geometry.FloatPoint):
                        self.assertAlmostEqualPoint(actual_value, initial_values[expected_value])
                    elif isinstance(actual_value, Geometry.FloatSize):
                        self.assertAlmostEqualSize(actual_value, initial_values[expected_value])
                    elif isinstance(actual_value, ScalarCoordinate):
                        self.assertAlmostEqual(actual_value.value, initial_values[expected_value])
                    else:
                        raise Exception("Unknown value type %s", type(actual_value))
                else:
                    if isinstance(actual_value, Geometry.FloatRect):
                        self.assertAlmostEqualRect(actual_value, expected_value)
                    elif isinstance(actual_value, Geometry.FloatPoint):
                        self.assertAlmostEqualPoint(actual_value, expected_value)
                    elif isinstance(actual_value, Geometry.FloatSize):
                        self.assertAlmostEqualSize(actual_value, expected_value)
                    elif isinstance(actual_value, float):
                        self.assertAlmostEqual(actual_value, expected_value.value)
                    else:
                        raise Exception("Unknown value type %s", type(actual_value))
            display_specifier.buffered_data_source.remove_region(region)
            region.is_bounds_constrained = False

        # rectangle top-left

        d = {
            "name": "drag top-left corner outside of bounds with no constraints",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect(origin=(0.21, 0.22), size=(0.31, 0.32)) }
            },
            "drag": [(210, 220), (-190, -180)],
            "output": {
                "properties": {
                    "_bounds.top_left": Geometry.FloatPoint(y=-0.19, x=-0.18),
                    "_bounds.bottom_right": "_bounds.bottom_right"
                },
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag top-left corner outside of bounds with bounds constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.21, 0.22), (0.31, 0.32)) },
                "constraints": ["bounds"]
            },
            "drag": [(210, 220), (-190, -180)],
            "output": {
                "properties": {
                    "_bounds.top_left": Geometry.FloatPoint(),
                    "_bounds.bottom_right": "_bounds.bottom_right"
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag top-left corner from center towards top left with bounds constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.25, 0.25), (0.5, 0.5)) },
                "constraints": ["bounds"]
            },
            "drag": [(250, 250), (150, 140), CanvasItem.KeyboardModifiers(alt=True)],
            "output": {
                "properties": {
                    "_bounds.center": "_bounds.center",
                    "_bounds.top_left": Geometry.FloatPoint(0.15, 0.14),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag top-left corner from center towards top left with position constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.25, 0.25), (0.5, 0.5)) },
                "constraints": ["position"]
            },
            "drag": [(250, 250), (150, 140), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_bounds.center": "_bounds.center",
                    "_bounds.top_left": Geometry.FloatPoint(0.15, 0.14),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag top-left corner from center outside of bounds to the top left with bounds constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.21, 0.22), (0.31, 0.32)) },
                "constraints": ["bounds"]
            },
            "drag": [(210, 220), (-190, -180), CanvasItem.KeyboardModifiers(alt=True)],
            "output": {
                "properties": {
                    "_bounds.center": "_bounds.center",
                    "_bounds.top_left": Geometry.FloatPoint(),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag top-left corner from center outside of bounds to the bottom with bounds constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.21, 0.22), (0.31, 0.32)) },
                "constraints": ["bounds"]
            },
            "drag": [(210, 220), (1500, 220), CanvasItem.KeyboardModifiers(alt=True)],
            "output": {
                "properties": {
                    "_bounds.center": "_bounds.center",
                    "_bounds.top": ScalarCoordinate(v_value=0.0),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag top-left corner from center outside of bounds to the right with bounds constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.21, 0.22), (0.31, 0.32)) },
                "constraints": ["bounds"]
            },
            "drag": [(210, 220), (210, 1500), CanvasItem.KeyboardModifiers(alt=True)],
            "output": {
                "properties": {
                    "_bounds.center": "_bounds.center",
                    "_bounds.left": ScalarCoordinate(h_value=0.0),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag squared top-left corner from outside of bounds to the bottom right with bounds constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.2, 0.3), (0.4, 0.5)) },
                "constraints": ["bounds"]
            },
            "drag": [(200, 300), (1500, 1500), CanvasItem.KeyboardModifiers(shift=True)],
            "output": {
                "properties": {
                    "_bounds.top_left": "_bounds.bottom_right",
                    "_bounds.bottom": ScalarCoordinate(v_value=0.8),
                    "_bounds.right": ScalarCoordinate(h_value=1.0),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag squared top-left corner from in one direction",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.4, 0.4), (0.2, 0.2)) },  # center 0.5, 0.5
                "constraints": ["bounds"]
            },
            "drag": [(400, 400), (200, 400), CanvasItem.KeyboardModifiers(shift=True)],
            "output": {
                "properties": {
                    "_bounds.bottom_right": "_bounds.bottom_right",
                    "_bounds.top_left": Geometry.FloatPoint(0.2, 0.2),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag squared top-left corner from outside of bounds to the bottom right with bounds constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.1, 0.3), (0.2, 0.2)) },  # center 0.2, 0.4
                "constraints": ["bounds"]
            },
            "drag": [(100, 300), (-200, -200), CanvasItem.KeyboardModifiers(shift=True, alt=True)],
            "output": {
                "properties": {
                    "_bounds.center": "_bounds.center",
                    "_bounds.left": ScalarCoordinate(h_value=0.2),
                    "_bounds.top": ScalarCoordinate(v_value=0.0),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag squared top-left corner with bounds, center, square constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.4, 0.4), (0.2, 0.2)) },  # center 0.5, 0.5
                "constraints": ["bounds"]
            },
            "drag": [(400, 400), (300, 200), CanvasItem.KeyboardModifiers(shift=True, alt=True)],
            "output": {
                "properties": {
                    "_bounds.center": "_bounds.center",
                    "_bounds.top_left": Geometry.FloatPoint(0.3, 0.3),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag squared top-left corner with bounds, center, square constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.7, 0.7), (0.2, 0.2)) },  # center 0.8, 0.8
                "constraints": ["bounds"]
            },
            "drag": [(700, 700), (0, 0), CanvasItem.KeyboardModifiers(shift=True, alt=True)],
            "output": {
                "properties": {
                    "_bounds.center": "_bounds.center",
                    "_bounds.right": ScalarCoordinate(h_value=1.0),
                    "_bounds.bottom": ScalarCoordinate(v_value=1.0),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag top-left to top-left with shape constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.3, 0.2), (0.2, 0.2)) },  # center 0.4, 0.3
                "constraints": ["shape"]
            },
            "drag": [(300, 200), (-100, -100), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_bounds.center": Geometry.FloatPoint(),
                    "_bounds.size": "_bounds.size",
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag all to top-left with no constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.3, 0.2), (0.2, 0.2)) },  # center 0.4, 0.3
            },
            "drag": [(400, 300), (0, 0), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_bounds.center": Geometry.FloatPoint(),
                    "_bounds.size": "_bounds.size",
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag all top-left with bounds constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.3, 0.2), (0.2, 0.2)) },  # center 0.4, 0.3
                "constraints": ["bounds"]
            },
            "drag": [(400, 300), (0, 0), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_bounds.center": Geometry.FloatPoint(0.1, 0.1),
                    "_bounds.size": "_bounds.size",
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag all bottom-right with bounds constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.3, 0.2), (0.2, 0.2)) },  # center 0.4, 0.3
                "constraints": ["bounds"]
            },
            "drag": [(400, 300), (1000, 1000), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_bounds.center": Geometry.FloatPoint(0.9, 0.9),
                    "_bounds.size": "_bounds.size",
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "drag all with restrict constraint",
            "input": {
                "type": "rectangle-region",
                "properties": { "_bounds": Geometry.FloatRect((0.4, 0.4), (0.2, 0.2)) },  # center 0.5, 0.5
            },
            "drag": [(500, 500), (800, 600), CanvasItem.KeyboardModifiers(shift=True)],
            "output": {
                "properties": {
                    "_bounds.center": Geometry.FloatPoint(0.8, 0.5),
                    "_bounds.size": "_bounds.size",
                }
            }
        }

        # vertical reflections not valid
        for h in (False, True):
            do_drag_test(reflect(d, False, h))

        # point

        d = {
            "name": "point drag with no constraint",
            "input": {
                "type": "point-region",
                "properties": { "_position": Geometry.FloatPoint(0.2, 0.3) },
                # "constraints": ["bounds"]
            },
            "drag": [(200, 300), (-100, -100), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_position": Geometry.FloatPoint(-0.1, -0.1),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "point drag with bounds constraint",
            "input": {
                "type": "point-region",
                "properties": { "_position": Geometry.FloatPoint(0.2, 0.3) },
                "constraints": ["bounds"]
            },
            "drag": [(200, 300), (-100, -100), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_position": Geometry.FloatPoint(),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "point drag with restrict",
            "input": {
                "type": "point-region",
                "properties": { "_position": Geometry.FloatPoint(0.2, 0.3) },
                "constraints": ["bounds"]
            },
            "drag": [(200, 300), (100, 100), CanvasItem.KeyboardModifiers(shift=True)],
            "output": {
                "properties": {
                    "_position": Geometry.FloatPoint(0.2, 0.1),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        # line regions

        d = {
            "name": "line drag with no constraints",
            "input": {
                "type": "line-region",
                "properties": {
                    "_start": Geometry.FloatPoint(0.2, 0.3),
                    "_end": Geometry.FloatPoint(0.6, 0.5),
                },
                # "constraints": ["bounds"]
            },
            "drag": [(400, 400), (600, 700), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_start": Geometry.FloatPoint(0.4, 0.6),
                    "_end": Geometry.FloatPoint(0.8, 0.8),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "line start drag with restrict",
            "input": {
                "type": "line-region",
                "properties": {
                    "_start": Geometry.FloatPoint(0.2, 0.3),
                    "_end": Geometry.FloatPoint(0.6, 0.5),
                },
                "constraints": ["shape"]
            },
            "drag": [(200, 300), (400, 600), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_start": Geometry.FloatPoint(0.4, 0.6),
                    "_end": Geometry.FloatPoint(0.8, 0.8),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "line drag with bounds constraint",
            "input": {
                "type": "line-region",
                "properties": {
                    "_start": Geometry.FloatPoint(0.2, 0.3),
                    "_end": Geometry.FloatPoint(0.6, 0.5),
                },
                "constraints": ["bounds"]
            },
            "drag": [(400, 400), (1000, 1000), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_start": Geometry.FloatPoint(0.6, 0.8),
                    "_end": Geometry.FloatPoint(1.0, 1.0),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "line start drag with no constraints",
            "input": {
                "type": "line-region",
                "properties": {
                    "_start": Geometry.FloatPoint(0.2, 0.3),
                    "_end": Geometry.FloatPoint(0.6, 0.5),
                },
                # "constraints": ["bounds"]
            },
            "drag": [(200, 300), (600, 700), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_start": Geometry.FloatPoint(0.6, 0.7),
                    "_end": Geometry.FloatPoint(0.6, 0.5),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "line start drag with bounds constraint",
            "input": {
                "type": "line-region",
                "properties": {
                    "_start": Geometry.FloatPoint(0.2, 0.3),
                    "_end": Geometry.FloatPoint(0.6, 0.5),
                },
                "constraints": ["bounds"]
            },
            "drag": [(200, 300), (-100, 300), CanvasItem.KeyboardModifiers()],
            "output": {
                "properties": {
                    "_start": Geometry.FloatPoint(0.0, 0.3),
                    "_end": Geometry.FloatPoint(0.6, 0.5),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        d = {
            "name": "line start drag with shape constraint",
            "input": {
                "type": "line-region",
                "properties": {
                    "_start": Geometry.FloatPoint(0.2, 0.3),
                    "_end": Geometry.FloatPoint(0.6, 0.5),
                },
                "constraints": ["bounds"]
            },
            "drag": [(200, 300), (500, 500), CanvasItem.KeyboardModifiers(shift=True)],
            "output": {
                "properties": {
                    "_start": Geometry.FloatPoint(0.5, 0.5),
                    "_end": Geometry.FloatPoint(0.6, 0.5),
                }
            }
        }

        for v in (False, True):
            for h in (False, True):
                do_drag_test(reflect(d, v, h))

        document_controller.close()

if __name__ == '__main__':
    logging.getLogger().setLevel(logging.DEBUG)
    unittest.main()

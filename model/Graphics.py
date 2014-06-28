# standard libraries
import copy
import gettext
import logging
import math

# third party libraries
import numpy  # for arange

# local libraries
from nion.ui import Observable


_ = gettext.gettext


def adjust_rectangle_like(mapping, original, current, part, modifiers):
    # NOTE: all sizes/points are assumed to be in image coordinates
    o = mapping.map_point_widget_to_image(original)
    p = mapping.map_point_widget_to_image(current)
    old_origin = mapping.map_point_image_norm_to_image(part[1][0])
    old_size = mapping.map_point_image_norm_to_image(part[1][1])
    old_center = (old_origin[0] + 0.5*old_size[0], old_origin[1] + 0.5*old_size[1])
    delta = (p[0] - o[0], p[1] - o[1])
    new_bounds = (old_origin, old_size)
    if part[0] == "top-left":  # top left
        if modifiers.alt:
            new_top_left = (old_origin[0] + delta[0], old_origin[1] + delta[1])
            if modifiers.shift:  # hold bottom left constant
                half_size = (old_center[0] - new_top_left[0], old_center[1] - new_top_left[1])
                if half_size[0] > half_size[1]:  # size will be width
                    new_top_left = (old_center[0] + half_size[1], new_top_left[1])
                else:  # size will be height
                    new_top_left = (new_top_left[0], old_center[1] + half_size[0])
            new_bottom_right = (2*old_center[0] - new_top_left[0], 2*old_center[1] - new_top_left[1])
            new_bounds = (new_top_left, (new_bottom_right[0] - new_top_left[0], new_bottom_right[1] - new_top_left[1]))
        else:
            new_bounds = ((old_origin[0] + delta[0], old_origin[1] + delta[1]), (old_size[0] - delta[0], old_size[1] - delta[1]))
            if modifiers.shift:  # hold bottom right constant
                if new_bounds[1][0] > new_bounds[1][1]:  # size will be width
                    new_bounds = ((new_bounds[0][0] + new_bounds[1][0] - new_bounds[1][1], new_bounds[0][1]), (new_bounds[1][1], new_bounds[1][1]))
                else:  # size will be height
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1] + new_bounds[1][1] - new_bounds[1][0]), (new_bounds[1][0], new_bounds[1][0]))
    elif part[0] == "top-right":  # top right
        if modifiers.alt:
            new_top_right = (old_origin[0] + delta[0], old_origin[1] + old_size[1] + delta[1])
            if modifiers.shift:  # hold bottom left constant
                half_size = (old_center[0] - new_top_right[0], old_center[1] - new_top_right[1])
                if half_size[0] > half_size[1]:  # size will be width
                    new_top_right = (old_center[0] + half_size[1], new_top_right[1])
                else:  # size will be height
                    new_top_right = (new_top_right[0], old_center[1] + half_size[0])
            new_bottom_left = (2*old_center[0] - new_top_right[0], 2*old_center[1] - new_top_right[1])
            new_bounds = ((new_top_right[0], new_bottom_left[1]), (new_bottom_left[0] - new_top_right[0], new_top_right[1] - new_bottom_left[1]))
        else:
            new_bounds = ((old_origin[0] + delta[0], old_origin[1]), (old_size[0] - delta[0], old_size[1] + delta[1]))
            if modifiers.shift:  # hold bottom left constant
                if new_bounds[1][0] > new_bounds[1][1]:  # size will be width
                    new_bounds = ((new_bounds[0][0] + new_bounds[1][0] - new_bounds[1][1], new_bounds[0][1]), (new_bounds[1][1], new_bounds[1][1]))
                else:  # size will be height
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1]), (new_bounds[1][0], new_bounds[1][0]))
    elif part[0] == "bottom-right":  # bottom right
        if modifiers.alt:
            new_bottom_right = (old_origin[0] + old_size[0] + delta[0], old_origin[1] + old_size[1] + delta[1])
            if modifiers.shift:  # hold bottom left constant
                half_size = (old_center[0] - new_bottom_right[0], old_center[1] - new_bottom_right[1])
                if half_size[0] > half_size[1]:  # size will be width
                    new_bottom_right = (old_center[0] + half_size[1], new_bottom_right[1])
                else:  # size will be height
                    new_bottom_right = (new_bottom_right[0], old_center[1] + half_size[0])
            new_top_left = (2*old_center[0] - new_bottom_right[0], 2*old_center[1] - new_bottom_right[1])
            new_bounds = (new_top_left, (new_bottom_right[0] - new_top_left[0], new_bottom_right[1] - new_top_left[1]))
        else:
            new_bounds = ((old_origin[0], old_origin[1]), (old_size[0] + delta[0], old_size[1] + delta[1]))
            if modifiers.shift:  # hold bottom left constant
                if new_bounds[1][0] > new_bounds[1][1]:  # size will be width
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1]), (new_bounds[1][1], new_bounds[1][1]))
                else:  # size will be height
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1]), (new_bounds[1][0], new_bounds[1][0]))
    elif part[0] == "bottom-left":  # bottom left
        if modifiers.alt:
            new_bottom_left = (old_origin[0] + old_size[0] + delta[0], old_origin[1] + delta[1])
            if modifiers.shift:  # hold bottom left constant
                half_size = (old_center[0] - new_bottom_left[0], old_center[1] - new_bottom_left[1])
                if half_size[0] > half_size[1]:  # size will be width
                    new_bottom_left = (old_center[0] + half_size[1], new_bottom_left[1])
                else:  # size will be height
                    new_bottom_left = (new_bottom_left[0], old_center[1] + half_size[0])
            new_top_right = (2*old_center[0] - new_bottom_left[0], 2*old_center[1] - new_bottom_left[1])
            new_bounds = ((new_top_right[0], new_bottom_left[1]), (new_bottom_left[0] - new_top_right[0], new_top_right[1] - new_bottom_left[1]))
        else:
            new_bounds = ((old_origin[0], old_origin[1] + delta[1]), (old_size[0] + delta[0], old_size[1] - delta[1]))
            if modifiers.shift:  # hold bottom left constant
                if new_bounds[1][0] > new_bounds[1][1]:  # size will be width
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1]), (new_bounds[1][1], new_bounds[1][1]))
                else:  # size will be height
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1] + new_bounds[1][1] - new_bounds[1][0]), (new_bounds[1][0], new_bounds[1][0]))
    elif part[0] == "all":
        new_bounds = ((old_origin[0] + delta[0], old_origin[1] + delta[1]), old_size)
    return (mapping.map_point_image_to_image_norm(new_bounds[0]), mapping.map_size_image_to_image_norm(new_bounds[1]))


class NullModifiers(object):
    def __init__(self):
        self.shift = False
        self.only_shift = False
        self.control = False
        self.only_control = False
        self.alt = False
        self.only_alt = False
        self.option = False
        self.only_option = False
        self.meta = False
        self.only_meta = False
        self.keypad = False
        self.only_keypad = False


# A Graphic object describes visible content, such as a shape, bitmap, video, or a line of text.
class Graphic(Observable.Observable, Observable.Broadcaster, Observable.ActiveSerializable):
    def __init__(self, type):
        super(Graphic, self).__init__()
        self.define_type(type)
        self.define_property(Observable.Property("color", "#F00", changed=self._property_changed))
    # subclasses should override __deepcopy__ and deepcopy_from as necessary
    def __deepcopy__(self, memo):
        graphic = self.__class__()
        graphic.deepcopy_from(self, memo)
        memo[id(self)] = graphic
        return graphic
    def _property_changed(self, name, value):
        self.notify_set_property(name, value)
    # test whether points are close
    def test_point(self, p1, p2, radius):
        return math.sqrt(pow(p1[0]-p2[0], 2)+pow(p1[1]-p2[1], 2)) < radius
    # closest point on line
    def get_closest_point_on_line(self, start, end, p):
        c = (p[0] - start[0], p[1] - start[1])
        v = (end[0] - start[0], end[1] - start[1])
        length = math.sqrt(pow(v[0],2) + pow(v[1],2))
        v = (v[0] / length, v[1] / length)
        t = v[0] * c[0] + v[1] * c[1]
        if t < 0:
            return start
        if t > length:
            return end
        return (start[0] + v[0] * t, start[1] + v[1] * t)
    # test whether point is close to line
    def test_line(self, start, end, p, radius):
        cp = self.get_closest_point_on_line(start, end, p)
        return math.sqrt(pow(p[0] - cp[0], 2) + pow(p[1] - cp[1], 2)) < radius
    def test_inside_bounds(self, bounds, p, radius):
        return p[0] > bounds[0][0] and p[0] <= bounds[0][0] + bounds[1][0] and p[1] > bounds[0][1] and p[1] <= bounds[0][1] + bounds[1][1]
    def draw_ellipse(self, ctx, cx, cy, rx, ry):
        ctx.save()
        ra = 0.0  # rotation angle
        ctx.begin_path()
        for i in numpy.arange(0, 2*math.pi, 0.1):
            x = cx - (ry * 0.5 * math.sin(i)) * math.sin(ra * math.pi) + (rx * 0.5 * math.cos(i)) * math.cos(ra * math.pi)
            y = cy + (rx * 0.5 * math.cos(i)) * math.sin(ra * math.pi) + (ry * 0.5 * math.sin(i)) * math.cos(ra * math.pi)
            if i == 0:
                ctx.move_to(x, y)
            else:
                ctx.line_to(x, y)
        ctx.close_path()
        ctx.stroke()
        ctx.restore()
    def draw_marker(self, ctx, p):
        ctx.save()
        ctx.fill_style = '#00FF00'
        ctx.begin_path()
        ctx.move_to(p[1] - 3, p[0] - 3)
        ctx.line_to(p[1] + 3, p[0] - 3)
        ctx.line_to(p[1] + 3, p[0] + 3)
        ctx.line_to(p[1] - 3, p[0] + 3)
        ctx.close_path()
        ctx.fill()
        ctx.restore()
    def notify_set_property(self, key, value):
        super(Graphic, self).notify_set_property(key, value)
        self.notify_listeners("graphic_changed", self)
    def nudge(self, mapping, delta):
        raise NotImplementedError()
    def notify_remove_region_graphic(self):
        self.notify_listeners("remove_region_graphic", self)


class RectangleTypeGraphic(Graphic):
    def __init__(self, type, title):
        super(RectangleTypeGraphic, self).__init__(type)
        self.title = title
        self.define_property(Observable.Property("bounds", ((0.0, 0.0), (1.0, 1.0)), validate=self.__validate_bounds, changed=self.__bounds_changed))
    # accessors
    def __validate_bounds(self, value):
        # normalize
        if value[1][0] < 0:  # height is negative
            value = ((value[0][0] + value[1][0], value[0][1]), (-value[1][0], value[1][1]))
        if value[1][1] < 0:  # width is negative
            value = ((value[0][0], value[0][1] + value[1][1]), (value[1][0], -value[1][1]))
        return copy.deepcopy(value)
    def __bounds_changed(self, name, value):
        self._property_changed(name, value)
        self._property_changed("center", self.center)
        self._property_changed("size", self.size)
    # dependent property center
    def __get_center(self):
        return (self.bounds[0][0] + self.size[0] * 0.5, self.bounds[0][1] + self.size[1] * 0.5)
    def __set_center(self, center):
        self.bounds = ((center[0] - self.size[0] * 0.5, center[1] - self.size[1] * 0.5), self.size)
    center = property(__get_center, __set_center)
    # dependent property size
    def __get_size(self):
        return self.bounds[1]
    def __set_size(self, size):
        # keep center the same
        old_origin = self.bounds[0]
        old_size = self.bounds[1]
        origin = old_origin[0] - (size[0] - old_size[0]) * 0.5, old_origin[1] - (size[1] - old_size[1]) * 0.5
        self.bounds = (origin, size)
    size = property(__get_size, __set_size)
    # test point hit
    def test(self, mapping, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        # top left
        if not move_only and self.test_point(origin, test_point, 4):
            return "top-left"
        # top right
        if not move_only and self.test_point((origin[0], origin[1] + size[1]), test_point, 4):
            return "top-right"
        # bottom right
        if not move_only and self.test_point((origin[0] + size[0], origin[1] + size[1]), test_point, 4):
            return "bottom-right"
        # bottom left
        if not move_only and self.test_point((origin[0] + size[0], origin[1]), test_point, 4):
            return "bottom-left"
        # center
        if self.test_inside_bounds((origin, size), test_point, 4):
            return "all"
        # didn't find anything
        return None
    def begin_drag(self):
        return (self.bounds, )
    def end_drag(self, part_data):
        pass
    # rectangle
    def adjust_part(self, mapping, original, current, part, modifiers):
        self.bounds = adjust_rectangle_like(mapping, original, current, part, modifiers)
    def nudge(self, mapping, delta):
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        original = (origin[0] + size[0] * 0.5, origin[1] + size[1] * 0.5)
        current = (original[0] + delta[0], original[1] + delta[1])
        self.adjust_part(mapping, original, current, ("all", ) + self.begin_drag(), NullModifiers())
    def draw(self, ctx, mapping, is_selected=False):
        raise NotImplementedError()


class RectangleGraphic(RectangleTypeGraphic):
    def __init__(self):
        super(RectangleGraphic, self).__init__("rect-graphic", _("Rectangle"))
    def draw(self, ctx, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        ctx.save()
        ctx.begin_path()
        ctx.move_to(origin[1], origin[0])
        ctx.line_to(origin[1] + size[1], origin[0])
        ctx.line_to(origin[1] + size[1], origin[0] + size[0])
        ctx.line_to(origin[1], origin[0] + size[0])
        ctx.close_path()
        ctx.line_width = 1
        ctx.stroke_style = self.color
        ctx.stroke()
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, origin)
            self.draw_marker(ctx, (origin[0] + size[0], origin[1]))
            self.draw_marker(ctx, (origin[0] + size[0], origin[1] + size[1]))
            self.draw_marker(ctx, (origin[0], origin[1] + size[1]))
            # draw center marker
            mark_size = 8
            if size[0] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.begin_path()
                ctx.move_to(mid_x - 0.5*mark_size, mid_y)
                ctx.line_to(mid_x + 0.5*mark_size, mid_y)
                ctx.stroke_style = self.color
                ctx.stroke()
                ctx.restore()
            if size[1] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.begin_path()
                ctx.move_to(mid_x, mid_y - 0.5*mark_size)
                ctx.line_to(mid_x, mid_y + 0.5*mark_size)
                ctx.stroke_style = self.color
                ctx.stroke()
                ctx.restore()


class EllipseGraphic(RectangleTypeGraphic):
    def __init__(self):
        super(EllipseGraphic, self).__init__("ellipse-graphic", _("Ellipse"))
    def draw(self, ctx, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_image_norm_to_widget(self.bounds[0])
        size = mapping.map_size_image_norm_to_widget(self.bounds[1])
        ctx.save()
        ctx.line_width = 1
        ctx.stroke_style = self.color
        self.draw_ellipse(ctx, origin[1] + size[1]*0.5, origin[0] + size[0]*0.5, size[1], size[0])
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, origin)
            self.draw_marker(ctx, (origin[0] + size[0], origin[1]))
            self.draw_marker(ctx, (origin[0] + size[0], origin[1] + size[1]))
            self.draw_marker(ctx, (origin[0], origin[1] + size[1]))
            # draw center marker
            mark_size = 8
            if size[0] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.begin_path()
                ctx.move_to(mid_x - 0.5*mark_size, mid_y)
                ctx.line_to(mid_x + 0.5*mark_size, mid_y)
                ctx.stroke_style = self.color
                ctx.stroke()
                ctx.restore()
            if size[1] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.begin_path()
                ctx.move_to(mid_x, mid_y - 0.5*mark_size)
                ctx.line_to(mid_x, mid_y + 0.5*mark_size)
                ctx.stroke_style = self.color
                ctx.stroke()
                ctx.restore()


class LineTypeGraphic(Graphic):
    def __init__(self, type, title):
        super(LineTypeGraphic, self).__init__(type)
        self.title = title
        # start and end points are stored in image normalized coordinates
        self.define_property(Observable.Property("start", (0.0, 0.0), changed=self._property_changed))
        self.define_property(Observable.Property("end", (1.0, 1.0), changed=self._property_changed))
        self.define_property(Observable.Property("start_arrow_enabled", False, changed=self._property_changed))
        self.define_property(Observable.Property("end_arrow_enabled", False, changed=self._property_changed))
    # accessors
    def __get_vector(self):
        return self.start, self.end
    def __set_vector(self, vector):
        self.start = vector[0]
        self.end = vector[1]
    vector = property(__get_vector, __set_vector)
    # test is required for Graphic interface
    def test(self, mapping, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        # start point
        if not move_only and self.test_point(p1, test_point, 4):
            return "start"
        # end point
        if not move_only and self.test_point(p2, test_point, 4):
            return "end"
        # along the line
        if self.test_line(p1, p2, test_point, 4):
            return "all"
        # didn't find anything
        return None
    def begin_drag(self):
        return (self.start, self.end)
    def end_drag(self, part_data):
        pass
    def adjust_part(self, mapping, original, current, part, modifiers):
        o_image = mapping.map_point_widget_to_image(original)
        p_image = mapping.map_point_widget_to_image(current)
        end_image = mapping.map_point_image_norm_to_image(self.end)
        start_image = mapping.map_point_image_norm_to_image(self.start)
        if part[0] == "start":
            dy = p_image[0] - end_image[0]
            dx = p_image[1] - end_image[1]
            if modifiers.shift:
                angle_degrees = math.degrees(math.atan2(abs(dy), abs(dx)))
                if angle_degrees > 60:
                    p_image = (p_image[0], end_image[1])
                elif angle_degrees > 30:
                    if angle_degrees > 45:
                        if dx * dy > 0:
                            p_image = (p_image[0], end_image[1] + dy)
                        else:
                            p_image = (p_image[0], end_image[1] - dy)
                    else:
                        if dx * dy > 0:
                            p_image = (end_image[0] + dx, p_image[1])
                        else:
                            p_image = (end_image[0] - dx, p_image[1])
                else:
                    p_image = (end_image[0], p_image[1])
            self.start = mapping.map_point_image_to_image_norm(p_image)
        elif part[0] == "end":
            dy = p_image[0] - start_image[0]
            dx = p_image[1] - start_image[1]
            if modifiers.shift:
                angle_degrees = math.degrees(math.atan2(abs(dy), abs(dx)))
                if angle_degrees > 60:
                    p_image = (p_image[0], start_image[1])
                elif angle_degrees > 30:
                    if angle_degrees > 45:
                        if dx * dy > 0:
                            p_image = (p_image[0], start_image[1] + dy)
                        else:
                            p_image = (p_image[0], start_image[1] - dy)
                    else:
                        if dx * dy > 0:
                            p_image = (start_image[0] + dx, p_image[1])
                        else:
                            p_image = (start_image[0] - dx, p_image[1])
                else:
                    p_image = (start_image[0], p_image[1])
            self.end = mapping.map_point_image_to_image_norm(p_image)
        elif part[0] == "all":
            o = mapping.map_point_widget_to_image_norm(original)
            p = mapping.map_point_widget_to_image_norm(current)
            start = (part[1][0] + (p[0] - o[0]), part[1][1] + (p[1] - o[1]))
            end = (part[2][0] + (p[0] - o[0]), part[2][1] + (p[1] - o[1]))
            self.vector = (start, end)
    def nudge(self, mapping, delta):
        end_image = mapping.map_point_image_norm_to_image(self.end)
        start_image = mapping.map_point_image_norm_to_image(self.start)
        original = ((end_image[0] + start_image[0]) * 0.5, (end_image[1] + start_image[1]) * 0.5)
        current = (original[0] + delta[0], original[1] + delta[1])
        self.adjust_part(mapping, original, current, ("all", ) + self.begin_drag(), NullModifiers())
    def draw_arrow(self, ctx, p1, p2):
        arrow_size = 8
        angle = math.atan2(p2[0] - p1[0], p2[1] - p1[1])
        ctx.move_to(p2[1], p2[0])
        ctx.line_to(p2[1] - arrow_size * math.cos(angle - math.pi / 6), p2[0] - arrow_size * math.sin(angle - math.pi / 6))
        ctx.move_to(p2[1], p2[0])
        ctx.line_to(p2[1] - arrow_size * math.cos(angle + math.pi / 6), p2[0] - arrow_size * math.sin(angle + math.pi / 6))
    def draw(self, ctx, mapping, is_selected=False):
        raise NotImplementedError()


class LineGraphic(LineTypeGraphic):
    def __init__(self):
        super(LineGraphic, self).__init__("line-graphic", _("Line"))
    def draw(self, ctx, mapping, is_selected=False):
        p1 = mapping.map_point_image_norm_to_widget(self.start)
        p2 = mapping.map_point_image_norm_to_widget(self.end)
        ctx.save()
        ctx.begin_path()
        ctx.move_to(p1[1], p1[0])
        ctx.line_to(p2[1], p2[0])
        if self.start_arrow_enabled:
            self.draw_arrow(ctx, p2, p1)
        if self.end_arrow_enabled:
            self.draw_arrow(ctx, p1, p2)
        ctx.line_width = 1
        ctx.stroke_style = self.color
        ctx.stroke()
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, p1)
            self.draw_marker(ctx, p2)


class PointTypeGraphic(Graphic):
    def __init__(self, type, title):
        super(PointTypeGraphic, self).__init__(type)
        self.title = title
        # start and end points are stored in image normalized coordinates
        self.define_property(Observable.Property("position", (0.5, 0.5), changed=self._property_changed))
    # test is required for Graphic interface
    def test(self, mapping, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        p = mapping.map_point_image_norm_to_widget(self.position)
        if self.test_point(p, test_point, 4):
            return "all"
        # didn't find anything
        return None
    def begin_drag(self):
        return (self.position, )
    def end_drag(self, part_data):
        pass
    def adjust_part(self, mapping, original, current, part, modifiers):
        o_image = mapping.map_point_widget_to_image(original)
        p_image = mapping.map_point_widget_to_image(current)
        pos_image = mapping.map_point_image_norm_to_image(self.position)
        if part[0] == "all":
            o = mapping.map_point_widget_to_image_norm(original)
            p = mapping.map_point_widget_to_image_norm(current)
            pos = part[1][0] + (p[0] - o[0]), part[1][1] + (p[1] - o[1])
            self.position = pos
    def nudge(self, mapping, delta):
        pos_image = mapping.map_point_image_norm_to_image(self.position)
        original = pos_image
        current = original + delta
        self.adjust_part(mapping, original, current, ("all", ) + self.begin_drag(), NullModifiers())
    def draw(self, ctx, mapping, is_selected=False):
        raise NotImplementedError()


class PointGraphic(PointTypeGraphic):
    def __init__(self):
        super(PointGraphic, self).__init__("point-graphic", _("Point"))
    def draw(self, ctx, mapping, is_selected=False):
        p = mapping.map_point_image_norm_to_widget(self.position)
        ctx.save()
        ctx.begin_path()
        cross_hair_size = 12
        ctx.move_to(p[1] - cross_hair_size, p[0])
        ctx.line_to(p[1] + cross_hair_size, p[0])
        ctx.move_to(p[1], p[0] - cross_hair_size)
        ctx.line_to(p[1], p[0] + cross_hair_size)
        ctx.line_width = 1
        ctx.stroke_style = self.color
        ctx.stroke()
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, p)


class IntervalGraphic(Graphic):
    def __init__(self):
        super(IntervalGraphic, self).__init__("interval-graphic")
        self.title = _("Interval")
        # start and end points are stored in channel normalized coordinates
        self.define_property(Observable.Property("start", 0.0, changed=self._property_changed))
        self.define_property(Observable.Property("end", 1.0, changed=self._property_changed))
    # test is required for Graphic interface
    def test(self, mapping, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        p1 = mapping.map_point_channel_norm_to_widget(self.start)
        p2 = mapping.map_point_channel_norm_to_widget(self.end)
        # start point
        if not move_only and abs(test_point.x - p1) < 4:
            return "start"
        # end point
        if not move_only and abs(test_point.x - p2) < 4:
            return "end"
        # along the line
        if test_point.x > p1 and test_point.x < p2:
            return "all"
        # didn't find anything
        return None
    def begin_drag(self):
        return (self.start, self.end)
    def end_drag(self, part_data):
        pass
    def adjust_part(self, mapping, original, current, part, modifiers):
        o = mapping.map_point_widget_to_channel_norm(original)
        p = mapping.map_point_widget_to_channel_norm(current)
        if part[0] == "start":
            self.start = p
        elif part[0] == "end":
            self.end = p
        elif part[0] == "all":
            self.start = part[1] + (p - o)
            self.end = part[2] + (p - o)
    def nudge(self, mapping, delta):
        end_channel = mapping.map_point_channel_norm_to_channel(self.end)
        start_channel = mapping.map_point_channel_norm_to_channel(self.start)
        original = (end_channel + start_channel) * 0.5
        current = original + delta
        self.adjust_part(mapping, original, current, ("all", ) + self.begin_drag(), NullModifiers())


def factory(vault):
    build_map = {
        "line-graphic": LineGraphic,
        "rect-graphic": RectangleGraphic,
        "ellipse-graphic": EllipseGraphic,
        "point-graphic": PointGraphic,
        "interval-graphic": IntervalGraphic,
    }
    type = vault.get_value("type")
    return build_map[type]() if type in build_map else None

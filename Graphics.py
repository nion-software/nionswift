# standard libraries
import logging
import math
import uuid

# third party libraries
# None

# local libraries
from nion.swift import Storage


def fit_to_aspect_ratio(rect, aspect_ratio):
    if rect[1][1] > aspect_ratio * rect[1][0]:
        # height will fill entire frame
        new_size = (rect[1][0], rect[1][0] * aspect_ratio)
        new_origin = (rect[0][0], rect[0][1] + 0.5 * (rect[1][1] - new_size[1]))
        return (new_origin, new_size)
    else:
        new_size = (rect[1][1] / float(aspect_ratio), rect[1][1])
        new_origin = (rect[0][0] + 0.5*(rect[1][0] - new_size[0]), rect[0][1])
        return (new_origin, new_size)


def fit_to_size(rect, fit_size):
    return fit_to_aspect_ratio(rect, float(fit_size[1])/float(fit_size[0]))


def distance(p1, p2):
    return math.sqrt(pow(p2[0] - p1[0], 2) + pow(p2[1] - p1[1], 2))

def midpoint(p1, p2):
    return (0.5 * (p1[0] + p2[0]), 0.5 * (p1[1] + p2[1]))


# A Graphic object describes visible content, such as a shape, bitmap, video, or a line of text.
class Graphic(Storage.StorageBase):
    def __init__(self):
        Storage.StorageBase.__init__(self)
    # subclasses should override copy and copyFrom as necessary
    def copy(self):
        graphic = self.__class__()
        graphic.copyFrom(self)
        return graphic
    def copyFrom(self, graphic):
        pass
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
        ctx.beginPath()
        ctx.translate(cx-rx*0.5, cy-ry*0.5)
        ctx.scale(rx*0.5, ry*0.5)
        ctx.arc(1, 1, 1, 0, 2 * math.pi, False)
        ctx.restore()
        ctx.stroke()
    def draw_marker(self, ctx, p):
        ctx.save()
        ctx.fillStyle = '#00FF00'
        ctx.beginPath()
        ctx.moveTo(p[1] - 3, p[0] - 3)
        ctx.lineTo(p[1] + 3, p[0] - 3)
        ctx.lineTo(p[1] + 3, p[0] + 3)
        ctx.lineTo(p[1] - 3, p[0] + 3)
        ctx.closePath()
        ctx.fill()
        ctx.restore()


class RectangleGraphic(Graphic):
    def __init__(self):
        super(RectangleGraphic, self).__init__()
        self.storage_properties += ["bounds"]
        self.storage_type = "rect-graphic"
        # start and end points are stored in image normalized coordinates
        self.__bounds = ((0.0, 0.0), (1.0, 1.0))
    def copyFrom(self, graphic):
        super(RectangleGraphic, self).copyFrom(graphic)
        self.bounds = graphic.bounds
    @classmethod
    def build(cls, storage_reader, item_node):
        bounds = storage_reader.get_property(item_node, "bounds", ((0.0, 0.0), (1.0, 1.0)))
        graphic = cls()
        graphic.bounds = bounds
        return graphic
    # accessors
    def __get_bounds(self):
        return self.__bounds
    def __set_bounds(self, bounds):
        # normalize
        if bounds[1][0] < 0:  # height is negative
            bounds = ((bounds[0][0] + bounds[1][0], bounds[0][1]), (-bounds[1][0], bounds[1][1]))
        if bounds[1][1] < 0:  # width is negative
            bounds = ((bounds[0][0], bounds[0][1] + bounds[1][1]), (bounds[1][0], -bounds[1][1]))
        # set it
        self.__bounds = bounds
        # notify
        self.notify_set_property("bounds", self.__bounds)
    bounds = property(__get_bounds, __set_bounds)
    # implement storage protocol
    def get_storage_property(self, key):
        if key == "bounds":
            return self.bounds
        return super(RectangleGraphic, self).get_storage_property(key)
    def test(self, mapping, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        origin = mapping.map_point_graphic_to_container(self.bounds[0])
        size = mapping.map_size_graphic_to_container(self.bounds[1])
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
    def calibrated_description(self, image_size, calibrations):
        size_image = (image_size[0] * self.bounds[1][0], image_size[1] * self.bounds[1][1])
        origin_image = (size_image[0] * 0.5 + image_size[0] * self.bounds[0][0] - 0.5 * image_size[0],
                        size_image[1] * 0.5 + image_size[1] * self.bounds[0][1] - 0.5 * image_size[1])
        origin_x_str = calibrations[1].convert_to_calibrated_str(origin_image[1])
        origin_y_str = calibrations[0].convert_to_calibrated_str(origin_image[0])
        size_x_str = calibrations[1].convert_to_calibrated_str(size_image[1])
        size_y_str = calibrations[0].convert_to_calibrated_str(size_image[0])
        return "Rectangle\n  Center ({0}, {1})\n  Size ({2} x {3})".format(origin_x_str, origin_y_str, size_x_str, size_y_str)
    def begin_drag(self):
        return (self.bounds, )
    def end_drag(self, part_data):
        pass
    def adjust_part(self, mapping, original, current, part, modifiers):
        o = mapping.map_point_container_to_graphic(original)
        p = mapping.map_point_container_to_graphic(current)
        old_bounds = part[1]
        old_origin = part[1][0]
        old_size = part[1][1]
        delta = (p[0] - o[0], p[1] - o[1])
        if part[0] == "top-left":  # top left
            new_bounds = ((old_origin[0] + delta[0], old_origin[1] + delta[1]), (old_size[0] - delta[0], old_size[1] - delta[1]))
            if modifiers.shift:  # hold bottom right constant
                if new_bounds[1][0] > new_bounds[1][1]:  # size will be width
                    new_bounds = ((new_bounds[0][0] + new_bounds[1][0] - new_bounds[1][1], new_bounds[0][1]), (new_bounds[1][1], new_bounds[1][1]))
                else:  # size will be height
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1] + new_bounds[1][1] - new_bounds[1][0]), (new_bounds[1][0], new_bounds[1][0]))
            self.bounds = new_bounds
        elif part[0] == "top-right":  # top right
            new_bounds = ((old_origin[0] + delta[0], old_origin[1]), (old_size[0] - delta[0], old_size[1] + delta[1]))
            if modifiers.shift:  # hold bottom left constant
                if new_bounds[1][0] > new_bounds[1][1]:  # size will be width
                    new_bounds = ((new_bounds[0][0] + new_bounds[1][0] - new_bounds[1][1], new_bounds[0][1]), (new_bounds[1][1], new_bounds[1][1]))
                else:  # size will be height
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1]), (new_bounds[1][0], new_bounds[1][0]))
            self.bounds = new_bounds
        elif part[0] == "bottom-right":  # bottom right
            new_bounds = ((old_origin[0], old_origin[1]), (old_size[0] + delta[0], old_size[1] + delta[1]))
            if modifiers.shift:  # hold bottom left constant
                if new_bounds[1][0] > new_bounds[1][1]:  # size will be width
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1]), (new_bounds[1][1], new_bounds[1][1]))
                else:  # size will be height
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1]), (new_bounds[1][0], new_bounds[1][0]))
            self.bounds = new_bounds
        elif part[0] == "bottom-left":  # bottom left
            new_bounds = ((old_origin[0], old_origin[1] + delta[1]), (old_size[0] + delta[0], old_size[1] - delta[1]))
            if modifiers.shift:  # hold bottom left constant
                if new_bounds[1][0] > new_bounds[1][1]:  # size will be width
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1]), (new_bounds[1][1], new_bounds[1][1]))
                else:  # size will be height
                    new_bounds = ((new_bounds[0][0], new_bounds[0][1] + new_bounds[1][1] - new_bounds[1][0]), (new_bounds[1][0], new_bounds[1][0]))
            self.bounds = new_bounds
        elif part[0] == "all":
            new_bounds = ((old_origin[0] + delta[0], old_origin[1] + delta[1]), old_size)
            self.bounds = new_bounds
    def draw(self, ctx, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_graphic_to_container(self.bounds[0])
        size = mapping.map_size_graphic_to_container(self.bounds[1])
        ctx.save()
        ctx.beginPath()
        ctx.moveTo(origin[1], origin[0])
        ctx.lineTo(origin[1] + size[1], origin[0])
        ctx.lineTo(origin[1] + size[1], origin[0] + size[0])
        ctx.lineTo(origin[1], origin[0] + size[0])
        ctx.closePath()
        ctx.lineWidth = 1
        ctx.strokeStyle = '#FF0000'
        ctx.stroke()
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, origin)
            self.draw_marker(ctx, (origin[0] + size[0], origin[1]))
            self.draw_marker(ctx, (origin[0] + size[0], origin[1] + size[1]))
            self.draw_marker(ctx, (origin[0], origin[1] + size[1]))
            mark_size = 8
            if size[0] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.beginPath()
                ctx.moveTo(mid_x - 0.5*mark_size, mid_y)
                ctx.lineTo(mid_x + 0.5*mark_size, mid_y)
                ctx.strokeStyle = '#FF0000'
                ctx.stroke()
                ctx.restore()
            if size[1] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.beginPath()
                ctx.moveTo(mid_x, mid_y - 0.5*mark_size)
                ctx.lineTo(mid_x, mid_y + 0.5*mark_size)
                ctx.strokeStyle = '#FF0000'
                ctx.stroke()
                ctx.restore()


class EllipseGraphic(Graphic):
    def __init__(self):
        super(EllipseGraphic, self).__init__()
        self.storage_properties += ["bounds"]
        self.storage_type = "ellipse-graphic"
        # start and end points are stored in image normalized coordinates
        self.__bounds = ((0.0, 0.0), (1.0, 1.0))
    def copyFrom(self, graphic):
        super(EllipseGraphic, self).copyFrom(graphic)
        self.bounds = graphic.bounds
    @classmethod
    def build(cls, storage_reader, item_node):
        bounds = storage_reader.get_property(item_node, "bounds", ((0.0, 0.0), (1.0, 1.0)))
        graphic = cls()
        graphic.bounds = bounds
        return graphic
    # accessors
    def __get_bounds(self):
        return self.__bounds
    def __set_bounds(self, bounds):
        # normalize
        if bounds[1][0] < 0:  # height is negative
            bounds = ((bounds[0][0] + bounds[1][0], bounds[0][1]), (-bounds[1][0], bounds[1][1]))
        if bounds[1][1] < 0:  # width is negative
            bounds = ((bounds[0][0], bounds[0][1] + bounds[1][1]), (bounds[1][0], -bounds[1][1]))
        # set it
        self.__bounds = bounds
        # notify
        self.notify_set_property("bounds", self.__bounds)
    bounds = property(__get_bounds, __set_bounds)
    # implement storage protocol
    def get_storage_property(self, key):
        if key == "bounds":
            return self.bounds
        return super(EllipseGraphic, self).get_storage_property(key)
    def test(self, mapping, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        origin = mapping.map_point_graphic_to_container(self.bounds[0])
        size = mapping.map_size_graphic_to_container(self.bounds[1])
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
    def calibrated_description(self, image_size, calibrations):
        size_image = (image_size[0] * self.bounds[1][0], image_size[1] * self.bounds[1][1])
        origin_image = (size_image[0] * 0.5 + image_size[0] * self.bounds[0][0] - 0.5 * image_size[0],
                        size_image[1] * 0.5 + image_size[1] * self.bounds[0][1] - 0.5 * image_size[1])
        origin_x_str = calibrations[1].convert_to_calibrated_str(origin_image[1])
        origin_y_str = calibrations[0].convert_to_calibrated_str(origin_image[0])
        size_x_str = calibrations[1].convert_to_calibrated_str(size_image[1])
        size_y_str = calibrations[0].convert_to_calibrated_str(size_image[0])
        return "Ellipse\n  Center ({0}, {1})\n  Size ({2} x {3})".format(origin_x_str, origin_y_str, size_x_str, size_y_str)
    def begin_drag(self):
        return (self.bounds, )
    def end_drag(self, part_data):
        pass
    def adjust_part(self, mapping, original, current, part, modifiers):
        o = mapping.map_point_container_to_graphic(original)
        p = mapping.map_point_container_to_graphic(current)
        old_bounds = part[1]
        old_origin = part[1][0]
        old_size = part[1][1]
        old_center = (part[1][0][0] + 0.5*part[1][1][0], part[1][0][1] + 0.5*part[1][1][1])
        delta = (p[0] - o[0], p[1] - o[1])
        if part[0] == "top-left":  # top left
            new_top_left = (old_origin[0] + delta[0], old_origin[1] + delta[1])
            if modifiers.shift:  # hold bottom left constant
                half_size = (old_center[0] - new_top_left[0], old_center[1] - new_top_left[1])
                if half_size[0] > half_size[1]:  # size will be width
                    new_top_left = (old_center[0] + half_size[1], new_top_left[1])
                else:  # size will be height
                    new_top_left = (new_top_left[0], old_center[1] + half_size[0])
            new_bottom_right = (2*old_center[0] - new_top_left[0], 2*old_center[1] - new_top_left[1])
            new_bounds = (new_top_left, (new_bottom_right[0] - new_top_left[0], new_bottom_right[1] - new_top_left[1]))
            self.bounds = new_bounds
        elif part[0] == "top-right":  # top right
            new_top_right = (old_origin[0] + delta[0], old_origin[1] + old_size[1] + delta[1])
            if modifiers.shift:  # hold bottom left constant
                half_size = (old_center[0] - new_top_right[0], old_center[1] - new_top_right[1])
                if half_size[0] > half_size[1]:  # size will be width
                    new_top_right = (old_center[0] + half_size[1], new_top_right[1])
                else:  # size will be height
                    new_top_right = (new_top_right[0], old_center[1] + half_size[0])
            new_bottom_left = (2*old_center[0] - new_top_right[0], 2*old_center[1] - new_top_right[1])
            new_bounds = ((new_top_right[0], new_bottom_left[1]), (new_bottom_left[0] - new_top_right[0], new_top_right[1] - new_bottom_left[1]))
            self.bounds = new_bounds
        elif part[0] == "bottom-right":  # bottom right
            new_bottom_right = (old_origin[0] + old_size[0] + delta[0], old_origin[1] + old_size[1] + delta[1])
            if modifiers.shift:  # hold bottom left constant
                half_size = (old_center[0] - new_bottom_right[0], old_center[1] - new_bottom_right[1])
                if half_size[0] > half_size[1]:  # size will be width
                    new_bottom_right = (old_center[0] + half_size[1], new_bottom_right[1])
                else:  # size will be height
                    new_bottom_right = (new_bottom_right[0], old_center[1] + half_size[0])
            new_top_left = (2*old_center[0] - new_bottom_right[0], 2*old_center[1] - new_bottom_right[1])
            new_bounds = (new_top_left, (new_bottom_right[0] - new_top_left[0], new_bottom_right[1] - new_top_left[1]))
            self.bounds = new_bounds
        elif part[0] == "bottom-left":  # bottom left
            new_bottom_left = (old_origin[0] + old_size[0] + delta[0], old_origin[1] + delta[1])
            if modifiers.shift:  # hold bottom left constant
                half_size = (old_center[0] - new_bottom_left[0], old_center[1] - new_bottom_left[1])
                if half_size[0] > half_size[1]:  # size will be width
                    new_bottom_left = (old_center[0] + half_size[1], new_bottom_left[1])
                else:  # size will be height
                    new_bottom_left = (new_bottom_left[0], old_center[1] + half_size[0])
            new_top_right = (2*old_center[0] - new_bottom_left[0], 2*old_center[1] - new_bottom_left[1])
            new_bounds = ((new_top_right[0], new_bottom_left[1]), (new_bottom_left[0] - new_top_right[0], new_top_right[1] - new_bottom_left[1]))
            self.bounds = new_bounds
        elif part[0] == "all":
            new_bounds = ((old_origin[0] + delta[0], old_origin[1] + delta[1]), old_size)
            self.bounds = new_bounds
    def draw(self, ctx, mapping, is_selected=False):
        # origin is top left
        origin = mapping.map_point_graphic_to_container(self.bounds[0])
        size = mapping.map_size_graphic_to_container(self.bounds[1])
        ctx.save()
        ctx.lineWidth = 1
        ctx.strokeStyle = '#FF0000'
        self.draw_ellipse(ctx, origin[1] + size[1]*0.5, origin[0] + size[0]*0.5, size[1], size[0])
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, origin)
            self.draw_marker(ctx, (origin[0] + size[0], origin[1]))
            self.draw_marker(ctx, (origin[0] + size[0], origin[1] + size[1]))
            self.draw_marker(ctx, (origin[0], origin[1] + size[1]))
            mark_size = 8
            if size[0] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.beginPath()
                ctx.moveTo(mid_x - 0.5*mark_size, mid_y)
                ctx.lineTo(mid_x + 0.5*mark_size, mid_y)
                ctx.strokeStyle = '#FF0000'
                ctx.stroke()
                ctx.restore()
            if size[1] > mark_size:
                mid_x = origin[1] + 0.5*size[1]
                mid_y = origin[0] + 0.5*size[0]
                ctx.save()
                ctx.beginPath()
                ctx.moveTo(mid_x, mid_y - 0.5*mark_size)
                ctx.lineTo(mid_x, mid_y + 0.5*mark_size)
                ctx.strokeStyle = '#FF0000'
                ctx.stroke()
                ctx.restore()


class LineGraphic(Graphic):
    def __init__(self):
        super(LineGraphic, self).__init__()
        self.storage_properties += ["start", "end"]
        self.storage_type = "line-graphic"
        # start and end points are stored in image normalized coordinates
        self.__start = (0.0, 0.0)
        self.__end = (1.0, 1.0)
    def copyFrom(self, line_graphic):
        super(LineGraphic, self).copyFrom(line_graphic)
        self.start = line_graphic.start
        self.end = line_graphic.end
    @classmethod
    def build(cls, storage_reader, item_node):
        start = storage_reader.get_property(item_node, "start", (0.0, 0.0))
        end = storage_reader.get_property(item_node, "end", (1.0, 1.0))
        graphic = cls()
        graphic.start = start
        graphic.end = end
        return graphic
    # accessors
    def __get_start(self):
        return self.__start
    def __set_start(self, start):
        self.__start = start
        self.notify_set_property("start", self.__start)
    start = property(__get_start, __set_start)
    def __get_end(self):
        return self.__end
    def __set_end(self, end):
        self.__end = end
        self.notify_set_property("end", self.__end)
    end = property(__get_end, __set_end)
    # implement storage protocol
    def get_storage_property(self, key):
        if key == "start":
            return self.start
        if key == "end":
            return self.end
        return super(LineGraphic, self).get_storage_property(self, key)
    # test is required for Graphic interface
    def test(self, mapping, test_point, move_only):
        # first convert to widget coordinates since test distances
        # are specified in widget coordinates
        p1 = mapping.map_point_graphic_to_container(self.start)
        p2 = mapping.map_point_graphic_to_container(self.end)
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
    def calibrated_description(self, image_size, calibrations):
        start_image = (image_size[0] * self.start[0], image_size[1] * self.start[1])
        end_image = (image_size[0] * self.end[0], image_size[1] * self.end[1])
        start_x_str = calibrations[1].convert_to_calibrated_str(start_image[1])
        start_y_str = calibrations[0].convert_to_calibrated_str(start_image[0])
        end_x_str = calibrations[1].convert_to_calibrated_str(end_image[1])
        end_y_str = calibrations[0].convert_to_calibrated_str(end_image[0])
        return "Line\n  Start ({0}, {1})\n  End ({2}, {3})".format(start_x_str, start_y_str, end_x_str, end_y_str)
    def begin_drag(self):
        return (self.start, self.end)
    def end_drag(self, part_data):
        pass
    def adjust_part(self, mapping, original, current, part, modifiers):
        o = mapping.map_point_container_to_graphic(original)
        p = mapping.map_point_container_to_graphic(current)
        if part[0] == "start":
            if modifiers.shift:
                if abs(p[0] - self.end[0]) > abs(p[1] - self.end[1]):
                    p = (p[0], self.end[1])
                else:
                    p = (self.end[0], p[1])
            self.start = p
        elif part[0] == "end":
            if modifiers.shift:
                if abs(p[0] - self.start[0]) > abs(p[1] - self.start[1]):
                    p = (p[0], self.start[1])
                else:
                    p = (self.start[0], p[1])
            self.end = p
        elif part[0] == "all":
            self.start = (part[1][0] + (p[0] - o[0]), part[1][1] + (p[1] - o[1]))
            self.end = (part[2][0] + (p[0] - o[0]), part[2][1] + (p[1] - o[1]))
    def draw(self, ctx, mapping, is_selected=False):
        p1 = mapping.map_point_graphic_to_container(self.start)
        p2 = mapping.map_point_graphic_to_container(self.end)
        ctx.save()
        ctx.beginPath()
        ctx.moveTo(p1[1], p1[0])
        ctx.lineTo(p2[1], p2[0])
        ctx.lineWidth = 1
        ctx.strokeStyle = '#FF0000'
        ctx.stroke()
        ctx.restore()
        if is_selected:
            self.draw_marker(ctx, p1)
            self.draw_marker(ctx, p2)

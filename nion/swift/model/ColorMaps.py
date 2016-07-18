import colorsys
import numpy
import math
import typing

def interpolate_colors(array: typing.List[int], x: int) -> typing.List[int]:
    """
    Creates a color map for values in array
    :param array: color map to interpolate
    :param x: number of colors
    :return: interpolated color map
    """
    out_array = []
    for i in range(x):
        if i % (x / (len(array) - 1)) == 0:
            index = i / (x / (len(array) - 1))
            out_array.append(array[int(index)])
        else:
            start_marker = array[math.floor(i / (x / (len(array) - 1)))]
            stop_marker = array[math.ceil(i / (x / (len(array) - 1)))]
            interp_amount = i % (x / (len(array) - 1)) / (x / (len(array) - 1))
            interp_color = numpy.rint(start_marker + ((stop_marker - start_marker) * interp_amount))
            out_array.append(interp_color)
    out_array[-1] = array[-1]
    return numpy.array(out_array).astype(numpy.uint8)

def generate_lookup_array_grayscale():
    out_list = []
    for i in range(256):
        out_list.append([i, i, i])
    return numpy.array(out_list)

lookup_arrays = {
    'magma':     [[0, 0, 0],
                  [127, 0, 127],
                  [96, 96, 255],
                  [64, 192, 255],
                  [223, 255, 255]],
    'viridis':   [[32, 32, 64],
                  [160, 160, 64],
                  [208, 208, 0],
                  [144, 255, 32],
                  [0, 255, 255]],
    'plasma':    [[127, 0, 0],
                  [127, 0, 127],
                  [127, 127, 255],
                  [127, 255, 255],
                  [195, 255, 255]],
    'ice':       [[0, 0, 0],
                  [127, 0, 0],
                  [255, 127, 0],
                  [255, 255, 127],
                  [255, 255, 255]]
}

def generate_lookup_array(color_map_id: str) -> numpy.array:
    return interpolate_colors(numpy.array(lookup_arrays[color_map_id]), 256)

def generate_lookup_array_hsv() -> numpy.array:
    result_array = []
    for lookup_value in range(256):
        color_values = [x * 255 for x in colorsys.hsv_to_rgb(lookup_value / 300, 1.0, 1.0)]
        result_array.append(color_values)
    return numpy.array(result_array).astype(int)

color_maps = {}
color_maps['magma'] = generate_lookup_array('magma')
color_maps['ice'] = generate_lookup_array('ice')
color_maps['plasma'] = generate_lookup_array('plasma')
color_maps['viridis'] = generate_lookup_array('viridis')
color_maps['hsv'] = generate_lookup_array_hsv()
color_maps['grayscale'] = generate_lookup_array_grayscale()
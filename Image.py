# standard libraries
import logging
import math
import sys

# third party libraries
import numpy
import scipy
import scipy.interpolate

# local libraries
import UserInterface


# size is c-indexed (height, width)
def scaled(image, size, method='linear'):
    assert numpy.ndim(image) in (2,3)
    if numpy.ndim(image) == 2:
        if method == 'cubic':
            new_x_coords = numpy.linspace(0, image.shape[1], size[1])
            new_y_coords = numpy.linspace(0, image.shape[0], size[0])
            f = scipy.interpolate.RectBivariateSpline(numpy.arange(image.shape[0]), numpy.arange(image.shape[1]), image)
            data = f(new_y_coords, new_x_coords)
            return data
        elif method == 'linear':
            fy = scipy.interpolate.interp1d(numpy.arange(image.shape[0]), image, axis=0, copy=True)
            iy = (image.shape[0]-1) * numpy.arange(size[0]).astype(float) / size[0]
            image = fy(iy)
            fx = scipy.interpolate.interp1d(numpy.arange(image.shape[1]), image, axis=1, copy=True)
            ix = (image.shape[1]-1) * numpy.arange(size[1]).astype(float) / size[1]
            image = fx(ix)
            return image
        else:  # nearest
            dst = numpy.empty(size, image.dtype)
            indices = numpy.indices(size)
            indices[0] = ((image.shape[0]-1) * indices[0].astype(float) / size[0]).round()
            indices[1] = ((image.shape[1]-1) * indices[1].astype(float) / size[1]).round()
            dst[:, :] = image[(indices[0], indices[1])]
            return dst
    elif numpy.ndim(image) == 3:
        assert image.shape[2] in (3,4)  # rgb, rgba
        dst_image = numpy.empty(size + (image.shape[2],), numpy.uint8)
        dst_image[:, :, 0] = scaled(image[:, :, 0], size, method=method)
        dst_image[:, :, 1] = scaled(image[:, :, 1], size, method=method)
        dst_image[:, :, 2] = scaled(image[:, :, 2], size, method=method)
        if image.shape[2] == 4:
            dst_image[:, :, 3] = scaled(image[:, :, 3], size, method=method)
        return dst_image
    return None


def byteView(rgba_image):
    return rgba_image.view(numpy.uint8).reshape(rgba_image.shape + (-1, ))


def rgbView(rgba_image, byteorder=None):
    if byteorder is None:
        byteorder = sys.byteorder
    bytes = byteView(rgba_image)
    assert bytes.shape[2] == 4
    if byteorder == 'little':
        return bytes[..., :3]  # strip A off BGRA
    else:
        return bytes[..., 1:]  # strip A off ARGB


def alphaView(rgba_image, byteorder=None):
    if byteorder is None:
        byteorder = sys.byteorder
    bytes = byteView(rgba_image)
    assert bytes.shape[2] == 4
    if byteorder == 'little':
        return bytes[..., 3]  # A of BGRA
    else:
        return bytes[..., 0]  # A of ARGB


def createCheckerboard(size):
    data = numpy.zeros(size, numpy.uint32)
    xx, yy = numpy.meshgrid(numpy.linspace(0,1,size[0]), numpy.linspace(0,1,size[1]))
    data[:] = numpy.sin(12*math.pi*xx)*numpy.sin(12*math.pi*yy) > 0
    return data


def createColor(size, r, g, b, a = 255):
    return byteView(createRGBAImageFromColor(size, r, g, b, a))


def createRGBAImageFromColor(size, r, g, b, a=255):
    rgba_image = numpy.empty(size, 'uint32')
    rgbView(rgba_image)[:] = (b,g,r)  # scalar data assigned to each component of rgb view
    alphaView(rgba_image)[:] = a
    return rgba_image


def scalarFromArray(array, normalize=True):
    if numpy.iscomplexobj(array):
        res = numpy.log(numpy.abs(array) + 1)
        return res
    return array


def createRGBAImageFromArray(array, normalize=True, display_limits=None):
    assert numpy.ndim(array) in (2,3)
    assert numpy.can_cast(array.dtype, numpy.double)
    if numpy.ndim(array) == 2:
        rgba_image = numpy.empty(array.shape, 'uint32')
        if normalize:
            nmin = numpy.amin(array)
            nmax = numpy.amax(array)
            if display_limits and (display_limits[0] != 0 or display_limits[1] != 1):
                nmin_new = nmin + (nmax - nmin)*display_limits[0]
                nmax_new = nmin + (nmax - nmin)*display_limits[1]
                a = numpy.maximum(numpy.minimum(array, nmax_new), nmin_new)
                # scalar data assigned to each component of rgb view
                m = 255.0 / (nmax_new - nmin_new) if nmax_new != nmin_new else 1
                rgbView(rgba_image)[:] = m * (a[..., numpy.newaxis] - nmin_new)
            else:
                # scalar data assigned to each component of rgb view
                m = 255.0 / (nmax - nmin) if nmax != nmin else 1
                rgbView(rgba_image)[:] = m * (array[..., numpy.newaxis] - nmin)
        else:
            rgbView(rgba_image)[:] = array[..., numpy.newaxis]  # scalar data assigned to each component of rgb view
        alphaView(rgba_image)[:] = 255
        return rgba_image
    if numpy.ndim(array) == 3:
        assert array.shape[2] in (3,4)  # rgb, rgba
        if array.shape[2] == 4:
            return array.view(numpy.uint32).reshape(array.shape[:-1])  # squash the color into uint32
        else:
            assert array.shape[2] == 3
            rgba_image = numpy.empty(array.shape[:-1] + (4,), numpy.uint8)
            rgba_image[:,:,0:3] = array
            rgba_image[:,:,3] = 255
            return rgba_image.view(numpy.uint32).reshape(rgba_image.shape[:-1])  # squash the color into uint32
    return None


def readImageFromFile(ui, filename, dtype=numpy.uint32):
    rgba_image = ui.readImageToPyArray(filename)
    assert rgba_image is not None
    image = numpy.zeros(rgba_image.shape, dtype)
    image[:, :] = numpy.mean(rgbView(rgba_image), 2)
    return image

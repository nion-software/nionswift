# standard libraries
import logging
import math
import sys

# third party libraries
import numpy
import scipy
import scipy.interpolate

# local libraries
# None

def scale_multidimensional(image, scaled_size):
    """
    Return image scaled to scaled_size. scaled_size should be a sequence
    with the same length as image.
    """
    # we make a list of slice objects like [0:image_x-1:scaled_size_x*1j]
    # this will give us scaled_size_x equal points between 0 and image_x-1
    slices = [slice(0, x-1, y*1j) for x, y in zip(image.shape, scaled_size)]
    # we pass slices into ogrid, to gives us vectors for each dimension
    # ogrid returns a list of floating numbers if we use complex so we have
    # to convert to int. np.rint rounds to nearest for us, but doesn't cast to int!
    coords = [numpy.rint(x).astype(numpy.int) for x in numpy.ogrid[slices]]
    # coords is now, for an array image of dimension n, a list of n 1d arrays we the
    # coords we want to take from image:
    return image[coords]


# size is c-indexed (height, width)
def scaled(image, size, method='linear'):
    if method=='nearest':
        return scale_multidimensional(image, size)

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


def rebin_1d(src, len):
    src_len = src.shape[0]
    if len < src_len:
        # create linear bins
        ss = numpy.linspace(0, len, len+1) * float(src_len) / len
        # create some useful row and column values using meshgrid
        ix, iy = numpy.meshgrid(numpy.linspace(0, src_len-1, src_len), numpy.linspace(0, len-1, len))
        ix = ix.astype(numpy.int32)
        iy = iy.astype(numpy.int32)
        # basic idea here is to multiply low window by high window to get the window for each bin; then sum the transpose to do the actual binning
        # result is scaled to keep amplitude the same.
        return sum((numpy.maximum(numpy.minimum(ss[iy+1] - ix, 1.0), 0.0) * numpy.minimum(numpy.maximum(ix+1 - ss[iy], 0), 1.0) * src).transpose()) * len / src_len
    else:
        # linear
        result = numpy.empty((len, ), dtype=numpy.double)
        index = numpy.linspace(0, src_len-1, len).astype(numpy.int32)
        result[:] = src[index]
        return result
    return src


def get_byte_view(rgba_image):
    return rgba_image.view(numpy.uint8).reshape(rgba_image.shape + (-1, ))


def get_rgb_view(rgba_image, byteorder=None):
    if byteorder is None:
        byteorder = sys.byteorder
    bytes = get_byte_view(rgba_image)
    assert bytes.shape[2] == 4
    if byteorder == 'little':
        return bytes[..., :3]  # strip A off BGRA
    else:
        return bytes[..., 1:]  # strip A off ARGB


def get_alpha_view(rgba_image, byteorder=None):
    if byteorder is None:
        byteorder = sys.byteorder
    bytes = get_byte_view(rgba_image)
    assert bytes.shape[2] == 4
    if byteorder == 'little':
        return bytes[..., 3]  # A of BGRA
    else:
        return bytes[..., 0]  # A of ARGB


def create_checkerboard(size):
    data = numpy.zeros(size, numpy.uint32)
    xx, yy = numpy.meshgrid(numpy.linspace(0,1,size[0]), numpy.linspace(0,1,size[1]))
    data[:] = numpy.sin(12*math.pi*xx)*numpy.sin(12*math.pi*yy) > 0
    return data


def create_color_image(size, r, g, b, a = 255):
    return get_byte_view(create_rgba_image_from_color(size, r, g, b, a))


def create_rgba_image_from_color(size, r, g, b, a=255):
    rgba_image = numpy.empty(size, dtype=numpy.uint32)
    get_rgb_view(rgba_image)[:] = (b,g,r)  # scalar data assigned to each component of rgb view
    get_alpha_view(rgba_image)[:] = a
    return rgba_image


def dimensional_shape_from_shape_and_dtype(shape, dtype):
    if shape is None or dtype is None:
        return None
    return shape[:-1] if dtype == numpy.uint8 and shape[-1] in (3,4) and len(shape) > 1 else shape
def spatial_shape_from_data(data):
    return dimensional_shape_from_shape_and_dtype(data.shape, data.dtype)

def is_shape_and_dtype_rgb(shape, dtype):
    if shape is None or dtype is None:
        return False
    return dtype == numpy.uint8 and shape[-1] == 3 and len(shape) > 1
def is_data_rgb(data):
    return data is not None and is_shape_and_dtype_rgb(data.shape, data.dtype)


def is_shape_and_dtype_rgba(shape, dtype):
    if shape is None or dtype is None:
        return False
    return dtype == numpy.uint8 and shape[-1] == 4 and len(shape) > 1
def is_data_rgba(data):
    return data is not None and is_shape_and_dtype_rgba(data.shape, data.dtype)


def is_shape_and_dtype_rgb_type(shape, dtype):
    return is_shape_and_dtype_rgb(shape, dtype) or is_shape_and_dtype_rgba(shape, dtype)
def is_data_rgb_type(data):
    return data is not None and is_shape_and_dtype_rgb_type(data.shape, data.dtype)


def is_shape_and_dtype_complex64(shape, dtype):
    if shape is None or dtype is None:
        return False
    return dtype == numpy.complex64
def is_data_complex64(data):
    return data is not None and is_shape_and_dtype_complex64(data.shape, data.dtype)


def is_shape_and_dtype_complex128(shape, dtype):
    if shape is None or dtype is None:
        return False
    return dtype == numpy.complex128
def is_data_complex128(data):
    return data is not None and is_shape_and_dtype_complex128(data.shape, data.dtype)


def is_shape_and_dtype_complex_type(shape, dtype):
    if shape is None or dtype is None:
        return False
    return dtype == numpy.complex64 or dtype == numpy.complex128
def is_data_complex_type(data):
    return data is not None and is_shape_and_dtype_complex_type(data.shape, data.dtype)


def is_shape_and_dtype_scalar_type(shape, dtype):
    if shape is None or dtype is None:
        return False
    return not is_shape_and_dtype_rgb_type(shape, dtype) and not is_shape_and_dtype_complex_type(shape, dtype)
def is_data_scalar_type(data):
    return data is not None and is_shape_and_dtype_scalar_type(data.shape, data.dtype)


def is_shape_and_dtype_1d(shape, dtype):
    if shape is None or dtype is None:
        return False
    if is_shape_and_dtype_rgb(shape, dtype) or is_shape_and_dtype_rgba(shape, dtype):
        return len(shape) == 2  # one extra dimension for rgb(a) values
    return len(shape) == 1
def is_data_1d(data):
    return data is not None and is_shape_and_dtype_1d(data.shape, data.dtype)


def is_shape_and_dtype_2d(shape, dtype):
    if shape is None or dtype is None:
        return False
    if is_shape_and_dtype_rgb(shape, dtype) or is_shape_and_dtype_rgba(shape, dtype):
        return len(shape) == 3  # one extra dimension for rgb(a) values
    return len(shape) == 2
def is_data_2d(data):
    return data is not None and is_shape_and_dtype_2d(data.shape, data.dtype)


def is_shape_and_dtype_3d(shape, dtype):
    if shape is None or dtype is None:
        return False
    if is_shape_and_dtype_rgb(shape, dtype) or is_shape_and_dtype_rgba(shape, dtype):
        return len(shape) == 4  # one extra dimension for rgb(a) values
    return len(shape) == 3
def is_data_3d(data):
    return data is not None and is_shape_and_dtype_3d(data.shape, data.dtype)


def scalar_from_array(array, normalize=True):
    if numpy.iscomplexobj(array):
        # numpy.nextafter returns the next possible represented number after 0 in the direction of 1
        # this prevents log from generating -inf from 0.0
        # quick way to drop out bottom percent:
        # samples = 2000, fraction=0.10
        # numpy.log(numpy.sort(numpy.abs(numpy.random.choice(data.reshape(numpy.product(data.shape)), samples)))[samples*fraction])
        # unfortunately, this needs to be integrated into the display calculation, not the conversion here.
        # the annoying conversion to float64 is to prevent float32 + float64 returning a 0.0. argh.
        # TODO: consider optimizing log(abs) to 0.5*log(re**2 + im**2)
        return numpy.log(numpy.abs(array).astype(numpy.float64) + numpy.nextafter(0,1))
    return array


# data_range and display_limits are in data value units. both are option parameters.
# if display limits is specified, values out of range are mapped to the min/max colors.
# if display limits are not specified, data range can be passed to avoid calculating min/max again.
# if underlimit/overlimit are specified and display limits are specified, values out of the under/over
#   limit percentage values are mapped to blue and red.
# may return a new array or a view on the existing array
def create_rgba_image_from_array(array, normalize=True, data_range=None, display_limits=None, underlimit=None, overlimit=None, lookup=None):
    assert numpy.ndim(array) in (1, 2, 3)
    assert numpy.can_cast(array.dtype, numpy.double)
    if numpy.ndim(array) == 1:  # temporary hack to display 1-d images
        array = array.reshape((1,) + array.shape)
    if numpy.ndim(array) == 2:
        rgba_image = numpy.empty(array.shape, 'uint32')
        if normalize:
            if display_limits and len(display_limits) == 2:
                nmin_new = display_limits[0]
                nmax_new = display_limits[1]
                a = numpy.maximum(numpy.minimum(array, nmax_new), nmin_new)
                # scalar data assigned to each component of rgb view
                m = 255.0 / (nmax_new - nmin_new) if nmax_new != nmin_new else 1
                if lookup is not None:
                    get_rgb_view(rgba_image)[:] = lookup[(m * (a - nmin_new)).astype(int)]
                else:
                    get_rgb_view(rgba_image)[:] = m * (a[..., numpy.newaxis] - nmin_new)
                if overlimit:
                    rgba_image = numpy.where(numpy.less(array - nmin_new, nmax_new - nmin_new * overlimit), rgba_image, 0xFFFF0000)
                if underlimit:
                    rgba_image = numpy.where(numpy.greater(array - nmin_new, nmax_new - nmin_new * underlimit), rgba_image, 0xFF0000FF)
            elif array.size:
                nmin = data_range[0] if data_range else numpy.amin(array)
                nmax = data_range[1] if data_range else numpy.amax(array)
                # scalar data assigned to each component of rgb view
                m = 255.0 / (nmax - nmin) if nmax != nmin else 1
                if lookup is not None:
                    get_rgb_view(rgba_image)[:] = lookup[(m * (array - nmin)).astype(int)]
                else:
                    get_rgb_view(rgba_image)[:] = m * (array[..., numpy.newaxis] - nmin)
                if overlimit:
                    rgba_image = numpy.where(numpy.less(array - nmin, (nmax - nmin) * overlimit), rgba_image, 0xFFFF0000)
                if underlimit:
                    rgba_image = numpy.where(numpy.greater(array - nmin, (nmax - nmin) * underlimit), rgba_image, 0xFF0000FF)
        else:
            get_rgb_view(rgba_image)[:] = array[..., numpy.newaxis]  # scalar data assigned to each component of rgb view
        if rgba_image.size:
            get_alpha_view(rgba_image)[:] = 255
        return rgba_image
    elif numpy.ndim(array) == 3:
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


# convert data to grayscale. may return same copy of data, or a copy.
def convert_to_grayscale(data, dtype=numpy.uint32):
    if is_data_rgb(data) or is_data_rgba(data):
        image = numpy.empty(data.shape[:-1], dtype)
        # don't be tempted to use the numpy.dot operator; after testing, this explicit method
        # is faster by a factor of two. cem 2013-11-02.
        # note 0=b, 1=g, 2=r, 3=a. calculate luminosity.
        image[...] = 0.0722 * data[..., 0] + 0.7152 * data[..., 1] + 0.2126 * data[..., 2]
        return image
    else:
        return scalar_from_array(data)


# return True if data is grayscale.
def is_grayscale(data):
    if is_data_rgb(data) or is_data_rgba(data):
        return numpy.array_equal(data[..., 0],data[..., 1]) and numpy.array_equal(data[..., 1],data[..., 2])
    return True


# read image file. return as rgba uint8.
def read_rgba_image_from_file(ui, filename):
    rgba_image = ui.load_rgba_data_from_file(filename)  # always loads rgba
    assert rgba_image is not None
    return rgba_image.view(numpy.uint8).reshape(rgba_image.shape + (4,))


# read image file. convert to dtype.
def read_grayscale_image_from_file(ui, filename, dtype=numpy.uint32):
    data = read_rgba_image_from_file(ui, filename)
    return convert_to_grayscale(data, dtype)


# read image file. convert to dtype if it is grayscale.
def read_image_from_file(ui, filename, dtype=numpy.uint32):
    data = read_rgba_image_from_file(ui, filename)
    if is_grayscale(data):
        return convert_to_grayscale(data, dtype)
    return data

.. _xdata-guide:

Extended Data Guide
===================

Many of the functions here are analogs to the similar NumPy function. A link is provided where possible.

Unless otherwise specified, all functions return a single extended data item.

.. note::
   The functions are still under development and the type signatures may change up until Nion Swift 1.0 is released.

Functions Changing Size or Type
-------------------------------

   >>> xdata = xd.astype(xdata, numpy.int32)

   >>> xdata_list = [xdata1, xdata2]
   >>> xdata = xd.concatenate(xdata_list)

   >>> xdata_list = [xdata1, xdata2]
   >>> xdata = xd.hstack(xdata_list)

   >>> xdata_list = [xdata1, xdata2]
   >>> xdata = xd.vstack(xdata_list)

   >>> xdata = xd.movaxis(xdata, axis_pos_in, axis_pos_out)

   >>> shape = (height, width)  # pixels, must be same number of total pixels
   >>> xdata = xd.reshape(xdata, shape)

   >>> data_range = (low_value, high_value)
   >>> xdata = xd.rescale(xdata, data_range)

   >>> xdata = xd.data_slice(xdata, [slice(0, 10, 1), slice(20, 40, 2)])

   >>> bounds = ((top, left), (height, width))  # fractional coordinates
   >>> xdata = xd.crop(xdata, bounds)

   >>> interval = (left_coord, right_coord)  # fractional coordinates
   >>> xdata = xd.crop_interval(xdata, interval)

   >>> xdata = xd.slice_sum(xdata, slice_center, slice_width)

   >>> position = (y, x)  # fractional coordinates
   >>> xdata = xd.pick(xdata, position)

   >>> xdata = xd.sum(xdata)

   >>> xdata = xd.sum_region(xdata, mask_xdata)  # mask data has same size as xdata, values of 1, 0

   >>> shape = (height, width)  # pixels
   >>> xdata = xd.resample_image(xdata, shape)

   >>> y_coords = xd.row(xdata.dimensional_shape)
   >>> x_coords = xd.column(xdata.dimensional_shape) + 0.5
   >>> xdata = xd.warp(xdata, (y_coords, x_coords))  # shift image by 1/2 pixel to left

Functions Generating Data
-------------------------

   >>> shape = (height, width)  # pixels, must be same number of total pixels
   >>> xdata = xd.column(shape)

   >>> shape = (height, width)  # pixels, must be same number of total pixels
   >>> xdata = xd.row(shape)

   >>> shape = (height, width)  # pixels, must be same number of total pixels
   >>> xdata = xd.radius(shape)

   >>> xdata = xd.gammapdf(xdata, a, mean, stddev)  # see SciPy documentation

   >>> xdata = xd.gammalogpdf(xdata, a, mean, stddev)  # see SciPy documentation

   >>> xdata = xd.gammacdf(xdata, a, mean, stddev)  # see SciPy documentation

   >>> xdata = xd.gammalogcdf(xdata, a, mean, stddev)  # see SciPy documentation

   >>> xdata = xd.normpdf(xdata, a, mean, stddev)  # see SciPy documentation

   >>> xdata = xd.normlogpdf(xdata, a, mean, stddev)  # see SciPy documentation

   >>> xdata = xd.normcdf(xdata, a, mean, stddev)  # see SciPy documentation

   >>> xdata = xd.normlogcdf(xdata, a, mean, stddev)  # see SciPy documentation

Functions for Complex Data
--------------------------

   >>> xdata = xd.absolute(xdata)

   >>> xdata = xd.angle(xdata)

   >>> xdata = xd.real(xdata)

   >>> xdata = xd.imag(xdata)

   >>> xdata = xd.conj(xdata)

   >>> xdata = xd.real_if_close(xdata, tol=100)

Functions for RGB Data
----------------------

   >>> xdata = xd.red(xdata)

   >>> xdata = xd.green(xdata)

   >>> xdata = xd.blue(xdata)

   >>> xdata = xd.alpha(xdata)

   >>> xdata = xd.luminance(xdata)

   >>> # input data can be integer or float. if integer, it is directly copied into resulting
   >>> # rgb data. if float, it is multiplied by 255 to form rgb data.
   >>> xdata = xd.rgb(red_xdata, green_xdata, blue_xdata)  # input data can be int or float

   >>> # input data can be integer or float. if integer, it is directly copied into resulting
   >>> # rgb data. if float, it is multiplied by 255 to form rgb data.
   >>> xdata = xd.rgba(red_xdata, green_xdata, blue_xdata, alpha_xdata)

Fourier Functions
-----------------

   >>> xdata = xd.fft(xdata)

   >>> xdata = xd.ifft(xdata)

   >>> xdata = xd.autocorrelate(xdata)

   >>> xdata = xd.crosscorrelate(xdata1, xdata2)

   >>> mask_xdata = data_item.mask_xdata
   >>> xdata = xd.fourier_mask(xdata, mask_xdata)  # handles FFT origin

Functions for Filters
---------------------

   >>> xdata = xd.sobel(xdata)

   >>> xdata = xd.laplace(xdata)

   >>> sigma = 2.5  # pixels
   >>> xdata = xd.gaussian_blur(xdata, sigma)

   >>> size = 3  # pixels
   >>> xdata = xd.median_filter(xdata, size)

   >>> size = 3  # pixels
   >>> xdata = xd.uniform_filter(xdata, size)

   >>> xdata = xd.transpose_flip(xdata, transpose=False, flip_v=True, flip_h=False)

Miscellaneous Functions
-----------------------

   >>> bins = 200
   >>> xdata = xd.histogram(xdata, bins)

   >>> vector = ((y1, x1), (y2, x2))  # fractional coordinates
   >>> integration_width = 20  # pixels
   >>> xdata = xd.line_profile(xdata, vector, integration_width)

   >>> xdata = xd.invert(xdata)

Useful Recipes for Data
-----------------------
Many ``xdata`` examples can be found by choosing menu items in the ``Processing`` menu and examining the resulting
computation code (use the computation inspector).

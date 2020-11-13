:orphan:

.. _scripting-guide:

Scripting Guide
===============
This guide explains many common tasks that you might want to do using scripting. It assumes you are familiar with
the Python programming language and with the basic functionality of Nion Swift.

For a developer overview, including a description of basic components, see :ref:`concepts-guide`.

For detailed class and method references, see :ref:`api-architecture`.

The examples below should work in both the Python Console inside of Nion Swift and by running external scripts via
``nionlib``.

If you are using ``nionlib`` you may need to add the following lines to your code. ::

   import numpy
   from nion.data import xdata_1_0 as xd
   api = nionlib.get_api('~1.0')

If you are developing scripts using instrumentation and acquisition, refer to `Nion Swift Instrumentation <https://nionswift-instrumentation.readthedocs.io/en/latest/>`_.

.. contents::

Opening the Python Console
--------------------------
Nion Swift includes an interactive Python Console for basic scripting. You can access a Python Console window using the
menu item ``File > Python Console`` (Ctrl-K on Windows/Linux; Cmd-K on macOS).

Once you have a Python Console, you can enter Python code in the interactive console. The Python Console automatically
configures the ``api`` variable for you. The ``api`` is the latest version. ::

   >>> window = api.application.document_windows[0]
   >>> len(window.library.data_items)
   126

Accessing a Specific Data Item
------------------------------
You may want to access a specific data item. To do this, you must ask Nion Swift to assign a variable representing the
data item.

You do this by clicking either on the display panel containing the data item or on the data item within the data panel list.

After you have selected the desired data item, press Ctrl-Shift-K (Windows/Linux) or Cmd-Shift-K (macOS). When you do this,
Nion Swift will show the variable in the title of the data item; it will also print the variable in any Python Console windows
that are open at the time. ::

   >>> r522 = api.library.get_data_item_by_uuid(uuid.UUID("c860b841-cc77-4e85-8dcc-aeea7da137a5"))
   >>> numpy.amin(r522.data)

The first line above will be added automatically when you press Ctrl/Cmd-Shift-K. Once it appears, you can type the second
line, substituting the actual r-variable for ``r522``.

Accessing the Target Data Item
------------------------------
In Nion Swift, when you select a display panel by clicking on its content and it becomes the target. The display panel
will show a blue outline when it the target. You can access the target data item from scripts. First, click on a display
panel that is showing an image. Now open a Python Console and type the following. ::

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> data_shape = data_item.data.shape
   >>> data_shape
   (2048, 2048)

Now click on a different display panel (or drag a new Data Item into the current display panel). ::

   >>> data_item = window.target_data_item
   >>> data_shape = data_item.data.shape
   >>> data_shape
   (512, 128)

Changing Data in a Data Item
----------------------------
You can use scripting to overwrite the data in a data item. This example assumes that you have an existing ``data_item``
that you wish to overwrite and stores new ``numpy`` data into it. ::

   >>> data_item.data = numpy.random.randn(16, 32)

You may want to change just part of the data in a data item without rewriting the entire data. ::

   >>> with api.library.data_ref_for_data_item(data_item) as data_ref:
   ...     data_ref[10:20, 10:20] = numpy.random.randn(10, 10)
   ...

Notice that you are assigning new data to a slice of the ``data_ref``, not assigning to ``data`` as in the previous example.

.. warning::
   From scripts, there is no protection against changing data. Changing data will permanently overwrite any old data.
   We recommend using caution with scripts that write to the target data item since the user may inadvertently choose
   a data item as the target which contains data that cannot be recovered.

Creating and Displaying a New Data Item
---------------------------------------
You can create a new data item and display it in an empty display panel. This example creates a new ``numpy`` array,
creates a new data item using the data, and displays it in the current workspace. Before running this script, if there
are no empty display panels, you can right/control click on an existing display panel and choose the menu item ``None``
to provide space in which the new data item can be placed.

The quick form (available in the console):

   >>> data = numpy.random.randn(16, 32)
   >>> show(data)

The most general form:

   >>> window = api.application.document_windows[0]
   >>> data = numpy.random.randn(16, 32)
   >>> data_item = api.library.create_data_item_from_data(data)
   >>> display_panel = window.display_data_item(data_item)

.. note::
   If there is no empty display panel, the data item will not be displayed immediately and ``display_data_item`` will
   return ``None``.

Creating a Calibrated Data Item
-------------------------------
You can set a data item's calibration. The API provides a ``create_calibration`` method where the offset, scale, and unit
name are specified. ::

   >>> window = api.application.document_windows[0]
   >>> data = numpy.random.randn(16, 32)
   >>> data_item = api.library.create_data_item_from_data(data)
   >>> intensity_calibration = api.create_calibration(offset=0.0, scale=4.0, units='counts')
   >>> dimensional_calibration_0 = api.create_calibration(0.0, 10, 'µm')
   >>> dimensional_calibration_1 = api.create_calibration(0.0, 19, 'µm')
   >>> dimensional_calibrations = [dimensional_calibration_0, dimensional_calibration_1]
   >>> data_item.set_intensity_calibration(intensity_calibration)
   >>> data_item.set_dimensional_calibrations(dimensional_calibrations)
   >>> show(data_item)

The calibration objects transform their values like this: ``x' = x * scale + offset``.

Adding Two Data Items
---------------------
Assuming you have two data items of the same size, you can add them together and display the result by following these
steps.

#. Click on each data item you want to add and assign an r-variable by pressing Ctrl/Cmd-Shift-K on each one. The r-variable
   will appear in the title of the data item, such as "My Data Item (r522)". ``r522`` is the r-variable.
#. Make sure you have an empty display panel by right/control clicking on one of the display panels and choose ``None`` from
   the menu.
#. Open a script window (Ctrl/Cmd-K).
#. Write the follow script, substituting the r-variables assigned in step #1 for ``r001`` and ``r002``. ::

   >>> window = api.application.document_windows[0]
   >>> data = r001.data + r002.data
   >>> data_item = api.library.create_data_item_from_data(data)
   >>> show(data_item)

The new added data should be displayed in the display panel you freed up in step 2 or another free display panel.

.. note::
   Nion Swift has the ability to configure *live* computations. In this case, though, the computation is not *live*. A
   description of how to set up a *live* computation will be provided soon!

Display Panels
--------------
The workspace area in Nion Swift can be split into multiple display panels. Each display panel has a two letter code that
allows you to access it directly from scripts. You can both get and set the data item in a specific display panel. ::

   >>> display_panel_id = “hy”  # this is the 2 letters in light gray appearing at the top-left of a display panel
   >>> window = api.application.document_windows[0]
   >>> display_panel = window.get_display_panel_by_id(display_panel_id)
   >>> display_panel.data_item.shape
   (480, 640)
   >>> data_item = api.library.create_data_item_from_data(numpy.random.randn(30, 40))
   >>> display_panel.set_data_item(data_item)
   >>> display_panel.data_item.shape
   (30, 40)

Working with Extended Data
--------------------------
In the code snippets above, data items have been treated as having ``numpy`` data. However, Nion Swift actually stores data
in :dfn:`extended data` structures (also called :dfn:`data and metadata` and sometimes abbreviated as :dfn:`xdata`).

Extended data combines the following components:
   * The ``numpy`` compatible data array.
   * Calibrations (intensity calibration and dimensional calibration)
   * Description of dimensions (sequence, collection, datum)
   * Timestamps
   * *Provenance/history (future feature)*

   >>> window = api.application.document_windows[0]
   >>> data = numpy.random.randn(16, 32)
   >>> intensity_calibration = api.create_calibration(offset=0.0, scale=4.0, units='counts')
   >>> dimensional_calibration_0 = api.create_calibration(0.0, 10, 'µm')
   >>> dimensional_calibration_1 = api.create_calibration(0.0, 19, 'µm')
   >>> dimensional_calibrations = [dimensional_calibration_0, dimensional_calibration_1]
   >>> xdata = api.create_data_and_metadata(data, intensity_calibration=intensity_calibration,
   ...     dimensional_calibrations=dimensional_calibrations)
   ...
   >>> data_item = api.library.create_data_item_from_data_and_metadata(xdata)

Extended data also describes the usage of each dimension. Extended data can represent a sequence of data, a collection of
data, and data with one or more datum dimensions. Extended data in Nion Swift is always organized with the sequence index (if
any) in the first index, followed by the collection indexes, followed by the datum indexes.

For instance, a regular 2d visual image would be described as having two datum dimensions.

A scanned image might be represented as having 2 collection dimensions and only a scalar datum dimension or as having two
datum dimensions.

A movie would be be described as being a sequence of two datum dimensions.

A spectrum image would be described as having two collection dimensions and a single datum dimension.

   >>> spectrum_data = numpy.random.randn(2048)
   >>> spectrum_data_descriptor = api.create_data_descriptor(is_sequence=False, collection_dimension_count=0, datum_dimension_count=1)
   >>> spectrum_xdata = api.create_data_and_metadata(data, data_descriptor=spectrum_data_descriptor)

   >>> image_data = numpy.random.randn(480, 640)
   >>> image_data_descriptor = api.create_data_descriptor(is_sequence=False, collection_dimension_count=0, datum_dimension_count=2)
   >>> image_xdata = api.create_data_and_metadata(data, data_descriptor=image_data_descriptor)

   >>> movie_data = numpy.random.randn(1000, 480, 640)
   >>> movie_data_descriptor = api.create_data_descriptor(is_sequence=True, collection_dimension_count=0, datum_dimension_count=2)
   >>> movie_xdata = api.create_data_and_metadata(data, data_descriptor=movie_data_descriptor)

   >>> line_spectrum_data = numpy.random.randn(500, 2048)
   >>> line_spectrum_data_descriptor = api.create_data_descriptor(is_sequence=False, collection_dimension_count=1, datum_dimension_count=1)
   >>> line_spectrum_xdata = api.create_data_and_metadata(data, data_descriptor=line_spectrum_data_descriptor)

   >>> line_2d_data = numpy.random.randn(500, 1024, 1024)
   >>> line_2d_data_descriptor = api.create_data_descriptor(is_sequence=False, collection_dimension_count=1, datum_dimension_count=2)
   >>> line_2d_xdata = api.create_data_and_metadata(data, data_descriptor=line_2d_data_descriptor)

   >>> si_data = numpy.random.randn(512, 512, 2048)
   >>> si_data_descriptor = api.create_data_descriptor(is_sequence=False, collection_dimension_count=2, datum_dimension_count=1)
   >>> si_xdata = api.create_data_and_metadata(data, data_descriptor=si_data_descriptor)

   >>> data_4d = numpy.random.randn(64, 64, 1024, 1024)
   >>> data_4d_data_descriptor = api.create_data_descriptor(is_sequence=False, collection_dimension_count=2, datum_dimension_count=2)
   >>> data_4d_xdata = api.create_data_and_metadata(data, data_descriptor=data_4d_data_descriptor)

You can get extended from a data item and query its contents with many useful methods. Here are some examples.

   >>> xdata = window.target_data_item.xdata
   >>> xdata.dimensional_shape
   (480, 640)
   >>> xdata.data_dtype
   dtype('float64')
   >>> xdata.is_sequence
   False
   >>> xdata.collection_dimension_count
   0
   >>> xdata.datum_dimension_count
   2
   >>> xdata.intensity_calibration
   x 1.0 + None
   >>> xdata.dimensional_calibrations
   [x 1.0 + None, x 1.0 + None]
   >>> r650.xdata.timestamp
   datetime.datetime(2016, 5, 26, 17, 11, 41, 918215)

Computations with Extended Data
-------------------------------
You can do all sorts of computations with extended data. To begin with, you can use basic Python operators.

   >>> xdata = xdata1 + xdata2 * xdata3
   >>> xdata = -xdata4

You can also import the ``xdata`` library and use the functions in that library. These functions will handle the data
descriptions and calibrations properly.

   >>> xdata = xd.fft(xdata1)
   >>> xdata = xd.gaussian_blur(xdata2, 2.0)
   >>> xdata = xd.pick(xdata3, (2, 3))
   >>> xdata = xd.column(xdata1.collection_dimension_shape)

For a description of the full ``xdata`` library, see :ref:`xdata-guide`.

For a quick description of the available methods or a specific method:

   >>> help(xd)
   >>> help(xd.fft)

Extracting Display Data from Data Items
---------------------------------------
In addition to the data that a data item stores, you can also access the secondary display data.

..
   :dfn:`Reduced data` refers to the original data sliced down to either 2d or 1d data. It has the data type of the
   original data.

:dfn:`Display data` refers to the original data sliced down to either 2d or 1d data and then converted to a scalar
or RGB data type. For instance, complex 128 data will have the complex display attribute applied and will result in
float 64 data.

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> data_item.xdata.is_sequence
   True
   >>> xdata.datum_dimension_count
   2
   >>> data_item.xdata.dimensional_shape
   (60, 1024, 1024)
   >>> data_item.xdata.data_dtype
   dtype('complex128')
   >>> data_item.display_xdata.is_sequence
   False
   >>> data_item.display_xdata.dimensional_shape
   (1024, 1024)
   >>> data_item.display_xdata.data_dtype
   dtype('float64')

Display data can be useful when you want to operate on the data that is displayed. For instance, a line profile
works with the display data rather than the original data.

Using Data Item Calibrations
----------------------------
There are a few convenience functions for accessing the calibrations of the data item. The ``intensity_calibration`` and
``dimensional_calibrations`` properties both return copies of the data item calibrations.

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> intensity_calibration = data_item.intensity_calibration
   >>> intensity_calibration.units
   'counts'
   >>> calibration_y = data_item.dimensional_calibrations[0]
   >>> calibration_x = data_item.dimensional_calibrations[1]
   >>> calibration_y.scale
   0.11
   >>> calibration_y.units
   'nm'

You can set the calibrations of the data item too.

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> intensity_calibration = data_item.intensity_calibration
   >>> intensity_calibration.units = 'cd'  # candela
   >>> data_item.set_intensity_calibration(intensity_calibration)
   >>> dimensional_calibrations = data_item.dimensional_calibrations
   >>> dimensional_calibrations[0].scale = 0.12
   >>> data_item.set_dimensional_calibrations(dimensional_calibrations)

You can convert between calibrated and uncalibrated pixels and strings using calibration objects:

   >>> c = Calibration.Calibration(3, 5, "nm")
   >>> c.convert_to_calibrated_value(20)
   103.0
   >>> c.convert_to_calibrated_size(20)
   100.0
   >>> c.convert_to_calibrated_value_str(20)
   '103 nm'
   >>> c.convert_to_calibrated_size_str(20)
   '100 nm'
   >>> c.convert_from_calibrated_value(90)
   17.4
   >>> c.convert_from_calibrated_size(10)
   2.0

.. note::
   The convenience functions for accessing data item calibrations work by setting the calibrations on the extended
   data associated with the data item. Storing new extended data will also change the calibrations. This can have
   unexpected consequences. For instance, calibrations can be overwritten if a live computation is executed. If you
   are using the API to perform a custom computation, and using these convenience functions, place them *after* the
   code that assigns new ``data`` or ``xdata`` to the target data item.

Using Data Item Created and Modified Timestamps
-----------------------------------------------
You can read the ``created`` and ``modified`` properties to get the created and modified ``datetime`` objects,
specified in UTC. You can also read the ``timestamp`` property of extended data.

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> data_item.modified.isoformat()
   '2017-02-09T05:10:18.427999'
   >>> data_item.created.isoformat()
   '2017-02-08T17:17:51.795207'
   >>> data_item.xdata.timestamp.isoformat()
   '2017-02-09T04:19:12.711283'

The ``created`` datetime is never updated. The ``modified`` datetime is updated whenever the data item or data changes.
The ``xdata.timestamp`` is updated whenever the data changes.

Finding Sources and Dependents of Data Items
--------------------------------------------
The library keeps track of high level connections between data items. For instance, if data item A has a crop applied
to it and generates data item B, then A is said to be a *source* of B and reciprocally B is said to be a *dependent* of
A.

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> dependents = api.library.get_dependent_data_items(data_item)
   >>> sources = api.library.get_source_data_items(dependents[0])
   >>> data_item is sources[0]
   True

Uniquely Identifying Data Items
-------------------------------
Persistent objects in the library have a unique ``uuid`` identifier which is persistent for the lifetime of the object,
even if exiting and relaunching Swift. The ``uuid`` uniquely identifies that object.

   >>> window = api.application.document_windows[0]
   >>> data_item = window.target_data_item
   >>> data_item.uuid
   UUID('646bc502-6e8e-4e9f-8ac0-30c124822df3')

.. note::
   The same object with the same ``uuid`` can appear in two different libraries with different properties and data
   since the user may explicitly copy items between libraries. The ``uuid`` is unique within a single library,
   however.

Managing Session Metadata
-------------------------
Metadata about the current session is stored with the library object and can be edited in the UI using the Session
panel. You can access the metadata using Python:

   >>> api.library.get_library_value("stem.session.instrument")
   Nion UltraSTEM 200keV
   >>> api.library.set_library_value("stem.session.microscopist", "Manfred Von Ardenne")
   >>> api.library.delete_library_value("stem.session.task")
   >>> api.library.has_library_value("stem.session.task")
   False

====================================== ====
**Session Description**
====================================== ====
``stem.session.instrument``            string
``stem.session.detector``              string
``stem.session.microscopist``          string
``stem.session.sample``                string
``stem.session.sample_area``           string
``stem.session.sample_source``         string
``stem.session.sample_formula``        string
``stem.session.site``                  string
``stem.session.task``                  string
====================================== ====

Reading and Writing Data Item Metadata
--------------------------------------
You can also access metadata associated with the data item.

   >>> data_item.set_metadata_value("stem.session.site", "Hogwarts School of Witchcraft and Wizardry")
   >>> data_item.set_metadata_value("stem.session.microscopist", "Albus Dumbledore")
   >>> data_item.get_metadata_value("stem.high_tension_v")
   120000
   >>> data_item.delete_metadata_value("stem.session.task")
   >>> data_item.has_metadata_value("stem.session.task")
   False

The tables below show possible metadata keys and their data types.

You may also need to store metadata not defined by the keys below. You can do that using the ``metadata`` property.

   >>> metadata_dict = data_item.metadata
   >>> metadata_dict.setdefault("astrology", dict())["moon-phase"] = "gibbous"
   >>> data_item.set_metadata(metadata_dict)

Any value stored in the ``metadata`` ``dict`` must be convertible to ``json``, e.g. ``json.dumps(metadata_dict)`` must
succeed.

Using the keys has the advantage that when the data item is exported to another file format (such as TIFF), the keys can
be used to *flatten* the ``metadata`` ``dict`` into well defined fields. If you use custom fields, they will only be
available as a general ``metadata`` ``json`` string.

In addition, using the keys improves interoperability between applications.

If a key or set of keys should be added, Nion maintains a registry of keys. Please contact us to discuss.

====================================== ====
**Session Description**
====================================== ====
``stem.session.instrument``            string
``stem.session.detector``              string
``stem.session.microscopist``          string
``stem.session.sample``                string
``stem.session.sample_area``           string
``stem.session.sample_source``         string
``stem.session.sample_formula``        string
``stem.session.site``                  string
``stem.session.task``                  string
====================================== ====

|

====================================== ====
**STEM Values**
====================================== ====
``stem.high_tension_v``                integer
``stem.gun_type``                      string
``stem.convergence_angle_rad``         real
``stem.collection_angle_rad``          real
``stem.probe_size_m2``                 real
``stem.beam_current_a``                real
``stem.defocus_m``                     real
====================================== ====

|

====================================== ====
**STEM Data**
====================================== ====
``stem.signal_type``                   string (EELS, EDS, CL, Ronchigram, HAADF, MAADF, BF)
====================================== ====

|

====================================== ====
**EELS Values**
====================================== ====
``stem.eels.spectrum_type``            string
``stem.eels.resolution_eV``            real
``stem.eels.is_monochromated``         boolean
====================================== ====

|

====================================== ====
**Hardware Values**
====================================== ====
``stem.hardware_source.id``            string
``stem.hardware_source.name``          string
====================================== ====

|

====================================== ===========  =
**Camera Values**
====================================== ===========  =
``stem.camera.binning``                integer
``stem.camera.channel_id``             string
``stem.camera.channel_index``          integer
``stem.camera.channel_name``           string
``stem.camera.exposure_s``             real
``stem.camera.frame_index``            integer      high level index. reset when played.
``stem.camera.frame_number``           integer      low level index. reset at application startup.
``stem.camera.valid_rows``             integer
``stem.camera.detector_current``       real
====================================== ===========  =

|

====================================== ====
**Scan Values**
====================================== ====
``stem.scan.center_x_nm``              real
``stem.scan.center_y_nm``              real
``stem.scan.channel_id``               string
``stem.scan.channel_index``            integer
``stem.scan.channel_name``             string
``stem.scan.frame_time_s``             real
``stem.scan.fov_nm``                   real
``stem.scan.frame_index``              integer
``stem.scan.pixel_time_us``            real
``stem.scan.rotation_rad``             real
``stem.scan.scan_id``                  string
``stem.scan.valid_rows``               integer
====================================== ====

Copying a Data Item
-------------------
You may want to copy an existing data item and be able to modify it without affecting the original data item.

There are two ways to copy a data item. The *copy* technique copies the data item and maintains any live computation
attached to the data item. The *snapshot* technique copies the data item but does *not* maintain any live computation.

Both copy operations copy the extended data, calibrations, metadata, display, and graphics. Neither operation copies
data items dependent the one being copied.

   >>> data = numpy.random.randn(16, 32)
   >>> data_item = api.library.create_data_item_from_data(data)
   >>> data_item_copy = api.library.copy_data_item(data_item)
   >>> data_item_snap = api.library.snapshot_data_item(data_item)
   >>> numpy.array_equal(data_item_copy.data, data)
   True
   >>> numpy.array_equal(data_item_snap.data, data)
   True

It is also possible to make a new data item by copying only the extended data. This copies the extended data,
calibrations, and metadata; but not session data, display, graphics or other items that are associated with the
data item but not the extended data.

   >>> data_item = api.library.create_data_item_from_data(numpy.random.randn(2, 2))
   >>> data_item_copy = api.library.create_data_item_from_data_and_metadata(data_item.xdata)
   >>> numpy.array_equal(data_item.data, data_item_copy.data)
   True
   >>> data_item.metadata == data_item_copy.metadata
   True

Copying Metadata from One Data Item to Another
----------------------------------------------
You can explicitly copy metadata from one data item to another. This is not recommended to use in production code since
it will most likely break in future versions.

   >>> data_item = api.library.create_data_item_from_data(numpy.random.randn(2, 2))
   >>> data_item_copy = api.library.create_data_item_from_data(numpy.random.randn(2, 2))
   >>> data_item_copy.set_intensity_calibration(data_item.intensity_calibration)
   >>> data_item_copy.set_dimensional_calibrations(data_item.dimensional_calibrations)
   >>> data_item_copy.set_metadata(data_item.metadata)
   >>> session_keys = ['stem.session.instrument', 'stem.session.microscopist', 'stem.session.sample', \
   ...   'stem.session.sample_area', 'stem.session.site', 'stem.session.task']
   ...
   >>> for session_key in session_keys:
   ...   if data_item.has_metadata_value(session_key):
   ...     data_item_copy.set_metadata_value(session_key, data_item.get_metadata_value(session_key))
   ...

Storing Persistent Settings Files
---------------------------------
You can store configuration files in a location provided by the API.

.. note::
  By convention, you should log the settings file location so that the user has direct access to them.

.. note::
  By convention, the settings files are stored in JSON format.

The following code shows how to access the configuration location::

    >>> config_file = api.application.configuration_location / pathlib.Path("my_settings.json")
    >>> logging.info("My plug-in configuration file: " + str(config_file))

..
    Configuring Live Operations
    ---------------------------
    * cropping
    * parameters
    * multiple inputs (cross correlation)
    * examine existing live operation (sources, regions, etc.)
    * filtering (fourier filter)
    * masking (pick)
    * aggregate (multiple-add)
    * multiple outputs (return a list)
    * input parameters may need to specify coordinate system

    # what about a 'computation_description' and user is allowed to build it up: add(mult(a,b),c)

    # crop can be specified with graphic or hard coded value (which will create a graphic) or default

    # filter is either on/off

    # mask is either on/off

    # computations that take a crop should have a UI in the inspector to enabled/disable

    computed_data_item = api.library.create_computed_data_item("fft", [{"data_item": data_item, "crop_graphic": crop_graphic])

    computed_data_item = api.library.create_computed_data_item("uniform-filter", [{"data_item": data_item}])

    computed_data_item = api.library.create_computed_data_item("uniform-filter", [{"data_item": data_item}])

    computed_data_item = api.library.create_computed_data_item("transpose-flip", [{"data_item": data_item}])

    computed_data_item = api.library.create_computed_data_item("resample", [{"data_item": data_item, "size": (256, 256)}])

    computed_data_item = api.library.create_computed_data_item("histogram", [{"data_item": data_item, "bins": 128}])

    computed_data_item = api.library.create_computed_data_item("invert", [{"data_item": data_item}])

    computed_data_item = api.library.create_computed_data_item("convert-to-scalar", [{"data_item": data_item}])

    computed_data_item = api.library.create_computed_data_item("crop", [{"data_item": data_item, "crop": (0.5, 0.6), (0.2, 0.3)}])

    computed_data_item = api.library.create_computed_data_item("sum", [{"data_item": data_item}])

    computed_data_item = api.library.create_computed_data_item("slice", [{"data_item": data_item}])

    computed_data_item = api.library.create_computed_data_item("pick-point", [{"data_item": data_item, "graphic": [pick_point_graphic]}])

    computed_data_item = api.library.create_computed_data_item("pick-mask-sum", [{"data_item": data_item, "mask_id": None}])

    computed_data_item = api.library.create_computed_data_item("line-profile", [{"data_item": data_item, "graphic": [line_profile_graphic]}])
    computed_data_item = api.library.create_computed_data_item("line-profile", [{"data_item": data_item, "line": ((0.2, 0.2), (0.4, 0.4)), "width": 18}])

    computed_data_item = api.library.create_computed_data_item("filter", [{"data_item": data_item, "filter_id": None}])

    Logging Output
    --------------
    Immediate, persistent, where to display a statistic in the UI?

    Import and Exporting Data
    -------------------------
    Exporting to various file types, sub regions too.

    Applying Processing to a Sequence of Data Items
    -----------------------------------------------

    Align Two Images
    ----------------

    Align a Stack of Images
    -----------------------

    Adding Functions to the Computation Space
    -----------------------------------------
    * add a library to Python that functions on xdata
    * import it into computations, use it

    Integrating a Third Party Python Library
    ----------------------------------------

    Using the Fourier Mask
    ----------------------
    * create a fourier mask object and assign a filter_id
    * build a complex mask
    * set up a filter

    Using a Graphics Mask
    ---------------------
    * create a mask object and assign a mask id

    Using Sets of Graphics
    ----------------------
    * create a graphic set and assign a group_id

    Using the Crop Area
    -------------------
    * crop_id?

    Creating Graphics
    -----------------

    Manipulating the Workspace
    --------------------------
    N/A

    Layout
    ++++++
    N/A

    Display Panels
    ++++++++++++++

    I/O Handler
    -----------
    N/A

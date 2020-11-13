:orphan:

.. _hardware-guide:

Hardware Guide
==============

There are two API's available for hardware control: high level functions that are device independent are described in
this document and lower level functions that are more device specific.

If you need lower level functions that are device specific, refer to `Nion Swift Instrumentation <https://nionswift-instrumentation.readthedocs.io/en/latest/>`_.

Instrument Control
------------------
You can access and control instruments, devices, and hardware sources via the instrument control API.

Getting an Instrument Object
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
To do instrument control, you will need to get a versioned ``instrument`` object from the ``api`` object using an
``instrument_id`` (see :ref:`hardware-source-identifiers`). ::

    autostem = api.get_instrument_by_id("autostem", version="1.0")

Instrument Properties
^^^^^^^^^^^^^^^^^^^^^
Once you have an ``instrument`` object, you can set and get properties on the instrument. ::

    if autostem.get_property_as_bool("ShowTuningImages"):
        show_data()

Properties are typed and the following types are supported:

    - float
    - int
    - str
    - bool
    - float_point

You can also set properties on an instrument. ::

    superscan.set_property_as_float_point("probe_position", (0.5, 0.5))

For more information about these methods, see :py:class:`nion.swift.Facade.Instrument`.

Instrument Controls
^^^^^^^^^^^^^^^^^^^
A set of methods to access a special subset of properties called *controls* is also available.

Controls are special properties that are always represented as float values and may represent combinations of other
controls. Their methods have special features which allow more precise setting within the network of controls.

Autostem controls are characterized as having a internal "local" value added to weighted sum of values from zero or more
input controls. Changing the value of an input control can change the output value of other controls.

Setting Output Values
+++++++++++++++++++++

You can set values on controls in such a way as to allow changes to propogate to dependent controls or not.

To set the output value of a control, use the ``set_control`` method with no options. ::

    autostem.set_control_output("d3x", d3x_value)

Confirmation
++++++++++++

When setting the absolute output value of a control, you can confirm the value gets set by passing an options dict with
a ``value_type`` key of ``confirm``. ::

    autostem.set_control_output("d3x", 0.0, options={'confirm': True})

You can also add options for tolerance factor when confirming. The tolerance factor default is 1.0 and should be thought
of as the nominal tolerance for that control. Passing a higher tolerance factor (for example 1.5) will increase the
permitted error margin and passing lower tolerance factor (for example 0.5) will decrease the permitted error margin
and consequently make a timeout more likely. The tolerance factor value 0.0 is a special value which removes all
checking and only waits for any change at all and then returns.

To set d3x to within 2% of its nominal target value ::

    autostem.set_control_output("d3x", 0.0, options={'confirm': True, 'confirm_tolerance_factor': 1.02})

You can also add timeout options when confirming. The default timeout is 16 seconds. ::

    autostem.set_control_output("d3x", 0.0, options={'confirm': True, 'confirm_timeout': 16.0})

If the timeout occurs before the value is confirmed, a ``TimeoutException`` will be raised.

Local Values
++++++++++++

You can set the *local* value of a control by passing an options dict with a ``value_type`` key of ``local``. ::

    autostem.set_control_output("d3x", 0.0, options={'value_type': 'local'})

Delta Values
++++++++++++

You can change a control by a delta value by passing an options dict with a ``value_type`` key of ``delta``. ::

    autostem.set_control_output("d3x", d3x_delta, options={'value_type': 'delta'})

Inform, or Keeping Dependent Outputs Constant
+++++++++++++++++++++++++++++++++++++++++++++

Finally, you can adjust a control in such a way that the output values of dependent controls stay constant. This is
useful during setup when you want to change the displayed value without actually changing the dependent outputs. You do
this by passing an options dict with a ``inform`` key of True. This parameter is named ``inform`` for historical
reasons but can also be thought of as *keep dependent outputs constant*. ::

    autostem.set_control_output("d3x", d3x_value, options={'inform': True})

Control State
+++++++++++++

Finally, you can query the state of a control to see if it exists or to see its current state. The only defined
return values at the moment are None and 'undefined' state. ::

    if autostem.get_control_state("dqt") is not None:
        run_dqt_adjustment()

For more information about these methods, see :py:class:`nion.swift.Facade.Instrument`.

Data Acquisition
----------------
In addition to instrument control, you can also control data acquisition on hardware sources.

Introduction
^^^^^^^^^^^^
Acquisition can be started in **View** or **Record** mode. **View** mode is an ongoing acquisition whereas **Record**
mode is a single acquisition.

Acquisition is started with frame parameters that specify the readout configuration to be used. You can configure
specific frame parameters or use one of the user defined profiles available in the user interface.

In **View** mode, you can specify the initial frame parameters, but other scripts may be able to change the frame
parameters during acquisition. The acquisition API doesn't attempt to prevent this.

In **Record** mode, since you are acquiring a single frame, your frame parameters are guaranteed to be used.  **Record**
mode can be used while **View** mode is already in progress. When the **Record** is finished, the **View** will
continue.

Acquisition code in extensions should be run on threads to prevent locking the user interface. Acquisition code in
scripts will always run on threads due to the nature of scripts.

Getting a Hardware Source Object
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
To do acquisition, you will need to get a versioned ``hardware_source`` from the :samp:`api` object using a
:samp:`hardware_source_id` (see :ref:`hardware-source-identifiers`). ::

    camera = api.get_hardware_source_by_id("ronchigram", version="1.0")

Frame Parameters Overview
^^^^^^^^^^^^^^^^^^^^^^^^^
You will first configure the :samp:`frame_parameters` for the hardware source. There are several ways to do this.

Frame parameters are specific to the hardware source. The easiest way to get valid frame parameters is to ask the
:samp:`camera` for the default frame parameters. ::

    frame_parameters = camera.get_default_frame_parameters()

Next you can modify the :samp:`frame_parameters` (this is hardware source specific). ::

    frame_parameters["binning"] = 4
    frame_parameters["exposure_ms"] = 200

You can also get the frame parameters for one of the acquisition profiles configured by the user. ::

    frame_parameters = camera.get_frame_parameters_for_profile_by_index(1)

You can get and set the currently selected acquisition profile in the user interface using the ``profile_index``
property. Setting the selected acquisition profile is discouraged since it can be confusing to the user if their
selected profile suddenly changes. ::

    old_profile_index = camera.profile_index
    camera.profile_index = new_profile_index

You can also update the frame parameters associated with a profile. Again, use this ability with caution since it can be
confusing to the user  to lose their settings. ::

    camera.set_frame_parameters_for_profile_by_index(1, frame_parameters)

Querying Acquisition State
^^^^^^^^^^^^^^^^^^^^^^^^^^
Hardware sources can be in one of several state: idle, viewing/playing, or recording. ::

    is_playing = camera.is_playing
    is_recording = camera.is_recording

.. note:: Recording can occur *during* viewing, in which case the camera can be viewing/playing and recording simultaneously.

Acquisition Frame Parameters
^^^^^^^^^^^^^^^^^^^^^^^^^^^^
Hardware sources have frame parameters associated with both view/play and record modes. You can query and set those
frame parameters using several methods. Setting the frame parameters will apply the frame parameters to soonest possible
frame.

To query and set the frame parameters for view/play mode::

    frame_parameters = camera.get_frame_parameters()
    camera.set_frame_parameters(frame_parameters)

To query and set the frame parameters for record mode::

    frame_parameters = camera.get_record_frame_parameters()
    camera.set_record_frame_parameters(frame_parameters)

Controlling Acquisition State
^^^^^^^^^^^^^^^^^^^^^^^^^^^^^
You can control the acquisition view/play state using these methods::

    camera.start_playing(frame_parameters, channels_enabled)
    camera.stop_playing()
    camera.abort_playing()

Passing ``frame_parameters`` and ``channels_enabled`` are optional. Passing ``None`` will use the existing frame
parameters and enabled channels. Not all hardware sources support channels.

Stopping will finish the current frame. Aborting will immediately stop acquisition, potentially mid-frame.

You can control acquisition record state using these methods::

    camera.start_recording(frame_parameters, channels_enabled)
    camera.abort_recording()

Again, ``frame_parameters`` and ``channels_enabled`` are optional.

Recording occurs on a frame by frame basis, so there is no need to stop recording as it will always finish at the end of
a frame. Calling ``abort_recording`` will immediately stop recording, if desired.

Recording in this way will generate a new data item.

.. note:: Recording can occur *during* view/play. How the view is stopped (stop or abort) to begin recording is
    specific to the camera implementation. After recording, the view will resume with current frame parameters.

Acquiring Data
^^^^^^^^^^^^^^
You can acquire data during a view. Acquired data is returned as a list of ``DataAndMetadata`` objects.

There are a few techniques to grab data:

    - ``grab_next_to_finish`` is used to grab data from view/play mode when frame parameters and other state related
      to the hardware source is already known.

    - ``grab_next_to_start`` is used to grab data from view/play mode when you need to ensure that the next frame
      represents data with new frame parameters or other state related to the hardware source.

    - ``record`` is used to grab data in record mode.

You can pass frame parameters and enabled channels to ``grab_next_to_start`` and ``record`` methods. There is no need
to pass them to ``grab_next_to_finish`` since that method will be grabbing data from acquisition that is already in
progress.

Only a single record can occur at once but there is no defined coordination technique to avoid multiple records from
occuring simultaneously. If two records are requested simultaneously, the latest one will override.

All three methods will start either view/play mode or record mode if not already started.

Some example code to demonstate calling these methods. ::

    data_and_metadata_list = camera.grab_next_to_finish(timeout)
    data_and_metadata = data_and_metadata_list[0]

    data_and_metadata_list = camera.grab_next_to_start(frame_parameters, channels_enabled, timeout)
    data_and_metadata = data_and_metadata_list[0]

    data_and_metadata_list = hardware_source_api.record(frame_parameters, channels_enabled, timeout)
    data_and_metadata = data_and_metadata_list[0]

The ``frame_parameters``, ``channels_enabled``, and ``timeout`` parameters are all optional.

For more information about these methods, see :py:class:`nion.swift.Facade.HardwareSource`.

Record Tasks
^^^^^^^^^^^^
For a *Record* data acquisition, you can also use an acquisition task. ::

    with contextlib.closing(hardware_source_api.create_record_task(frame_parameters)) as record_task:
        do_concurrent_task()
        data_and_metadata_list = record_task.grab()

The acquisition is started as soon as the **Record** task is created. The :samp:`grab` method will wait until the
recording is done and then return.

Record tasks are useful to do concurrent work while the recording is taking place.

For more information about these methods, see :py:class:`nion.swift.Facade.HardwareSource`.

.. _hardware-source-identifiers:

Hardware Configuration
^^^^^^^^^^^^^^^^^^^^^^
With a ``hardware_source`` object, you can set and get properties on the instrument. ::

    if camera.get_property_as_bool("use_gain"):
        do_gain_image_processing()

Properties are typed and the following types are supported:

    - float
    - int
    - str
    - bool
    - float_point

You can also set properties on a hardware source. ::

    superscan.set_property_as_float_point("probe_position", (0.5, 0.5))

For more information about these methods, see :py:class:`nion.swift.Facade.Instrument`.

Hardware Source Identifiers
^^^^^^^^^^^^^^^^^^^^^^^^^^^
Instruments and hardware sources are identified by id's. Id's are divided into direct id's and aliases. Aliases are
configurable in .ini files. For instance, the direct hardware might have a ``hardware_source_id`` of ``nionccd1010`` but
there might be an alias ``ronchigram`` which points to the ``nionccd1010``. It is recommended to make an alias for each
application that you write, making it easy for users to configure what camera to use for your application.

..
    Camera Hardware Source
    ----------------------
    N/A

    Scan Hardware Source
    --------------------
    N/A

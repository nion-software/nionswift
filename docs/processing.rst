:orphan:

.. _processing:

Processing and Analysis
=======================
.. explanation: Background information and conceptual discussions

You can apply processing and analysis to items in your project. An example of processing may be to apply an FFT operation to an image. An example of analysis may be to measure the intensity of a line profile.

Many processing and analysis menu items result in a live computation. A live computation automatically updates the outputs when either parameters change or the source data changes. A live computation is live even after closing and reloading the project.

Other processing functions are single commands, meaning that the output is computed once and the resulting data item or other output is added to the project and no live computation is created.

A live computation takes inputs and produces outputs. It also watches for changes to its inputs and updates it outputs whenever the inputs change.

Inputs can be data items, display items, and graphics. Outputs can be data items and graphics.

Live computations are useful during acquisition where you can perform live processing on incoming data.

Live computations are also useful for non-acquisition processing and analysis because they allow you to vary parameters and observe how the outputs change.

Live Computations
-----------------
.. how-to: Concise instructions for accomplishing specific tasks.

To apply processing and analysis to items in your project, you should first select the inputs you want to process or analyze.

In many cases, you can select the input by clicking on a display panel to give it keyboard focus and then choosing one of the processing menu items.

Most processing functions are available in the :menuselection:`Processing` menu. Plug-in packages may add processing functions to other menus, too.

Once you have selected the input data item(s), you can choose the processing function from the menu.

Any given processing or analysis menu item must be applied to a data item that is compatible with the processing or analysis. For example, you cannot apply processing to sum a sequence of images to a non-sequence.

The particular behavior of a given processing function applied to the wrong data varies. Different processing functions may produce an invalid data item, do nothing, or produce an error message.

Live Computations with Multiple Inputs
++++++++++++++++++++++++++++++++++++++
In cases where processing requires multiple inputs (e.g. cross correlation or make RGB), most operations will work with a single item selected and then you can edit the computation (see `Edit Computation`_) to change the secondary inputs.

You can also select multiple display panels before you use the processing menu item if that is easier.

Finally, for many operations you can select multiple crops (rectangles on images or intervals on line plots) and the processing will use the selected crops.

See :ref:`display-panels` for more information about keyboard focus and selecting multiple display panels.

Duplicate, Snapshot, and Capture
--------------------------------
Since displays are distinct from data items, there are a variety of commands to make additional copies of displays and data items.

The :menuselection:`Display --> Duplicate Display Item` menu item creates a new display item that is a copy of the selected display item. The new display item is linked to the original data item. This can be used to create a another view of the original data item. Each display can have its own settings, such as color table, zoom level, and crop.

The :menuselection:`Display --> Snapshot Display` menu item or the :kbd:`Ctrl+S` (Windows/Linux) or :kbd:`Cmd+S` creates a new data item that matches the displayed image or line plot of the original data item. Then a new display is created that is linked to the new data item and matches the original display. This can be used to grab a particular display snapshot for later reference. Neither the new display nor the new data item is linked to the original display or data item. For instance, if you have a spectrum image and take a display snapshot, the resulting data item will be the displayed slice of the original data only, not the full spectrum image data.

The :menuselection:`Processing --> Snapshot` menu item creates a new data item that is a copy of the selected data item. The new data item not linked to the original data item and the associated display is copied.

The :menuselection:`Processing --> Duplicate` menu item creates a new data item that is a copy of the selected data item. The new data item is not linked to the original data item and the associated display is not copied.

Some plug-in packages may also provide the concept of "capture" which is similar to "duplicate" but will ensure the duplicate takes place at the end of a frame. This is useful during acquisition where the data may be partially updated.

.. _Line Profile Computation:

Line Profiles
-------------
A line profile is a special live computation that allows you to see the intensity of an image along a line with optional integration in the tranverse direction. The line is displayed on the image and the profile is displayed in a line plot.

A line profile can be created by using the line profile tool in the tool panel, by choosing the :menuselection:`Processing --> Line Profile` menu item, or by pressing the kbd:`l` key while a display panel has keyboard focus.

A line profile can be edited by dragging the resulting line profile graphic or by editing the line profile graphic in the inspector.

A line profile and its computation can be copied from one data item to another by copying and pasting the line profile graphic from one display to another. A new line profile graphic and associated computation will be created on the data item of target display.

See also :ref:`Line Profile Graphic`.

Picks
-----
A pick is a special live computation that allows you to pick a region of a collection of 1d data and see the average or sum of the 1d data in the region. The region is displayed as a rectangle graphic on the collection of 1d data and the average or sum is displayed in a line plot.

A pick can be created by choosing the :menuselection:`Processing --> Reduce --> Pick` menu item, or by pressing the :kbd:`p` key while a display panel has keyboard focus.

A pick can be edited by dragging the resulting rectangle graphic or by editing the pick graphic in the inspector.

A pick can be copied from one data item to another by copying and pasting the pick graphic from one display to another. Then, using the new rectangle graphic, a new pick computation can be created using :menuselection:`Processing --> Reduce --> Pick`.

See also :ref:`Rectangle Graphic`.

Generating Data
---------------

The :menuselection:`Processing --> Generate Data` menu item allows you to create a new data item with a specified shape and data type. The data can also be expanded to a collection or sequence.

.. _Edit Computation:

Edit Computation
----------------
The edit computation dialog allows you to edit the inputs and parameters of a computation.

Once the edit computation dialog is open, you can change inputs by dragging items into the input data item controls.

You can drag display items from the data panel or display panels to the input thumbnails in the dialog. You can also drag the thumbnails themselves out into display panels.

Some computations can perform their processing on a cropped region of a data item. You can select a rectangular graphic on a display item, release the mouse, hold the :kbd:`Alt` key (Windows, Linux) or the :kbd:`Option` key (macOS), then click the mouse on the selected graphic and drag to the input data item control in the edit computation dialog. This will force the combination of the data and crop area to be used as the input data item.

Run Script
----------
The :guilabel:`Run Script` dialog allows you to install and run Python scripts. The availability of the scripts are persistent between launches of Nion Swift.

To open the dialog, choose the menu item :menuselection:`File --> Scripts...`.

Once the dialog is open, you can add individual scripts using the :guilabel:`Add...` button.

You can also add a folder of scripts using the :guilabel:`Add Folder...` button.

You can remove scripts by selecting them and clicking the :guilabel:`Remove` button.

You can open the folder location of a script by right clicking on the script and choosing :menuselection:`Open Containing Folder`.

You can run a script by selecting it and clicking the :guilabel:`Run` button or by double-clicking on the script.

When the script runs, it will show its output and possibly ask for some input.

Once it is finished, you can click the :guilabel:`Close` button to close the window or the :guilabel:`Run Again` button to re-run the script.

Python Scripts
--------------
The :guilabel:`Python Console` can be used to run immediate mode Python commands.

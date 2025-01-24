:orphan:

.. _processing:

Processing and Analysis
=======================
.. explanation: Background information and conceptual discussions

You can apply processing and analysis to items in your project. An example of processing may be to apply an FFT operation to an image. An example of analysis may be to measure the intensity of a line profile.

Most processing and analysis functions set up a live computation, meaning that when you apply the processing to a data item the results, often another data item, will be updated whenever the input data item changes or when the parameters of the computation change. The live computation is live even after closing and reloading the project.

Some processing functions are single commands, meaning that the result is computed once and the resulting data item or other output is added to the project and no live computation is created.

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

.. _Edit Computation:

Edit Computation
----------------
The edit computation dialog allows you to edit the inputs and parameters of a computation.

Once the edit computation dialog is open, you can change inputs by dragging items into the input data item controls.

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

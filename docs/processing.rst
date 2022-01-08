:orphan:

.. _processing:

Processing and Analysis
=======================
You can apply processing and analysis to items in your project.

When you apply processing or analysis, a computation is configured and stored in your project.

A computation takes inputs and produces outputs. It also watches for changes to its inputs and updates it outputs whenever the inputs change.

Inputs can be data items, display items, and graphics. Outputs can be data items and graphics.

Computations are particularly useful during acquisition where you can perform live processing on incoming data.

Computations are also useful for non-acquisition processing and analysis because they allow you to vary parameters and observe how the outputs change.

Computations
------------
To apply processing and analysis to items in your project, you should first select the inputs you want to process or analyze.

In many cases, you can select the input by clicking on a display panel to give it keyboard focus and then choosing one of the processing menu items.

Computations with Multiple Inputs
+++++++++++++++++++++++++++++++++
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

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

Some computations can perform their processing on a cropped region of a data item. You can select a rectangular graphic on a display item, release the mouse, hold the Alt key (Windows, Linux) or the Option key (macOS), then click the mouse on the selected graphic and drag to the input data item control in the edit computation dialog. This will force the combination of the data and crop area to be used as the input data item.

Run Script
----------

Python Scripts
--------------

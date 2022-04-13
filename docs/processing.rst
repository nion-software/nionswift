:orphan:

.. _processing:

***********************
Processing and Analysis
***********************
Processing and analysis comes in the form of computations. Computations can be applied to data items and graphics in your project and they can gather specific metrics on your data for analysis. Computations take inputs in the form of data items, display items, or graphics; and produce outputs in the form of new data items, or graphics. If the input of a computation is modified, the outputs will update live to reflect the new calculations. This means you can use computations for processing data being acquired live. When a computation is applied to a data item or graphic, the computation will be stored in the project.

Computations
============
To apply processing to an item, select the item by clicking on it, then use the [Processing] menu to select the desired computation. If a computation requires multiple inputs, you can select multiple items before applying processing. See :ref:`data-items` (Selections) for more information. You could also apply a process to only one item and add more inputs using the Computation editor dialogue. Open the editor by hitting [ctrl + E] (or [cmd + E] on macOS). To add or change inputs in the Computation editor dialogue, drag data items, display items, or graphics into the input slot(s). 

Computational Graphics 
======================
The line profile and Fourier filter have a computational aspect to them that uses the data at their position as an input and creates a new data item to show their output.

Line Profile
------------
A line profile creates a line plot of the data under the line in an image. Add a line profile to an image with the line profile tool in the toolbar or by hitting the lowercase “L” key. Creating a line profile will generate a new data item in the form of a line plot that will display the values of the data under the line.

Fourier Filtering
-----------------
Fourier filtering can be applied to one of the four :ref:`graphics` (Masks). To add a Fourier filter to a graphic or display item, select the item and use the menu item [Processing > Fourier > Fourier Filter].

Scripts and Commands
====================
To extend the functionality of Swift, you can add and run your own scripts in your project. Begin by opening the script dialogue box by using the menu item [File > Scripts…]. Clicking the “Add…” or “Add Folder…” buttons will allow you to select one or multiple scripts to import into the project. Similarly, to remove a script, select it and click the “Remove” button. To quickly add other scripts contained in the same folder as a previously added script, right click on the script and choose “Open Containing Folder.” 

To run a script, select the desired script from the Scripts dialogue box and click “Run.” You can also run a script by double clicking on it. A running script will display its output in the Output Panel. A script might also ask for an input or inputs if it doesn't have the right data to run on.

Once a script has finished, click the “Close” button to close the dialogue, or click “Run Again” to re-run the script.

To run immediate mode Python commands, open the Python Console by using the menu item [File > Python Console…].


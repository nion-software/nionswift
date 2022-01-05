:orphan:

.. _display-panels:

Display Panels
==============

Display Panels
--------------
Display panels are used to show display items.

You can drag items from the data panel into a display panel.

You can put keyboard focus on a display panel by clicking on it.

The display item with keyboard focus also serves as the primary selected item. Primary selections are indicated by a solid focus ring.

You can add secondary selected items by :kbd:`control` clicking (Windows/Linux) or :kbd:`command` (macOS) clicking on display panels. Secondary selections are indicated by a dotted focus ring.

Processing and other commands apply to the primary selected items. Processing commands that need multiple inputs may use secondary selected items.

To select multiple primary items, you need to use the data panel or a browser panel.

.. _Display Panel Browsers:

Browsers
--------
Display panels can also show a browser, either as a thumbnail strip at the bottom of the display panel (thumbnail browser) or as a grid of display items (grid browser).

You can change the browser in a display panel by using the menu items :menuselection:`Display --> Thumbnail Browser` and :menuselection:`Display --> Grid Browser`. You can change to the single display item view by choosing the menu item :menuselection:`Display --> Display Item`.

You can also cycle between the display item, thumbnail, and grid browser by clicking on the display panel and pressing the :kbd:`v` key.

Finally, you can change to a single display item by double clicking on it in either the thumbnail or grid browser.

Note: If the display panel has an associated control bar, which is often present for live acquisition data, the :kbd:`v` key will not work.

.. _Image Display Panel:

Images
------
If the display item is displaying 2D data, it will be shown as an image.

Images can be zoomed and translated within the display panel.

To move the image within the display panel, you can use the hand tool or the keyboard.

To use the hand tool, select the :guilabel:`Hand` in the tool bar (or press the :kbd:`h` key shortcut). Then drag the image with the hand. See :ref:`Tool Panel`.

To use the keyboard, deselect any graphics and then use the arrow keys to nudge the image. Holding down the shift key while pressing the arrow keys makes the nudge larger. You can also move the image with the :kbd:`i`, :kbd:`j`, :kbd:`k`, and :kbd:`m` keys.

To zoom the image within the display panel, you can use the keyboard.

To use the keyboard, press the :kbd:`+` or :kbd:`-` keys to zoom in or out respectively.

You can also reset the image to fit inside the display panel, fill the display panel, and also scale itself such that the image to screen pixel ratio is 1:1 or 2:1.

You can use the menu item :menuselection:`Display -> Fit to View` or press :kbd:`0` to make the image fit the display panel area.

You can use the menu item :menuselection:`Display -> Fill View` or press :kbd:`Shift-0` to fill the display panel area such that no extra space is visible. This may crop part of the display.

You can use the menu items :menuselection:`Display -> 1:1 View` or :menuselection:`Display -> 2:1 View` or press :kbd:`1` or :kbd:`2` to change the image to be a 1:1 or 1:2 image pixel to screen pixel ratio.

The image display shows a two dimensional data element. If the data item has data that is higher dimensional, such as a sequence of images, controls may be overlaid on the image allowing you to select which item in the sequence or collection is displayed.

Once the two dimensional data element is determined, the data is converted to scalar, if required, according to the complex data type in the inspector. For instance, if the data is complex then it may be converted to a scalar by taking the log-modulus of the data.

Once the data has been converted to scalar values, brightness, contrast, and gamma adjustments are applied to rescale the data.

The display has an associated color map, which can be changed in the Inspector.

Once the adjustments have been applied, the data is scaled so that the lower display limit maps to the lower end of the color map and the upper display limit maps to the upper end of the color map.

The display limits may be specified or unspecified, in which case they are "auto" calculated, meaning that they will automatically adjust to the lowest and highest values of the data (once it has been converted to scalar and brightness, contrast, and gamma applied) in the image.

The selection of indexes for sequences or collections, the conversion from complex to scalar, the adjustments such as brightness, contrast, and gamma, the display limits, and the color map are all selectable or editable using the inspector (see :ref:`Inspector Panel`).

You can press the :kbd:`Enter` key to reset display limits.

The Histogram panel (see :ref:`Histogram Panel`) shows the histogram of the image data. It can be used to set or reset the display limits by dragging within the histogram graph or by double clicking within the graph, respectively.

The Info panel (see :ref:`Info Panel`) shows the value of the image data underneath the cursor.

You can add graphics and other annotations to the image display. See :ref:`graphics`.

.. _Line Plot Display Panel:

Line Plots
----------
If the display item is displaying 1D data, it will be shown as an line plot.

The data within a line plot can be scaled in both the x-axis and y-axis. The intensity values in the data will be displayed along the y-axis. The x-axis is determined by the calibration of the data.

You can drag each axis of the line plot by moving the mouse over the labels and dragging.

You can zoom each axis by :kbd:`control` clicking (Windows/Linux) or :kbd:`command` (macOS) clicking on the axis and dragging up/right to zoom in and down/left to zoom out.

The line plot display shows a one dimensional data element. If the data item has data that is higher dimensional, such as a sequence of spectra, controls may be overlaid on the line plot allowing you to select which item in the sequence or collection is displayed.

Once the one dimensional data element is determined, the data is converted to scalar, if required, according to the complex data type in the inspector. For instance, if the data is complex then it may be converted to a scalar by taking the modulus of the data.

The axes may be configured so that they are specified with values or are "auto" calculated, meaning that they will automatically adjust so that the entire data range is shown.

You can reset an axis to "auto" by double clicking on it.

The display limits and display channels may be specified or unspecified, in which case they are "auto" calculated, meaning that they will automatically adjust to the lowest and highest values of the data (once it has been converted to scalar) in the plot.

The y-axis can be displayed as linear or logarithmic by clicking on the :guilabel:`Log Scale (Y)` checkbox in the :guilabel:`Line Plot Display` section of the Inspector.

The line plot can display calibrated or uncalibrated values. You can change what is displayed by changing the :guilabel:`Display` setting in the :guilabel:`Calibrations` section of the Inspector.

You can also change calibration in the Inspector. However, if the data is a result of a computation or acquisition, the calibration will get recalculated/reset when the data is recomputed/reacquired.

The Info panel (see :ref:`Info Panel`) shows the value of the data underneath the cursor.

You can add interval graphics to the line plot by dragging across the plot or by using the menu item :menuselection:`Processing --> Add Interval Graphic`.

You can add a channel graphic to the line plot by using the menu item :menuselection:`Processing --> Add Channel Graphic`.

You can use the mouse to move and resize interval graphics. You can also use the mouse to move channel graphics. You can use the Inspector to adjust the endpoints of the interval graphics or position of the channel graphics.

You can use the :kbd:`Left` and  :kbd:`Right` arrow keys to nudge an interval graphic or channel graphics. Holding the :kbd:`Shift` key while nudging the graphic will make it move farther.

You can press the :kbd:`Delete` key with a interval graphic or channel graphic selected to delete the it.

Line Plot Layers
++++++++++++++++
.. this is too complicated

A line plot display can show multiple data item plots in the same display.

You can drag a line plot into the graph area of another line plot to create the layering. Each layer will have its own name, stroke color, fill color, and stroke width.

Note: Layers will only be displayed if the calibrated units match the first data item in the line plot. This can be confusing.

The line plot display with multiple layers will have one or more data items associated with it. Each layer will be "pointing to" one of the data items. This is specified in the Inspector as the :guilabel:`Data Index`. In addition, each data item may have multiple rows of data or just one. If multiple, the layer can pick which row is displayed in that layer by the :guilabel:`Row`. Also note that each data item may be higher dimensional data and require its own selection of sequence or collection index to reduce itself to a one dimensional data element that will then be displayed in the layer.

The line plot layers can be reordered. The line plot data items cannot be reordered, although they may be deleted by clicking the :guilabel:`X` in the :guilabel:`Data #n` section of the Inspector. If a data item is removed from the line plot, any associated layers are automatically removed also. In addition, new data items and subsequently new layers can be added. Dragging in a new data item will automatically add an associated layer.

To reorder the line plot layers, you can click the up and down arrows in the :guilabel:`Line Plot Layers` section of the Inspector.

To add or remove line plot layers without explicitly adding or removing the underlying data items, you can click the :guilabel:`+` and :guilabel:`-` buttons in the :guilabel:`Line Plot Layers` section of the Inspector.

You can change the fill and stroke colors (both of which may be transparent to effectively make them invisible) by clicking on the associated color pick or by typing in a color into the associated text field. The format of the text field can be in the format "rgb(100, 50, 200)", "rgb(100, 50, 200, 0.5)" for transparency, "#55AAFF", "#55AAFF80" for transparency, or a web-named color such as "blue".

When the line plot has multiple layers, the name of each layer can be displayed in a legend. You can adjust the position of the legend or whether it appears at all by changing the :guilabel:`Legend Position` in the :guilabel:`Line Plot Display` section of the Inspector.

You can reorder layers within the legend by grabbing the layer and dragging it to reorder it within the legend.

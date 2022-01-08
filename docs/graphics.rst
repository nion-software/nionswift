:orphan:

.. _graphics:

Graphics
========
Both image displays and line plot displays can be annotated with graphic items. The graphics serve as functional elements when they designate a region such as a crop or they can serve as annotation elements where they annotate the data.

Graphics can be named and the label will appear next to the graphic.

Graphics can be edited in uncalibrated or calibrated coordinates.

Most graphics can be added using either the menus or the tool panel.  See :ref:`Tool Panel`.

You can select graphics by clicking on them.

You can deselect all graphics by clicking somewhere outside any graphic.

You can select or deselect multiple graphics by :kbd:`Control` key (Windows) clicking or :kbd:`Command` key (macOS) clicking on additional graphics.

You can delete graphics by selecting the graphics to delete and pressing the :kbd:`Delete` key or choosing :menuselection:`Edit --> Delete`.

You can cut, copy, and paste graphics.

If you have trouble selecting a graphic that is behind another graphic, try clicking on the control points of the graphic. The control points take priority over the middle of graphics further forward.

.. _Image Graphics:

Image Graphics
--------------
Several graphics are specific to image displays.

.. _Point Graphic:

Point
+++++
The point graphic can be placed on an image display.

You can add a point graphic using the :guilabel:`Point` tool in the tool panel.

You can add a point by using the menu item :menuselection:`Graphics --> Add Point Graphic`.

You can edit the position of the point in the :guilabel:`Inspector` panel.

You can edit the position of the point by dragging.

.. _Line Graphic:

Line
++++
The line graphic can be placed on an image display.

You can add a line graphic using the :guilabel:`Line` tool in the tool panel.

You can add a line by using the menu item :menuselection:`Graphics --> Add Line Graphic`.

You can edit the start, end, length, and angle of the line in the :guilabel:`Inspector` panel.

You can edit the end points of the line by dragging each end point. Holding the :kbd:`Shift` key while dragging will limit the line to be horizontal, vertical, or at a 45° angle.

You can change the position of the line by dragging in the middle along the line.

.. _Line Profile Graphic:

Line Profile
++++++++++++
A special line graphic can be used as the source of the line profile computation, which produces another data item with data of the image underneath the line.

You can add a line graphic using the :guilabel:`Line Profile` tool in the tool panel.

You can add a line profile by using the menu item :menuselection:`Processing -> Line Profile`.

You can edit the start, end, length, angle, and width of the line profile in the :guilabel:`Inspector` panel.

You can edit the end points of the line by dragging each end point. Holding the :kbd:`Shift` key while dragging will limit the line to be horizontal, vertical, or at a 45° angle.

You can change the position of the line by dragging in the middle along the line.

.. _Rectangle Graphic:

Rectangle
+++++++++
The rectangle graphic can be placed on an image display.

You can add a rectangle graphic using the :guilabel:`Rectangle` tool in the tool panel.

You can add a rectangle by using the menu item :menuselection:`Graphics --> Add Rectangle Graphic`.

You can edit the center position, size, and rotation of the rectangle in the :guilabel:`Inspector` panel.

You can edit the corners of the rectangle by dragging the corners.

You can change the position of the rectangle by dragging in the middle of the rectangle.

You can rotate the rectangle by selecting it and dragging the rotation control at the top of the rectangle.

.. _Ellipse Graphic:

Ellipse
+++++++
The ellipse graphic can be placed on an image display.

You can add an ellipse graphic using the :guilabel:`Ellipse` tool in the tool panel.

You can add an ellipse by using the menu item :menuselection:`Graphics --> Add Ellipse Graphic`.

You can edit the center position, size, and rotation of the ellipse in the :guilabel:`Inspector` panel.

You can edit the corners of the ellipse by dragging the corners.

You can change the position of the ellipse by dragging in the middle of the ellipse.

You can rotate the ellipse by selecting it and dragging the rotation control at the top of the ellipse.

.. _Line Plot Graphics:

Line Plot Graphics
------------------
Several graphics are specific to line plot displays.

.. _Interval Graphic:

Interval
++++++++
The interval graphic can be placed on a line plot display.

You can add an interval graphic by dragging over the line plot with the :guilabel:`Pointer` tool.

If there are other intervals which prevent dragging, you can select the :guilabel:`Interval` tool and force an interval to be created.

You can add an interval graphic by using the menu item :menuselection:`Graphics --> Add Interval Graphic`.

You can edit the left and right channels of the interval by positioning the mouse over the left/right channel and dragging. The cursor will change to indicate you are adjusting an edge. It may be helpful to zoom into the line plot area where the interval is located for more precise positioning.

You can edit the position of the interval by dragging within the middle of the interval. The cursor will change to indicate you are dragging rather than editing an edge.

You can hold down the :kbd:`Control` key (Windows) or :kbd:`Command` key (macOS) to force dragging of the interval instead of editing the left/right channel.

When the interval is selected, it displays the left and right channel values and the interval width.

You can edit the left and right channel of the interval graphic in the :guilabel:`Inspector` panel.

.. _Channel Graphic:

Channel
+++++++
The channel graphic can be placed on a line plot display.

You can add a channel graphic by using the menu item :menuselection:`Graphics --> Add Channel Graphic`.

You can drag the channel graphic using the mouse.

You can edit the position of the channel graphic in the :guilabel:`Inspector` panel.

.. _Masking:

Masking
-------
Rectangle and ellipse graphics can be used to construct masks. Masks are used in conjunction with some processing operations such as :menuselection:`Processing --> Arithmetic --> Mask` and  :menuselection:`Processing --> Arithmetic --> Masked`.

To create a mask, add one or more rectangle or ellipse graphics. Select the desired masks and use the menu item :menuselection:`Graphics --> Add to Mask`.

You can remove a graphic from a mask by selecting the graphic and choosing :menuselection:`Graphics -> Remove from Mask` or by just deleting the graphic.

.. _Fourier Filtering:

Fourier Filtering
-----------------
A special type of masking is called Fourier filtering. You can place symmetric masks on complex-valued images and perform Fourier filtering using the menu item :menuselection:`Processing --> Fourier --> Fourier Filter`.

The origin of the Fourier filter graphics will typically be in the middle of the center value of the complex-valued image. However, the origin can be changed by editing the spatial calibrations of the image.

Four types of graphics are available for Fourier filter.

.. this section needs work
..   a better description of the use of filters
..   more thorough explanation of their functionality

.. _Spot Graphic:

Spot
++++
The spot graphic is a rotatable ellipse, symmetric around the origin. It can be used to filter a specific frequency at a specific angle.

You can drag either spot to adjust its position, shape, and rotation.

You can edit the position, size, and rotation in the :guilabel:`Inspector` panel.

.. _Wedge Graphic:

Wedge
+++++
The wedge graphic is a pair of lines intersecting at the origin. It can be used to perform filtering along a specific angle and a range of frequencies.

You can drag either line to adjust its angle.

You can edit both angles in the :guilabel:`Inspector` panel.

.. _Ring Graphic:

Ring
++++
The wedge graphic is a pair of circles centered at the origin. It can be used to perform low pass, high pass, and band pass filters.

You can drag the radius of either circle to adjust its filter frequency.

You can change whether it is a low pass, high pass, or band pass filter in the :guilabel:`Inspector` panel.

.. _Lattice Graphic:

Lattice
+++++++
The lattice graphic is a repeating filter centered at the origin. It can be used to filter related frequencies occurring at regular spacing.

The lattice graphic consists of two vectors and rotatable ellipses at the end of each vector. The vectors are then repeated across the entire image.

You can edit the position of each vector by dragging the ellipse. You can edit the shape and rotation of the ellipse.

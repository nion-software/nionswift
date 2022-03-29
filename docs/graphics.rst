:orphan:

.. _graphics:

Graphics
========
Graphics are used to highlight certain sections of a display item. Similarly, masks are used to mark off certain sections of a display item to focus on. Certain graphics can only be used on images and others can only be used on line plots. Masks can only be used on images. Selecting one or multiple graphics on the same display item will allow you to edit the parameters of the graphics in the :ref:`graphics inspector section` subsection of the Inspector Panel. Selecting a display panel with graphics on it will show parameters for editing all of the applied graphics in the Inspector Panel. You can copy, cut, and paste graphics by selecting them with [ctrl + click] (or [cmd + click] on macOS) or by using shortcuts like [ctrl + c] and [ctrl + v] (or [cmd + c] and [cmd + v] for macOS) To delete a graphic or graphics, select them and press the delete key or use the menu item [Edit > Delete].

.. _Image Graphics:

Image Graphics
--------------
Image graphics are exclusive to data items displayed as images. They can only be placed on 2D images. Add an image graphic by using the various graphic buttons in the toolbar or by using the [Graphics] menu item. 

.. _Point Graphic:

Point
+++++
The point graphic highlights the point at the center of four anchor points. The anchor points show the boundary of the graphic but cannot be moved in relation to the center of the graphic or to each other. To move the point graphic, click and drag from anywhere within the four anchor points.

In the Inspector Panel, you can adjust the (x,y) coordinate of the center point.

.. _Line Graphic:

Line
++++
The line graphic creates a line between two anchor points. To move the line, click and drag from any point along the line excluding the two anchor points. You can adjust the line by manipulating the two anchor points. Holding shift while moving an anchor point will snap the line to a multiple of a 45˚ angle.

In the Inspector Panel, you can adjust the length of the line, angle of the line, and (x,y) coordinates of both anchor points.

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
The rectangle graphic creates a rectangle with four anchor points at the vertices. Holding shift while manipulating one of the anchor points will make the rectangle a perfect square. To adjust the rotation of the rectangle, drag the fifth, exterior anchor point around its center point. Holding shift while rotating the graphic will snap it to intervals of 45˚. To move the whole graphic, click and drag from anywhere within the outer line of the rectangle.

In the Inspector Panel, you can adjust the (x,y) coordinate of the center point, the height and width of the rectangle, and the rotation of the graphic.

.. _Ellipse Graphic:

Ellipse
+++++++
The ellipse graphic creates an ellipse between four anchor points. Holding shift while manipulating one of the anchor points will make the ellipse a perfect circle. To adjust the rotation of the ellipse, drag the fifth, exterior anchor point around its center point. Holding shift while rotating the graphic will snap it to intervals of 45˚. To move the whole graphic, click and drag from anywhere within the outer line of the ellipse.

In the Inspector Panel, you can adjust the (x,y) coordinate of the center point, the height and width of the ellipse, and the rotation of the graphic.

.. _Line Plot Graphics:

Line Plot Graphics
------------------
Line plot graphics are exclusive to data items displayed as line plots. They can only be placed on 1D line plots. Add a line plot graphic by using the various graphic buttons in the toolbar or by using the [Graphics] menu item.

.. _Interval Graphic:

Interval
++++++++
The interval graphic highlights a section between two boundaries. To adjust the boundaries of the interval, click and drag left or right from either of the boundaries. To move the entire interval, click and drag the center anchor point between the two boundaries.

In the Inspector Panel, you can adjust the x values of each boundary.

If another interval graphic is blocking the creation of a new one, you can use the Interval Graphic button in the toolbar to force a new graphic.

.. _Channel Graphic:

Channel
+++++++
The channel marks a value along the x axis with an orange marker. To move the graphic, click and drag the orange marker along the x axis.

.. _Masking:

Masking
-------
Masks are used to isolate sections of an image to gather information from just the specified area rather than the whole image. Preset masks are added to images just like graphics either by using the mask buttons in the toolbar or by using the [Graphics] menu item. 

Aside from the default masks, you can choose to make a regular image graphic part of a mask. To add a graphic to the mask, select the graphic and use the menu item [Graphics > Add to Mask]. Similarly, remove a graphic from the mask by selecting it and using the menu item [Graphics > Remove from Mask]. A graphic will turn blue when it is part of the mask on an image.

Below are the preset types of masks. For more information about adjusting the parameters of masks, see the GRAPHICS subsection of the Inspector Panel.

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
The spot mask creates two ellipses that are symmetrical and equidistant from the top left corner. This can be used to filter a specific frequency at a specific angle. One of the ellipses might be outside of the image so you may need to move or zoom out of the image by using the [ - ] key in order to see it. The ellipses will always be identical, so manipulating one will change the other. The ellipses can be manipulated just like the ELLIPSE GRAPHIC. Moving one ellipse will also move the other ellipse to be exactly opposite the other one around the top left corner.

In the Inspector Panel, you can adjust the (x,y) coordinates of the centerpoint of the ellipse inside the image, and set the rotation of the ellipse inside the image.

.. _Wedge Graphic:

Wedge
+++++
The wedge mask creates slices through an image from the top left corner. This can be used to filter a range of frequencies at a specific angle. Move the slice by clicking and dragging from within the pink highlighted section. To adjust the angle of the wedge, click and drag one of the boundaries of the wedge.

In the Inspector Panel, you can adjust the starting and ending angles of the wedge.

.. _Ring Graphic:

Ring
++++
The ring mask creates a ring centered around the top left corner of the image. The ring mask can either include the circle around the top left corner, exclude the circle around the top left corner, or be a band with width surrounding the top left corner. Adjust the radius(es) of the circle(s) by dragging the anchor points along the edges of the image.

In the Inspector Panel, you can adjust both radiuses and the type of ring. Radius 1 is the outermost radius and is the radius used for the low and high ring masks. The low pass ring mask excludes a ring around the top left corner of the image. The high pass ring mask includes only a ring around the top left corner of the image. The band pass ring mask makes a ring around the top left corner with an inner and outer radius.

.. _Lattice Graphic:

Lattice
+++++++
The lattice mask creates a grid of circles that tile the image. This can be used to filter related frequencies with regular spacing. 

There are two circles that can be moved to establish the pattern of the grid. These circles will be highlighted with green anchor points. One of the moveable circles will be inside the image and the other will be outside, so you may need to move or zoom out of the image using the [ - ] key in order to see it.

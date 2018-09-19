.. _userinterface-guide:

User Interface
--------------

Layouts
^^^^^^^
The overall size of the layout is determined by the panel_properties of the panel delegate. If no width or height are
specified the size is determined by the content. If the content cannot be used to determine the size, then other panels
in the same column or row are used to determine the size. The recommended technique for width is to add a 'min-width' to
your panel_properties. This allows the width to expand to match wider panels docked in the same column. The recommended
technique for height is to add a 'max-height' if needed. A minimum height can be specified with 'min-height' but it is
not usually needed since the content almost always determines the preferred height.

Within the overall layout, children will expand to take up as much space as possible. You can add ``spacing`` and
``stetches`` to rows and coluns to modify this behavior. If a ``stretch`` is present within a row or column, the rest of
the items will be decreased to their preferred size and possibly further to their minimum size.

For instance, if you add a button to a row, the button will expand to the size of the row. If you add a button and a
stretch, the button will only expand to its preferred size. The ``stretch`` will fill the remainder of the space.

Best Practices
^^^^^^^^^^^^^^
* Separate the UI code from the controller code. Consider putting all control code into a separate controller class.
* Write the code bottom-up, which means define all components, then add to enclosing item, then add those enclosing
  items to their enclosing items, until the top level at the bottom of the code. Then add controller code.
* Write utility functions for common code. Make functions purely functional when possible.
* Use closures and lambda functions to avoid defining new methods.
* Pay attention to when close methods are required to be called.

..
    Menu Item
    ---------
    N/A

    Panel
    -----
    N/A

    Declarative UI
    --------------

    * model stored in properties, model objects, or the widgets.
    * binding vs. explicit get/set/event.
    * model objects for binding vs. get/set/notify methods.
    * items that have content have margins and spacing
    * splitting into design, handler, hardware abstraction
    * testing strategies: nui, test-ui, logging

    * TODO: validations
    * TODO: consider whether to have an initialize component call in the handler
    * TODO: decide on class naming
    * TODO: creator application, running without any models
    * TODO: a web based version, how does application, windows, dialogs, etc. fit together
    * TODO: custom canvas items

:orphan:

.. _upgrading:

Upgrading from Earlier Versions
===============================

Notable Changes
---------------
The highlights of this release are improved display performance, improved reliability, improved line plot displays, and an improved computation inspector.

In addition, the nomenclature has changed slightly. In Nion Swift 15, data is stored in *Projects*. Projects were previously named *Libraries*. This change was made to conform more to image processing and archiving standard terms.

The menus have also changed slightly. The *View* menu has been split into *Display* and *Workspace* menus. And a new menu *Graphics* has been added.

Upgrading
---------
Be sure to quit/exit any previous versions of Nion Swift before running the new version.

If you had been using an earlier version of Nion Swift, your existing projects will be scanned when you launch the first time. This may take a while depending on how many existing projects are available.

Existing projects will need to be upgraded to work with the newer version of Nion Swift. Upgrading a project will ask you to choose a new location for the upgraded project and then it will copy all existing files into the new location.

Whereas *Libraries* were stored in folders in earlier versions of Swift, *Projects* are similarly stored. However, the standard storage mechanism is now a single index file and an associated folder of data. So when upgrading, you'll be choosing a location and name for the index file. The associated data folder will be created in the same location.

Once the existing projects have been scanned and upgraded, Nion Swift will launch and ask you to choose an initial project. You can switch projects any time using the **File** > **Chose Project...** menu item.

.. image:: graphics/choose_project.png
  :width: 450
  :alt: Choose Project

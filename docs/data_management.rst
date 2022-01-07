:orphan:

.. _data-management:

Data Management
===============

.. _Import Export:

Import/Exporting
----------------
When you import files, they are copied into your project as items and stored in an internal format.

You can also export items to files. The exported files can be used in other programs. Exporting a file does not remove it from your project.

.. _Import:

Importing
+++++++++
You can import data from several data formats.

You can drag files directly into the data panel to import.

You can drag files directly into an empty display panel to import.

You can import files using the :menuselection:`File --> Import...` menu item. This will allow you to select which files to import. The files will appear in your project.

You can import a folder of files using :menuselection:`File --> Import Folder...` menu item. This will import all files that are importable within the folder. The files will appear in your project.

.. _Export:

Exporting
+++++++++
You can export to several data formats.

The data format to which you are exporting must support data in the format of the data item you are choosing to export. For instance, you cannot export a 2D collection of 1D data to TIFF, which only supports images.

You can select which data items to export by selecting one or more items in the data panel and context clicking on one of the items and then choosing the :menuselection:`File --> Export...` menu item.

You can also export the currently focused item by choosing the menu item :menuselection:`File --> Export...`.

You can also export an item in a display panel by context clicking on the display panel and choosing :menuselection:`Export...`.

You can also represent a graphic representation of your display using :menuselection:`File --> Export SVG...`.

.. _Managing Projects:

Managing Projects
-----------------
Data is organized into projects, which hold the data and a description of the connections between the data.

A project may represent a particular session on an instrument, an ongoing session, or another grouping of data.

Only one project can be open at once and the name of the project is shown in the title bar of the main window.

The project is stored on disk and is typically a combination of an index file and a folder of data stored at the same folder level.

The index file has the suffix '.nsproj' and the data folder is named with the same base name as the index file with 'Data' appended to the name.

It is not possible (currently) to rename projects.

It is not possible (currently) to transfer data items between projects.

Projects from previous versions may be a folder with both the index file, with the suffix of '.nslib', and data folder inside.

You can create a new project using the menu item :menuselection:`File --> New Project...`. You will be asked to choose a location in which to create the project and a name for the project. Two files will be created within the folder you select: an index file with the base name your select for the project and the suffix '.nsproj' and a data folder with the base name you select for the project and the suffix 'Data'.

You can switch projects by using the menu :menuselection:`File --> Recent Projects`.

You can also switch projects by using the menu :menuselection:`File --> Choose Project...`. A list of recent projects will be shown. You can also create a new project or open a previous project from the resulting dialog. You can mouse over the list of projects to see their location. You can right-click on a project to open its location or remove it from the list.

You can open an existing project that does not appear in either the choose project dialog or the recent projects menu. Use :menuselection:`File --> Open Project...`. You will be asked to select a file with the suffix of either '.nsproj' or '.nsindex' (for older projects).

We recommend creating new projects frequently in order to keep the number of items per project limited.

.. _Backup:

Backup
------
You can back up your project by copying the index file and the data folder.

Be sure to exit Nion Swift before backing up the project.

Also take care not to modify multiple copies of the project.

To restore a project, you can copy the index file and data folder to your local machine and then use :menuselection:`File --> Open Project...` to open the restored project.

.. _Recovery:

Recovery
--------
If you lose your index file or it becomes corrupt, the data in the project may still be recoverable. Contact us to proceed.

:orphan:

.. _data-management:

Data Management
===============
Nion Swift can accept data files, export changed files, and store projects as index files. It is important to know how to keep track of the different kinds of files as you use the application.

.. _Import:

Importing
+++++++++
There are several ways to import data files into your project and many file types are supported. You can import a data file by

* Dragging it directly into the data panel

* Dragging it directly into an empty display panel

* Using the menu item [File > Import Data…]

Data files can be in image formats like PNG and JPEG files, or in other formats such as TIFF and DM3 files.

.. _Export:

Exporting
+++++++++
Data can be exported as an image or as a raw data file. To export as a file, select one or more data or display items, and use the menu item [File > Export…]. Raw data files and images can be exported this way to their respective file types, and images can also be exported as SVG files by using the menu item [File > Export SVG].

.. _Managing Projects:

Managing Projects
-----------------
Projects are stored locally on your computer as an index file. This project file will be in the NSPROJ format which will allow it to be opened in any installation of Nion Swift. The project file will store any imported, generated, or gathered data, and any modifications, computations, or scripts associated with them. The project file also keeps track of sessions so you can see what modifications happened when. Essentially, everything you see and do when working in Nion Swift is stored in the project index file.

You can create new projects, open recent projects, or select a project to open in the [File] menu. For best performance, we recommend creating new projects frequently. This keeps the number of items in a given project from getting too high.

.. _Backup:

Backup
------
It is highly recommended that you make backups of your projects. While project files themselves save data from session to session, if something happens to the project file, recovery can be very difficult or impossible. To backup your project, make a copy of the project index file and begin working on the new copy.

If something happens to your project file (corrupted, deleted, misplaced, etc.) the data may still be recoverable. Contact Nion to proceed.

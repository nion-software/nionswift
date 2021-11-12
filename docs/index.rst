.. _index:

Nion Swift User's Guide (0.16.0)
================================
Nion Swift is open source scientific image processing software integrating hardware control, data acquisition,
visualization, processing, and analysis using Python. Nion Swift is easily extended using Python. It runs on
Windows, Linux, and macOS.

.. image:: graphics/workspace.png
  :width: 640
  :alt: The Swift Workspace

Key Features

- Data handling of 1D plots, 2D images, 1D and 2D collections of plots and images, and sequences.
- Live computations that can be chained during acquisition or live parameter adjustment.
- Open source, cross platform (macOS, Windows, Linux), and Python based scientific data processing.
- Low latency, high throughput data acquisition platform.

Who Uses Nion Swift?
--------------------

Nion Swift has been primarily developed for the operation of Nion electron microscopes and also as an offline tool to
visualize, process, and analyze scientific data from electron microscopes, other instrumentation, and other scientific
fields.

Nion Swift is open source. You can find the source code on
`GitHub Nion Swift <https://github.com/nion-software/nionswift/>`_.

Installation/Upgrading
----------------------
To install Nion Swift, you will need to install a Python environment and then install Python packages required for Nion
Swift.

For specific installation details and download links, follow link below. Instructions to install additional packages to
extend Nion Swift are also covered.

* :ref:`installation`
* :ref:`upgrading`
* :ref:`release-notes`

Using Nion Swift
----------------
Once you have installed Nion Swift and successfully launched it, you can read the introduction to understand the basic
ideas, follow through the basic tutorial to try out key concepts, and consult the user guide for more advanced use,
Python scripting, and reference.

* :ref:`basic-use`
* :ref:`user-guide`

.. _python-scripting:

Python Scripting
----------------
Nion Swift offers a great deal of functionality using the user interface. However, sometimes you will want to go beyond
its intrinsic capabilities. Fortunately it is easy to extend the functionality using Python.

* :ref:`scripting`

Nion Swift Links
----------------
`Nion Swift Google Group <https://groups.google.com/forum/#!forum/nionswift>`_ News and Announcements.

Indices and Tables
==================

Links
-----
* :ref:`genindex`
* :ref:`modindex`
* :ref:`search`

..
  Docs environment:
  conda create -n docs pip sphinx scipy h5py imageio pytz tzlocal pillow

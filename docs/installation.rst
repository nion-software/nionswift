.. _installation:

Nion Swift Installation
=======================
To install Nion Swift, you will need to install a Python environment with some specific Python packages. When you
initially launch the application, it will ask you for the directory of that Python environment.

As an open source project, there are many possible installation scenarios such as for offline use, for use on a
Nion electron microscope, or for open source development. In addition, Python installation itself is highly flexible.
Some Python installations will be used with other software, and others specifically with Nion Swift.

This guide mainly covers the offline use case with a Python environment dedicated to Nion Swift usage.

Python Environment
------------------
To use Nion Swift for offline use, you will need to install a Python environment. We recommend have a dedicated
Python installation that is only used for Nion Swift.

You will first need to install Python for your specific platform.

Nion Swift has been tested extensively with the *Anaconda* Python distribution and we recommend using that. The
Anaconda distribution includes a wide range of preinstalled Python packages, including everything required for
Nion Swift. If you are familiar with Python and wish to use a smaller distribution, you may also consider using
*Miniconda*.

We recommend using Python 3.6 or later for best performance, although the application is compatible with Python 3.5.

Begin by installing Anaconda or Miniconda on your system.

We recommend installing Python to the default location and using a conda environment.

We do not recommend adding Python to your command line PATH, which the installers will give you the option to do.

    * `Anaconda <https://www.anaconda.com/download/>`_
    * `Miniconda <https://conda.io/miniconda.html>`_

Windows
-------
Nion Swift for Windows requires Windows 7 or later, although we recommend Windows 10 for best compatibility.

Install Nion Swift using the command:

    $ \path\to\python\Scripts\conda install -c defaults -c conda-forge -c nion nionswift

Launch Nion Swift from your conda command line environment using:

    $ nionswift

MacOS
-----
Nion Swift for macOS requires macOS 10.11 or later. We recommend using the latest version of macOS.

Install Nion Swift using the command:

    $ /path/to/python/Scripts/conda install -c defaults -c conda-forge -c nion nionswift

Launch Nion Swift from your conda command line environment using:

    $ nionswift

Linux
-----
Nion Swift for Linux requires Qt 5.5 or later (qt5-default), Python 3.5 or later.

Swift has been tested with Ubuntu 16.04, 17.04, 17.10, Debian 9, Fedora 26. It is not compatible with Debian 8 (Qt 5.3)
but please contact us if you need to run on Debian 8 as there may be workarounds.

Install Nion Swift using the Terminal command:

    $ /path/to/python/Scripts/conda install -c defaults -c conda-forge -c nion nionswift

Launch Nion Swift from your Terminal conda environment using:

    $ nionswift

Installing Nion Swift Extensions
--------------------------------
Extensions for Nion Swift can be installed in your Python environment using the ``pip`` installation tool.

For example, you can install the Nion STEM microscope simulator using the either of the following commands ::

    $ pip install nionswift-usim

or

    $ conda -c defaults -c conda-forge -c nion install nionswift-usim

After restarting Nion Swift, the microscope simulator would be available within Nion Swift.

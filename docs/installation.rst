.. _installation:

Nion Swift Installation
=======================
Nion Swift is written in the Python programming language. To use Nion Swift, you will need to install a Python
environment.

As an open source project, there are many possible installation scenarios such as for offline use, for use on a
Nion electron microscope, or for open source development. In addition, Python installation itself is highly flexible.
Some Python installations will be used with other software, and others specifically with Nion Swift.

This guide mainly covers the offline use case with a Python environment dedicated to Nion Swift usage.

Requirements
------------
Nion Swift for Windows requires Windows 7 or later, although we recommend Windows 10 for best compatibility.

Nion Swift for macOS requires macOS 10.11 or later. We recommend using the latest version of macOS.

Nion Swift for Linux requires a distribution with Qt 5.5 or later (qt5-default) and Python 3.5 or later.

Nion Swift has been tested with Ubuntu 16.04, 17.04, 17.10, 18.04, Debian 9, Fedora 26. It is expected to work with
newer distributions of Linux. It is not compatible with Debian 8 (Qt 5.3) but please contact us if you need to run on
Debian 8 as there may be workarounds.

Python Environment
------------------
There are several Python environments that are capable of running Nion Swift.

Anaconda and Miniconda are Python distributions by Continuum Analytics and both allow easy installation of 3rd party
libraries that are optimized for your computer. Nion Swift has been tested extensively with both Anaconda and Miniconda
distributions.

Anaconda is a full featured environment which distributes a large number of useful libraries, but it is a large
download. The Miniconda environment is a minimal environment which can be downloaded more quickly and can later be
updated to include any desired libraries that would otherwise be contained in the larger Anaconda distribution.

You have two options:

    * Install Anaconda (more disk space, slower download, but easier to install)
    * Install Miniconda (less disk space, faster download, but requires more technical knowledge)

While it is possible to share a Python environment with other applications, or to use the built-in Python on your
machine, we recommend against this. We recommend having a dedicated Python installation that is only used for
Nion Swift.

Installing Python
-----------------
You will first need to install Python 3.6 for your specific platform. Visit one of the websites below, download the
64-bit installer, and follow the 'Instructions' link.

    * `Anaconda <https://docs.anaconda.com/anaconda/install/>`_
    * `Miniconda <https://conda.io/miniconda.html>`_

The installer may give you an option to add Python to your command line PATH. We recommend against this since it may
interfere with other Python installations.

The installer may also give you an option to make this the default Python for your system. Again, we recommend against
this since it may interfere with other Python installations.

You can usually use the default location for the installation; however, make a note of wherever you choose to install it
so that that location can be used in the steps below.

Windows
-------

Activating Python
+++++++++++++++++
If you have installed Anaconda, you will find an *Anaconda Prompt* in your Start menu. Launch the *Anaconda Prompt*.

If you have installed Miniconda, you will use the *Command Prompt* to finish the installation. Launch a Command Prompt
by clicking in the Start menu and looking in the Windows System folder for Command Prompt. You can also just click in
the Start menu and type "command" and it will usually find the Command Prompt.

For an Anaconda installation, launching the *Anaconda Prompt* will activate Anaconda Python automatically.

For a Miniconda installation you will need to explicitly activate Miniconda Python from the Command Prompt. ::

    $ C:\PATH_TO_MINCONDA\Scripts\Activate.bat

Installing Nion Swift
+++++++++++++++++++++
Once you have activated Python, you can install Nion Swift within the Anaconda or Miniconda environment. ::

    $ conda create -n nionswift -c nion nionswift nionswift-tool
    $ conda activate nionswift

Running Nion Swift
++++++++++++++++++
Once you have activated Python and installed Nion Swift, you can run Nion Swift from the command line. ::

    $ conda activate nionswift
    $ nionswift

For easier launching, you can create a Shortcut to Nion Swift on your Desktop using the command::

    $ conda activate nionswift
    $ nionswift --alias

Double clicking this Shortcut will launch Nion Swift in the Python environment from which the command above was run.

Updating Nion Swift
+++++++++++++++++++
Periodically you may want to update Nion Swift to get the latest features and bug fixes. First activate Python (see
above), then run the following command. ::

    $ conda activate nionswift
    $ conda update -c nion --all

Troubleshooting Windows Installation
++++++++++++++++++++++++++++++++++++
Nion Swift running with `nionswift-tool` requires a PATH environment variable that does not include directories
containing Qt libraries. As a workaround or if you cannot remove the other Qt installation from your PATH environment
variable, you can uninstall `nionswift-tool` and install PyQt5 using `conda install pyqt5` and try running Nion Swift
again.

MacOS
-----
Nion Swift for macOS requires macOS 10.11 or later. We recommend using the latest version of macOS.

If you have just installed conda or wish to create a new Nion Swift specific environment::

    $ source /path/to/python/bin/activate root
    $ conda create -n nionswift -c nion nionswift nionswift-tool
    $ conda activate nionswift

If you already have a conda environment, install Nion Swift using the command::

    $ conda install -c nion nionswift nionswift-tool

Launch Nion Swift from your conda command line environment using::

    $ nionswift

Linux
-----
Nion Swift for Linux requires Qt 5.5 or later (qt5-default), Python 3.5 or later.

Swift has been tested with Ubuntu 16.04, 17.04, 17.10, Debian 9, Fedora 26. It is not compatible with Debian 8 (Qt 5.3)
but please contact us if you need to run on Debian 8 as there may be workarounds.

If you have just installed conda or wish to create a new Nion Swift specific environment::

    $ source /path/to/python/Scripts/activate root
    $ conda create -n nionswift -c nion nionswift nionswift-tool
    $ conda activate nionswift

If you already have a conda environment, install Nion Swift using the command::

    $ conda install -c nion nionswift

Launch Nion Swift from your Terminal conda environment using::

    $ nionswift

Troubleshooting Linux Installation
++++++++++++++++++++++++++++++++++
Nion Swift running with `nionswift-tool` requires a PATH environment variable that does not include directories
containing Qt libraries. As a workaround or if you cannot remove the other Qt installation from your PATH environment
variable, you can uninstall `nionswift-tool` and install PyQt5 using `conda install pyqt5` and try running Nion Swift
again.

Installing Nion Swift Extensions
--------------------------------
Extensions for Nion Swift can be installed in your Python environment using the ``conda`` (preferred) or ``pip``
installation tools.

For example, you can install the Nion STEM microscope simulator using the either of the following commands::

    $ conda install -c nion nionswift-usim

or ::

    $ pip install nionswift-usim

After restarting Nion Swift, the microscope simulator would be available within Nion Swift.

You can search for additional Nion Swift extensions using the command::

    $ pip search nionswift

Here are several extensions that may prove useful:

=======================  =====  ===  =================================================================
Project Name             Conda  Pip  Description
=======================  =====  ===  =================================================================
nionswift-usim           Yes    Yes  A STEM microscope simulator for development
nionswift-eels-analysis  Yes    Yes  Tools for EELS analysis
nionswift-video-capture  Yes    No   Capture video from your computer's camera or a web stream.
                                     Requires conda opencv.
nionswift-experimental   Yes    Yes  Experimental tools (see project home page for details).
=======================  =====  ===  =================================================================

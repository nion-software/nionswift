:orphan:

.. include:: defs.rst
.. _installation:

|AppName| Installation
=======================
For the fastest setup, download a pre-built version that includes everything needed to run the
basic application with key plug-ins.

* `Download for macOS, Linux, or Windows <https://nion.com/swift/downloads>`_.

Installing from PyPI
--------------------
|AppName| is available on `PyPI <https://pypi.org/project/nionswift/>`_ and installs
into an isolated Python virtual environment using common Python tools.

Each approach below creates a self-contained environment so |AppName| does not interfere with
other Python software on your machine.

Requirements
~~~~~~~~~~~~
* Python 3.14 or later
* macOS 12 or later
* Windows 10 or later
* Linux — a recent distribution (Ubuntu 20.04+, Fedora 36+, or equivalent)

.. _install-pip-venv:

Using pip and venv
~~~~~~~~~~~~~~~~~~
``pip`` and ``venv`` are built into Python and work on every platform.
Install Python 3.14 or later first, then create a virtual environment and install |AppName|.

**Step 1 — Install Python 3.14+**

.. tab-set::

   .. tab-item:: macOS

      Download from `python.org <https://www.python.org/downloads/>`_ or install via Homebrew:

      .. code-block:: console

         $ brew install python@3.14

   .. tab-item:: Windows

      Download from `python.org <https://www.python.org/downloads/>`_ or install via ``winget``:

      .. code-block:: console

         > winget install Python.Python.3.14

   .. tab-item:: Linux

      Install via your distribution's package manager. For example on Debian/Ubuntu:

      .. code-block:: console

         $ sudo apt install python3.14 python3.14-venv

**Step 2 — Create a virtual environment and install**

.. tab-set::

   .. tab-item:: macOS / Linux

      .. code-block:: console

         $ python3.14 -m venv nionswift-env
         $ source nionswift-env/bin/activate
         $ python -m pip install nionswift nionswift-tool

   .. tab-item:: Windows

      .. code-block:: console

         > py -3.14 -m venv nionswift-env
         > nionswift-env\Scripts\activate
         > python -m pip install nionswift nionswift-tool

**Step 3 — Run** |AppName|

.. code-block:: console

   $ nionswift

To run |AppName| in future sessions, activate the environment first:

.. tab-set::

   .. tab-item:: macOS / Linux

      .. code-block:: console

         $ source nionswift-env/bin/activate
         $ nionswift

   .. tab-item:: Windows

      .. code-block:: console

         > nionswift-env\Scripts\activate
         > nionswift

.. _install-uv:

Using uv
~~~~~~~~
`uv <https://docs.astral.sh/uv/>`_ is a fast, modern Python environment and package manager.
It can install Python for you, so no separate Python installation step is required.

**Step 1 — Install uv**

.. tab-set::

   .. tab-item:: macOS

      Install via `Homebrew <https://brew.sh>`_:

      .. code-block:: console

         $ brew install uv

   .. tab-item:: Windows

      Install via ``winget``:

      .. code-block:: console

         > winget install astral-sh.uv

   .. tab-item:: Linux

      Install via your distribution's package manager. For example on Debian/Ubuntu:

      .. code-block:: console

         $ sudo apt install uv

      Or on Fedora:

      .. code-block:: console

         $ sudo dnf install uv

      If ``uv`` is not available in your distribution's repositories, see the
      `uv installation docs <https://docs.astral.sh/uv/getting-started/installation/>`_.

**Step 2 — Create a virtual environment and install**

``uv`` will download Python 3.14 automatically if it is not already present on your system.

.. tab-set::

   .. tab-item:: macOS / Linux

      .. code-block:: console

         $ uv venv --python 3.14 nionswift-env
         $ source nionswift-env/bin/activate
         $ uv pip install nionswift nionswift-tool

   .. tab-item:: Windows

      .. code-block:: console

         > uv venv --python 3.14 nionswift-env
         > nionswift-env\Scripts\activate
         > uv pip install nionswift nionswift-tool

**Step 3 — Run** |AppName|

.. code-block:: console

   $ nionswift

To run |AppName| in future sessions, activate the environment first:

.. tab-set::

   .. tab-item:: macOS / Linux

      .. code-block:: console

         $ source nionswift-env/bin/activate
         $ nionswift

   .. tab-item:: Windows

      .. code-block:: console

         > nionswift-env\Scripts\activate
         > nionswift

.. _install-conda:

Using conda with pip
~~~~~~~~~~~~~~~~~~~~~
If you use the `Conda <https://conda.io>`_ package manager (via
`Miniforge <https://github.com/conda-forge/miniforge>`_, Miniconda, or Anaconda),
create a dedicated environment and install |AppName| from PyPI using ``pip``.

Install Miniforge (recommended) from the
`Miniforge releases page <https://github.com/conda-forge/miniforge/releases>`_.

**Create a dedicated environment and install**

.. code-block:: console

   $ conda create -n nionswift python=3.14
   $ conda activate nionswift
   $ python -m pip install nionswift nionswift-tool

**Run** |AppName|

.. code-block:: console

   $ nionswift

To run |AppName| in future sessions:

.. code-block:: console

   $ conda activate nionswift
   $ nionswift

Installing Extensions
---------------------
Extensions add capabilities to |AppName| and are installed into the same virtual environment.
Restart |AppName| after installing an extension to load it.

.. tab-set::

   .. tab-item:: pip / venv

      .. code-block:: console

         $ python -m pip install nionswift-usim

   .. tab-item:: uv

      .. code-block:: console

         $ uv pip install nionswift-usim

   .. tab-item:: conda

      .. code-block:: console

         $ python -m pip install nionswift-usim

Browse all available extensions at `pypi.org <https://pypi.org/search/?q=nionswift>`_.

These extensions are commonly used:

=======================  =================================================================
Extension                Description
=======================  =================================================================
nionswift-usim           A STEM microscope simulator for development and offline use
nionswift-eels-analysis  Tools for EELS analysis
nionswift-video-capture  Capture video from your computer's camera or a web stream
nionswift-experimental   Experimental tools (see project home page for details)
=======================  =================================================================

Updating |AppName|
-------------------
Activate your environment and run the appropriate pip upgrade command.

.. tab-set::

   .. tab-item:: pip / venv

      .. code-block:: console

         $ python -m pip install --upgrade nionswift nionswift-tool

   .. tab-item:: uv

      .. code-block:: console

         $ uv pip install --upgrade nionswift nionswift-tool

   .. tab-item:: conda

      After activating your conda environment, use ``python -m pip`` to upgrade:

      .. code-block:: console

         $ python -m pip install --upgrade nionswift nionswift-tool

Uninstalling |AppName|
-----------------------
Remove |AppName| and its environment using the method that matches your installation.

.. tab-set::

   .. tab-item:: pip / venv

      To remove the environment and all installed packages:

      .. code-block:: console

         $ rm -rf nionswift-env

      On Windows:

      .. code-block:: console

         > rmdir /s /q nionswift-env

   .. tab-item:: uv

      To remove the environment and all installed packages:

      .. code-block:: console

         $ rm -rf nionswift-env

      On Windows:

      .. code-block:: console

         > rmdir /s /q nionswift-env

   .. tab-item:: conda

      To remove the conda environment:

      .. code-block:: console

         $ conda remove -n nionswift --all

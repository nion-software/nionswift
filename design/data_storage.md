# Nion Swift Data Storage

A project stores each data item's data, with the data item's properties, in a data file of its own, and stores its other items in its index file. This document describes how a project's file storage chooses, writes, reads, removes and loads data files, and which threads touch a data item's data. The code is in `FileStorageSystem.py`, `NDataHandler.py`, `HDF5Handler.py` and the data handling of `DataItem.py`. Tests also use `MemoryProjectStorageSystem`, which holds the same content in dictionaries.

## Terms

A **data file** holds one data item's data and its properties. It is an ndata file (`.ndata`) or an HDF5 file (`.h5`). A storage handler, `NDataHandler` or `HDF5Handler`, reads and writes one data file, and the project's storage, `FileProjectStorageSystem`, keeps one for each data item.

A project's **data folder** holds its data files. A data file's path in it is `<year>/<month>/<day>/<session>/<stem>.<extension>`, made from the data item's creation date, its session and a stem, `data_` followed by an encoding of its uuid. The date and session folders are historical, from when it was not yet known whether users would browse the data folder directly. Users are not expected to, but the folders still keep any one folder from holding every data file of a project. The storage finds data files by reading the whole data folder. A file whose stem is that of its data item is **named for** the data item.

A data item's **properties** are its persistent properties, among them its data's shape, dtype and descriptor, its calibrations, its metadata, its session and its `modified` time. Keeping the properties in the data file rather than the index file is a historical choice, which makes migrating a project slow, since a migration touches every data file, and limits a data file to formats which can hold and quickly update the properties; https://github.com/nion-software/nionswift/issues/1264 proposes moving them to the index file.

## How it works

### File type

A data item whose data takes more than 16 MiB is stored in an HDF5 file, and any other in an ndata file. HDF5 data can be read and written in part without loading all of it into memory. ndata data is read into memory as a numpy array, which supports every numpy operation, and an ndata file can be read without a third-party library. A test can set another limit, to store small data in HDF5, through the profile's `ProjectStorageSettings`, which the profile passes to index projects only.

When written or reserved data crosses the limit, the storage replaces the data item's file with one of the other type, at the path for the data item's current session. It deletes the old file, writes the properties into the new one, and then writes the data.

### What each file holds

An ndata file is an uncompressed zip of `data.npy` and `metadata.json`, which holds the properties, with the data first. Writing or reserving data rewrites the whole file in place and keeps its properties. Writing properties rewrites `metadata.json` and the zip directory after the data when the data comes first, and otherwise the whole file. Each ndata write sets the file's modification time to the data item's creation time.

An HDF5 file holds one dataset, `data`, with the properties as JSON in its `properties` attribute. Data of the dataset's shape and dtype is written into the dataset. Data of another shape or dtype, and any reserve into a file which has a dataset, deletes the file and creates it again with a new dataset, copying the `properties` attribute. Writing properties to a file which has no dataset creates an empty one of shape (0,), which reads as no data. The handler opens its h5py file on first use and keeps it open. A reshape, a reserve or a removal closes it, and the next use opens it again.

### Reading

A data item loads its data from its file when the first reference to the data is taken, and drops it when the last reference goes, once the data is written to the file. ndata data is read into memory. HDF5 data is the h5py dataset itself: a partial update writes into the file through it, and a holder of it can no longer read it once a reshape, a reserve, a storage type change or a removal has closed the file.

### Writing

When a data item's data is set or partially updated, when the data item is inserted into a project, and when its write delay ends, it writes its properties and then its data. A reserve first replaces the file's data with data of the new shape and dtype, which reads as zeros, keeping the file's properties, and then writes the properties which describe the new shape. Each change to a property rewrites all of the data item's properties. While a data item's writes are delayed, as in a transaction, it keeps its data in memory and writes its properties and data when the delay ends; a reserve still writes its data at once, and a partial update to HDF5 data still writes into the file through the dataset.

A partial update to ndata data changes the data in memory and rewrites the whole file. A partial update to HDF5 data writes the slice into the file through the dataset, and the storage then flushes the file.

Setting or partially updating data records the current session on the data item. The session chooses the folder of a file made later, by a storage type change or a restore; an existing file stays where it is.

### Removing and restoring

Removing a data item moves its file into the `trash` folder of the data folder, or deletes the file if the trash already holds one of that name. Restoring the data item, required for undo, finds the file in the trash which holds it, looking first at the files named for it, and moves that file back to the path for its creation date and session, unless a file is already at that path. The trash keeps a removed data item's data, which may be too large to keep in memory, so that undo can restore it. The trash is emptied each time the project is opened, as it historically has been; https://github.com/nion-software/nionswift/issues/123 proposes a trash which the user views and empties.

### Finding the data folder

The data folder is the folder beside the index file with the index file's name, without its extension, and " Data" appended, if it exists, and otherwise the first existing folder among those listed in the index file's `project_data_folders`. If none of them exists, it is the folder beside the index file with " Data" appended, which is made when the first data file is written. Each write of the index file records the data folder in `project_data_folders`, relative to the index file's folder when it is beside the index file.

### Loading

At load the storage reads the properties of every data file in the data folder, except files in the trash and files whose names begin with ".". Every `.h5` file is read as an HDF5 data file, and an `.ndata` file is read as an ndata data file if it is a zip which holds `data.npy`, `metadata.json` or both, and nothing else. A file whose properties or uuid cannot be read is reported as a reader error, closed and left in place. Data items are loaded from the files of the version this nionswift writes, in order of their creation time.

When a data item matches more than one file of the data item version this nionswift writes, it takes its properties and its data from the one with the newest `modified` in its properties, then the one named for the data item, then the first by path. The others are deleted. A file which cannot be deleted is reported on the `loader` log. A file of another data item version is never chosen and never deleted, since it may be the only copy another version of nionswift reads. A data item whose files are all of another version is not loaded.

### Threads

The main thread sets, reserves and partially updates a data item's data, writes its file, and removes, restores and loads data items. Acquisition and other threads queue new data and partial updates on the document model, and the main thread applies them. Computation and display threads read a data item's data through `xdata`, which may load the data from the file on that thread.

A data item's lock, `__data_ref_count_mutex` in `DataItem`, guards its loaded data, its data metadata and its data reference count. Loading data reads the file while holding the lock. A set assigns the data and its data metadata together under the lock and writes the file after releasing it. A reserve holds the lock from dropping the loaded data, through the storage's reserve and any storage type change, to loading the reserved data, and writes the properties after releasing it. `xdata` reads the data and its data metadata together under the lock, so that a display or computation thread gets both from the same set or reserve. A partial update writes into the data the item already holds, of the same shape and dtype, without the lock, since the lock guards which data and data metadata a reader takes and not the values in the data. Locks are taken in one order: a data item's lock, then its storage handler's lock, then the HDF5 file manager's and file entry's locks. Loading and reserving call into the storage while holding the data item's lock, so the storage code doesn't take that lock, since a thread taking it inside a storage lock could deadlock with one taking them in order.

### Data files log

The logger `nion.swift.data_files` records each data file created, written, reserved, moved and deleted, each storage type change, each ndata read and properties rewrite, and each HDF5 write through the dataset, all at DEBUG. Turn it on with `logging.getLogger("nion.swift.data_files").setLevel(logging.DEBUG)`, for example from the console or a debugger; its records then go to stderr through the handler the application adds to the root logger.

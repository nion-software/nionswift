"""
    A module for handle .h5 files for Swift.
"""
from __future__ import annotations

import dataclasses
import datetime
import io
import itertools
import json
import logging
import os
import pathlib
import struct
import threading
import typing
import uuid
import concurrent.futures

import h5py
import numpy
import numpy.typing
import bitshuffle
import hdf5plugin
from h5py._objects import phil

from nion.data import DataAndMetadata
from nion.swift.model import StorageHandler
from nion.swift.model import Utility
from nion.utils import DateTime
from nion.utils import Geometry
from nion.utils import Registry

if typing.TYPE_CHECKING:
    from nion.data import DataAndMetadata


PersistentDictType = typing.Dict[str, typing.Any]
_NDArray = numpy.typing.NDArray[typing.Any]

# the log of data file management: data files created, written, moved and deleted. its records are at DEBUG, so it is off
# by default. turn it on with logging.getLogger("nion.swift.data_files").setLevel(logging.DEBUG), for example from the
# console or a debugger. its records then go to the app's stderr, not to the Output panel.
data_files_logger = logging.getLogger("nion.swift.data_files")


def _normalize_step_one_slice(axis_slice: slice, axis_length: int) -> slice:
    start, stop, step = axis_slice.indices(axis_length)
    if step != 1:
        raise ValueError("HDF5 chunk writes require slices with step 1.")
    return slice(start, stop)


def _normalize_slices(slices: tuple[slice, ...], shape: typing.Sequence[int]) -> tuple[slice, ...]:
    assert len(slices) == len(shape)
    return tuple(_normalize_step_one_slice(axis_slice, axis_length) for axis_slice, axis_length in zip(slices, shape))


_BITSHUFFLE_FILTER_ID = 32008


def _default_bitshuffle_block_size(itemsize: int) -> int:
    """Return bitshuffle's default block size (in elements): ~8 kB, multiple of 8, at least 128."""
    block_size = (8192 // itemsize) // 8 * 8
    return max(block_size, 128)


def _dataset_uses_bitshuffle(dataset: typing.Any) -> bool:
    plist = dataset.id.get_create_plist()
    return any(plist.get_filter(i)[0] == _BITSHUFFLE_FILTER_ID for i in range(plist.get_nfilters()))


def make_directory_if_needed(directory_path: str) -> None:
    """
        Make the directory path, if needed.
    """
    if os.path.exists(directory_path):
        if not os.path.isdir(directory_path):
            raise OSError("Path is not a directory:", directory_path)
    else:
        os.makedirs(directory_path)


def get_write_chunk_shape_for_data(data_shape: DataAndMetadata.ShapeType, data_dtype: numpy.typing.DTypeLike, data_descriptor: DataAndMetadata.DataDescriptor, target_chunk_size: int=240000) -> typing.Optional[DataAndMetadata.ShapeType]:
    """
    Calculate an appropriate write chunk shape for a given data shape and dtype.

    The default target chunk size is 240 kB which seems to be a sweet spot according to benchmarks.
    The algorithm assumes that the data is c-contiguous in memory.

    If the total number of chunks that the calculated chunk shape would lead to is less than 100 (i.e. the file will
    be less than 24 MB in size) or if the data shape is not suitable for chunking, return None.

    The chunk shape is calculated according to the following rules:
    - Use a quarter of the data axis (i.e. the last axis for 1D data and the last two axis for 2D data)
      if the number of elements in the last two or last three dimensions is large enough. If not, use
      the entire data axis.
    - Work backwards from the last axis and increse the number of elements per axis until prod(chunk_chape) >= target_chunk size.
      A chunk cannot exceed the number of elements of an axis, so if one dimension is "full", move to the next axis.
    - The slow scan axis and the sequence axis when acquiring a sequence of SIs or 4D STEM images can never be chunked (i.e.
      chunk shape == 1 for these axis).
    - The sequence axis in a sequence of 1D or 2D data can be chunked.
    """
    data_dtype = numpy.dtype(data_dtype)

    is_2d_data = data_descriptor.datum_dimension_count == 2

    target_chunk_size = int(round(target_chunk_size / data_dtype.itemsize))
    divisors = [1] * len(data_shape)
    if len(data_shape) > 2 and (
        (numpy.prod(data_shape[-3:]) > 8 * target_chunk_size and is_2d_data) or
        (numpy.prod(data_shape[-2:]) > 2 * target_chunk_size)):
        if is_2d_data:
            divisors[-2:] = [4, 4]
        else:
            divisors[-1] = 4

    chunk_size = 1
    counter = len(data_shape)
    chunk_shape = [1] * len(data_shape)
    while chunk_size < target_chunk_size and counter > 0:
        counter -= 1
        chunk_size *= data_shape[counter] // divisors[counter]
        chunk_shape[counter] = data_shape[counter] // divisors[counter]

    if chunk_size == 0: # This means one of the input dimensions was "0", so chunking cannot be used
        return None

    chunk_size //= chunk_shape[counter]
    remaining_elements = min(max(target_chunk_size // chunk_size, 1), data_shape[counter])
    chunk_shape[counter] = int(remaining_elements)

    n_chunks = 1
    for i in range(len(chunk_shape)):
        n_chunks *= data_shape[i] // chunk_shape[i]
    if n_chunks < 100:
        return None

    # Do not allow chunking of the slow scan axis or the sequence axis when acquiring a sequence of SIs or 4D STEM images.
    if is_2d_data and len(data_shape) > 3:
        chunk_shape[:-3] = [1] * (len(data_shape) - 3)
    elif not is_2d_data and len(data_shape) > 2:
        chunk_shape[:-2] = [1] * (len(data_shape) - 2)

    return tuple(chunk_shape)


@dataclasses.dataclass
class _HDF5ChunkCacheEntry:
    """A partially filled buffer for a single HDF5 dataset chunk, awaiting the remaining data before it can be flushed.

    data holds the in-progress contents of one dataset chunk. Its shape matches the chunk's actual on-disk shape,
    which may be smaller than the dataset's nominal chunk shape at the edges of the dataset. mask tracks which
    elements of data have already been written; once mask is entirely True the chunk is complete and can be
    written to the file with write_direct_chunk.
    """
    data: _NDArray
    mask: numpy.typing.NDArray[numpy.bool_]


class _ChunkBufferPool:
    """A thread-safe pool of reusable chunk buffers.

    Allocating a fresh multi-MB buffer for every chunk is expensive, mostly because of page faults on first touch
    (on Windows each large allocation is new virtual memory). Reusing buffers avoids that. The pool keeps at most
    max_buffers idle buffers; any additional released buffers are left to the garbage collector.
    """

    def __init__(self, max_buffers: int) -> None:
        self.__lock = threading.Lock()
        self.__max_buffers = max_buffers
        self.__buffers: dict[tuple[tuple[int, ...], str], list[_NDArray]] = dict()
        self.__count = 0

    def acquire(self, shape: tuple[int, ...], dtype: numpy.dtype[typing.Any]) -> _NDArray:
        key = (tuple(shape), dtype.str)
        with self.__lock:
            buffers = self.__buffers.get(key)
            if buffers:
                self.__count -= 1
                return buffers.pop()
        return numpy.empty(shape, dtype=dtype)

    def release(self, buffer: _NDArray) -> None:
        key = (tuple(buffer.shape), buffer.dtype.str)
        with self.__lock:
            if self.__count < self.__max_buffers:
                self.__buffers.setdefault(key, list()).append(buffer)
                self.__count += 1

    def clear(self) -> None:
        with self.__lock:
            self.__buffers.clear()
            self.__count = 0


_HDF5FilePointer = typing.Any


class HDF5FileEntry:
    def __init__(self, path: pathlib.Path) -> None:
        self.__lock = threading.RLock()
        self.__path = path
        self.__fp: typing.Optional[_HDF5FilePointer] = None
        self._count = 0

    @property
    def fp(self) -> _HDF5FilePointer:
        with self.__lock:
            self.open()
            assert self.__fp
            return self.__fp

    def open(self) -> None:
        with self.__lock:
            if not self.__fp:
                self.__path.parent.mkdir(parents=True, exist_ok=True)
                self.__fp = h5py.File(self.__path, "a")

    def close(self) -> None:
        with self.__lock:
            if self.__fp:
                self.__fp.close()
            self.__fp = None


class HDF5FileManager:
    def __init__(self) -> None:
        self.__file_entries: typing.Dict[pathlib.Path, HDF5FileEntry] = dict()
        self.__lock = threading.RLock()

    def _clear(self) -> None:
        # for tests only
        self.__file_entries.clear()

    @property
    def _open_count(self) -> int:
        return len(self.__file_entries.items())

    def open(self, path: pathlib.Path) -> HDF5FileEntry:
        with self.__lock:
            if not path in self.__file_entries:
                self.__file_entries[path] = HDF5FileEntry(path)
            self.__file_entries[path]._count += 1
            return self.__file_entries[path]

    def close(self, path: pathlib.Path) -> None:
        with self.__lock:
            self.__file_entries[path]._count -= 1
            if self.__file_entries[path]._count == 0:
                self.__file_entries.pop(path).close()

    def force_close(self, path: pathlib.Path) -> None:
        with self.__lock:
            if path in self.__file_entries:
                self.__file_entries[path].close()


_file_manager = HDF5FileManager()


class HDF5Handler(StorageHandler.StorageHandler):
    count = 0  # useful for detecting leaks in tests
    open = 0  # useful for detecting unclosed files

    def __init__(self, file_path: typing.Union[str, pathlib.Path], max_workers=None) -> None:
        self.__file_path = str(file_path)
        self.__lock = threading.RLock()
        self.__file = _file_manager.open(pathlib.Path(self.__file_path))
        self.__dataset: typing.Any = None
        self.__chunk_cache: dict[tuple[int, ...], _HDF5ChunkCacheEntry] = dict()
        self.__write_futures: set[concurrent.futures.Future] = set()
        # The workers assemble (copy), compress and write chunks. Copying (numpy) and compression (bitshuffle >= 0.5,
        # ideally built without OpenMP) release the GIL and scale with the number of workers; the final
        # write_direct_chunk is serialized by h5py's phil lock. Benchmarks with ~4.8 MB chunks show that up to 20 workers
        # still result in moderate speedup, but it starts saturating around that. The test system only has 20 CPU threads,
        # so that might also explain the saturation. However, a default of 24 or the number of CPU threads should be
        # a decent starting point.
        max_workers = max_workers or min(24, os.cpu_count() or 8)
        self.__executor = concurrent.futures.ThreadPoolExecutor(max_workers=max_workers)
        # reusable chunk buffers; more than workers so that buffers released by finishing workers can be picked up
        # by the next tasks without allocating.
        self.__buffer_pool = _ChunkBufferPool(max_buffers=2 * max_workers)
        self._write_count = 0
        HDF5Handler.count += 1

    def close(self) -> None:
        HDF5Handler.count -= 1
        self.__executor.shutdown()
        self.__write_futures.clear()
        self.__chunk_cache.clear()
        self.__buffer_pool.clear()
        self.__close_fp()
        _file_manager.close(pathlib.Path(self.__file_path))

    @property
    def factory(self) -> StorageHandler.StorageHandlerFactoryLike:
        return HDF5HandlerFactory()

    @property
    def storage_handler_type(self) -> str:
        return "hdf5"

    # called before the file is moved; close but don't count.
    def prepare_move(self) -> None:
        with self.__lock:
            self.__close_fp()
            _file_manager.force_close(pathlib.Path(self.__file_path))

    @property
    def reference(self) -> str:
        return self.__file_path

    @property
    def is_valid(self) -> bool:
        return True

    # For testing
    @property
    def _dataset(self) -> typing.Any:
        return self.__dataset

    @_dataset.setter
    def _dataset(self, value: typing.Any) -> None:
        self.__dataset = value

    @property
    def _file(self) -> HDF5FileEntry:
        return self.__file

    def get_extension(self) -> str:
        return ".h5"

    def __write_properties_to_dataset(self, properties: PersistentDictType) -> None:
        with self.__lock:
            assert self.__dataset is not None

            class JSONEncoder(json.JSONEncoder):
                def default(self, obj: typing.Any) -> typing.Any:
                    if isinstance(obj, Geometry.IntPoint) or isinstance(obj, Geometry.IntSize) or isinstance(obj, Geometry.IntRect) or isinstance(obj, Geometry.FloatPoint) or isinstance(obj, Geometry.FloatSize) or isinstance(obj, Geometry.FloatRect):
                        return tuple(obj)
                    else:
                        return json.JSONEncoder.default(self, obj)

            json_io = io.StringIO()
            json.dump(Utility.clean_dict(properties), json_io, cls=JSONEncoder)
            json_str = json_io.getvalue()

            self.__dataset.attrs["properties"] = json_str

    def __ensure_dataset(self) -> None:
        with self.__lock:
            if self.__dataset is None:
                if "data" in self.__file.fp:
                    self.__dataset = self.__file.fp["data"]
                else:
                    self.__dataset = self.__file.fp.create_dataset("data", data=numpy.empty((0,)))
                    data_files_logger.debug("data file created: %s, file type HDF5, shape %s, dtype %s", self.__file_path, self.__dataset.shape, self.__dataset.dtype)

    def __queue_threaded_write(self, dataset: typing.Any, chunk_offset: tuple[int, ...], is_bitshuffled: bool, *,
                               chunk_data: typing.Optional[_NDArray] = None,
                               source_view: typing.Optional[_NDArray] = None,
                               chunk_shape: typing.Optional[tuple[int, ...]] = None,
                               chunk_dtype: typing.Optional[numpy.dtype[typing.Any]] = None,
                               valid_local_slices: typing.Optional[tuple[slice, ...]] = None) -> threading.Event:
        """Queue a chunk to be assembled, compressed and written by the thread pool.

        Either pass chunk_data, a complete chunk buffer that will not be modified anymore, or source_view (a view
        into the caller's data), chunk_shape, chunk_dtype and valid_local_slices. In the latter case the worker
        copies source_view into a pooled chunk buffer; numpy releases the GIL for this copy, so the copies of
        several chunks run in parallel.

        Returns an event that is set once the worker no longer needs source_view (i.e. it has been copied). The
        caller must wait for it before the source data may be modified.
        """
        copied = threading.Event()
        buffer_pool = self.__buffer_pool

        def write_chunk() -> None:
            pooled_buffer: typing.Optional[_NDArray] = None
            try:
                if chunk_data is not None:
                    data = chunk_data
                else:
                    assert source_view is not None and chunk_shape is not None and chunk_dtype is not None and valid_local_slices is not None
                    pooled_buffer = buffer_pool.acquire(chunk_shape, chunk_dtype)
                    if source_view.shape != chunk_shape:
                        # edge chunk: the out-of-bounds part is never read back, but zero it to get deterministic
                        # (and well compressible) file contents instead of stale data from a reused buffer.
                        pooled_buffer.fill(0)
                    pooled_buffer[valid_local_slices] = source_view
                    data = pooled_buffer
            finally:
                copied.set()
            try:
                payload: typing.Any
                if is_bitshuffled:
                    # write_direct_chunk bypasses the HDF5 filter pipeline, so the 12 byte header that the
                    # bitshuffle HDF5 filter expects (uncompressed size, block size) must be added manually.
                    block_size = _default_bitshuffle_block_size(data.dtype.itemsize)
                    compressed_chunk_data = bitshuffle.compress_lz4(data, block_size)
                    header = struct.pack(">QI", data.nbytes, block_size * data.dtype.itemsize)
                    if pooled_buffer is not None:
                        # the uncompressed buffer is not needed anymore; make it available to other workers early.
                        buffer_pool.release(pooled_buffer)
                        pooled_buffer = None
                    # assemble header and compressed data with a single numpy copy (which releases the GIL) instead
                    # of tobytes() + bytes concatenation (two copies, both holding the GIL).
                    header_size = len(header)
                    payload = numpy.empty(header_size + compressed_chunk_data.nbytes, dtype=numpy.uint8)
                    payload[:header_size] = numpy.frombuffer(header, dtype=numpy.uint8)
                    payload[header_size:] = compressed_chunk_data
                else:
                    # write_direct_chunk accepts any object implementing the buffer protocol; no need for bytes.
                    payload = numpy.ascontiguousarray(data)
                with phil:
                    dataset.id.write_direct_chunk(chunk_offset, payload)
            finally:
                if pooled_buffer is not None:
                    buffer_pool.release(pooled_buffer)

        future = self.__executor.submit(write_chunk)
        self.__write_futures.add(future)
        future.add_done_callback(self.__write_futures.discard)
        return copied

    def _wait_for_pending_writes(self) -> None:
        """Wait for all pending threaded writes to complete."""
        concurrent.futures.wait(list(self.__write_futures))

    def write_hdf5_chunks(self, source_data: _NDArray, source_slices: tuple[slice, ...], target_slices: tuple[slice, ...], wait_for_copy: bool = False) -> None:
        """Write source_data[source_slices] into target_dataset[target_slices] using direct chunk writes.

        The target dataset is divided into a grid of on-disk chunks. Chunks that are fully covered by
        target_slices are copied from source_data, compressed and written by the thread pool using
        target_dataset.id.write_direct_chunk. Chunks that are only partially covered are accumulated in
        self.__chunk_cache (keyed by chunk offset) across successive calls; once a cached chunk becomes
        fully covered, it is written and removed from the cache. This assumes target_slices and
        source_slices use a step of 1 in every dimension.

        The data of fully covered chunks is copied out of source_data by the workers. If wait_for_copy is True,
        this method returns only once all of these copies are done, so the caller may modify source_data
        afterwards. If wait_for_copy is False (the default), the method returns right after queuing the chunks and
        source_data must not be modified until the pending writes are done (see _wait_for_pending_writes). In both
        cases compression and writing may still be in progress on return.
        """
        target_dataset = self.__dataset
        chunk_shape = target_dataset.chunks
        dataset_shape = target_dataset.shape
        dataset_dtype = target_dataset.dtype
        dimension_count = len(dataset_shape)
        source_slices = _normalize_slices(source_slices, source_data.shape)
        target_slices = _normalize_slices(target_slices, dataset_shape)

        # if the dataset is not chunked, fall back to a plain slice assignment.
        if chunk_shape is None:
            target_dataset[target_slices] = source_data[source_slices]
            return

        chunk_shape = tuple(chunk_shape)

        # determine once per call whether chunks must be bitshuffle-compressed manually.
        with phil:
            is_bitshuffled = _dataset_uses_bitshuffle(target_dataset)

        # determine the range of chunk indices, in each dimension, that overlap target_slices.
        chunk_index_ranges = list()
        for dimension_index in range(dimension_count):
            first_chunk_index = target_slices[dimension_index].start // chunk_shape[dimension_index]
            last_chunk_index = (target_slices[dimension_index].stop - 1) // chunk_shape[dimension_index]
            chunk_index_ranges.append(range(first_chunk_index, last_chunk_index + 1))

        # events of the chunks whose data is copied out of source_data by the workers; if wait_for_copy is True, wait
        # for all of them before returning so that the caller may modify source_data afterwards.
        copy_events: list[threading.Event] = list()
        try:
            for chunk_index in itertools.product(*chunk_index_ranges):
                chunk_offset = tuple(chunk_index[d] * chunk_shape[d] for d in range(dimension_count))
                # the actual on-disk chunk shape may be smaller than the nominal chunk shape at the dataset edges.
                chunk_actual_shape = tuple(min(chunk_shape[d], dataset_shape[d] - chunk_offset[d]) for d in range(dimension_count))
                chunk_slices = tuple(slice(chunk_offset[d], chunk_offset[d] + chunk_actual_shape[d]) for d in range(dimension_count))

                fully_overlapping = all(
                    target_slices[d].start <= chunk_slices[d].start and target_slices[d].stop >= chunk_slices[d].stop
                    for d in range(dimension_count)
                )

                # the region, in target dataset coordinates, where the chunk and target_slices overlap.
                overlap_slices = tuple(
                    slice(max(target_slices[d].start, chunk_slices[d].start), min(target_slices[d].stop, chunk_slices[d].stop))
                    for d in range(dimension_count)
                )
                # the corresponding region in source_data, derived from the offset between target_slices and source_slices.
                source_overlap_slices = tuple(
                    slice(
                        source_slices[d].start + (overlap_slices[d].start - target_slices[d].start),
                        source_slices[d].start + (overlap_slices[d].stop - target_slices[d].start)
                    )
                    for d in range(dimension_count)
                )

                # the raw buffer passed to write_direct_chunk must always match the dataset's nominal chunk
                # shape, even at the dataset edges where only a portion of the chunk lies within the dataset
                # bounds; the out-of-bounds portion is never read back and its contents are irrelevant.
                valid_local_slices = tuple(slice(0, chunk_actual_shape[d]) for d in range(dimension_count))

                if fully_overlapping:
                    # the entire (in-bounds) chunk is covered by this call; a worker copies it from source_data into
                    # a pooled full-size buffer, compresses and writes it. discard any pending partial data for it.
                    copy_events.append(self.__queue_threaded_write(
                        target_dataset, chunk_offset, is_bitshuffled,
                        source_view=source_data[source_overlap_slices],
                        chunk_shape=chunk_shape,
                        chunk_dtype=dataset_dtype,
                        valid_local_slices=valid_local_slices))
                    self.__chunk_cache.pop(chunk_offset, None)
                    continue

                # the chunk is only partially covered by this call; accumulate it in the cache.
                chunk_cache_entry = self.__chunk_cache.get(chunk_offset)
                if chunk_cache_entry is None:
                    # seed the cache entry with the chunk's existing on-disk data so unwritten elements are preserved.
                    existing_chunk_data = numpy.array(target_dataset[chunk_slices], dtype=dataset_dtype)
                    chunk_buffer = numpy.zeros(chunk_shape, dtype=dataset_dtype)
                    chunk_buffer[valid_local_slices] = existing_chunk_data
                    # the portion of the buffer beyond the dataset bounds never receives real data, so mark it
                    # as already complete; only the in-bounds portion needs to be tracked as unwritten.
                    chunk_mask = numpy.ones(chunk_shape, dtype=numpy.bool_)
                    chunk_mask[valid_local_slices] = False
                    chunk_cache_entry = _HDF5ChunkCacheEntry(chunk_buffer, chunk_mask)
                    self.__chunk_cache[chunk_offset] = chunk_cache_entry

                local_slices = tuple(
                    slice(overlap_slices[d].start - chunk_offset[d], overlap_slices[d].stop - chunk_offset[d])
                    for d in range(dimension_count)
                )
                chunk_cache_entry.data[local_slices] = source_data[source_overlap_slices]
                chunk_cache_entry.mask[local_slices] = True

                if bool(chunk_cache_entry.mask.all()):
                    # the cache entry is removed below, so its buffer is handed over to the worker.
                    self.__queue_threaded_write(target_dataset, chunk_offset, is_bitshuffled, chunk_data=chunk_cache_entry.data)
                    del self.__chunk_cache[chunk_offset]
        finally:
            if wait_for_copy:
                for copy_event in copy_events:
                    copy_event.wait()

    def write_data_partial(self, data: _NDArray, data_descriptor: DataAndMetadata.DataDescriptor, file_datetime: datetime.datetime, target_slices: tuple[slice, ...], source_slices: tuple[slice, ...]) -> None:
        with self.__lock:
            assert data is not None
            json_properties = None
            normalized_source_slices = _normalize_slices(source_slices, data.shape)
            if not "data" in self.__file.fp:
                dataset_shape = tuple(
                    max(
                        target_slice.stop if target_slice.stop is not None else (target_slice.start or 0) + (normalized_source_slices[index].stop - normalized_source_slices[index].start),
                        data.shape[index]
                    )
                    for index, target_slice in enumerate(target_slices)
                )
                # For compressed storage, we need to choose a larger chunk size for optimal performance. Generally,
                # larger seems better, but we don't want to go too large. 4.8 MB seems to be a good compromise.
                chunks = get_write_chunk_shape_for_data(dataset_shape, data.dtype, data_descriptor, target_chunk_size=4800000)
                self.__dataset = self.__file.fp.require_dataset("data", shape=dataset_shape, dtype=data.dtype, chunks=chunks, compression=hdf5plugin.Bitshuffle(cname="lz4"))
            else:
                if self.__dataset is None:
                    self.__dataset = self.__file.fp["data"]
                if self.__dataset.dtype != data.dtype:
                    json_properties = self.__dataset.attrs.get("properties", "")
                    dataset_shape = self.__dataset.shape
                    self.__close_fp()
                    os.remove(self.__file_path)
                    # For compressed storage, we need to choose a larger chunk size for optimal performance. Generally,
                    # larger seems better, but we don't want to go too large. 4.8 MB seems to be a good compromise.
                    chunks = get_write_chunk_shape_for_data(dataset_shape, data.dtype, data_descriptor, target_chunk_size=4800000)
                    self.__dataset = self.__file.fp.require_dataset("data", shape=dataset_shape, dtype=data.dtype, chunks=chunks, compression=hdf5plugin.Bitshuffle(cname="lz4"))
                    if json_properties is not None:
                        self.__dataset.attrs["properties"] = json_properties
        self.write_hdf5_chunks(data, source_slices, target_slices)
            # self.__file.fp.flush()

    def write_data(self, data: _NDArray, data_descriptor: DataAndMetadata.DataDescriptor, file_datetime: datetime.datetime) -> None:
        with self.__lock:
            assert data is not None
            json_properties = None
            # handle three cases:
            #   1 - 'data' doesn't yet exist (require_dataset)
            #   2 - 'data' exists but is a different size (delete, then require_dataset)
            #   3 - 'data' exists and is the same size (overwrite)
            if not "data" in self.__file.fp:
                # case 1
                chunks = get_write_chunk_shape_for_data(data.shape, data.dtype, data_descriptor)
                self.__dataset = self.__file.fp.require_dataset("data", shape=data.shape, dtype=data.dtype, chunks=chunks)
                data_files_logger.debug("data file created: %s, file type HDF5, shape %s, dtype %s", self.__file_path, data.shape, data.dtype)
            else:
                if self.__dataset is None:
                    self.__dataset = self.__file.fp["data"]
                if self.__dataset.shape != data.shape or self.__dataset.dtype != data.dtype:
                    # case 2
                    json_properties = self.__dataset.attrs.get("properties", "")
                    self.__close_fp()
                    os.remove(self.__file_path)
                    data_files_logger.debug("data file deleted: %s, file type HDF5, reason data of another shape or dtype written", self.__file_path)
                    chunks = get_write_chunk_shape_for_data(data.shape, data.dtype, data_descriptor)
                    self.__dataset = self.__file.fp.require_dataset("data", shape=data.shape, dtype=data.dtype, chunks=chunks)
                    data_files_logger.debug("data file created: %s, file type HDF5, shape %s, dtype %s", self.__file_path, data.shape, data.dtype)
            if id(data) == id(self.__dataset):
                # the dataset already holds the data, written into the file through it, as a partial update is. this is
                # on the path of each partial update, so it adds no more than the logger's own level check.
                data_files_logger.debug("data written through its dataset: %s, file type HDF5", self.__file_path)
            else:
                self.__dataset[:] = data
                self._write_count += 1
                data_files_logger.debug("data written: %s, file type HDF5, shape %s, dtype %s", self.__file_path, data.shape, data.dtype)
            if json_properties is not None:
                self.__dataset.attrs["properties"] = json_properties
            self.__file.fp.flush()

    def reserve_data(self, data_shape: DataAndMetadata.ShapeType, data_dtype: numpy.typing.DTypeLike, data_descriptor: DataAndMetadata.DataDescriptor, file_datetime: datetime.datetime) -> None:
        # reserve data of the given shape and dtype, filled with zeros
        with self.__lock:
            json_properties = None
            # first read existing properties and then close existing data set and file.
            if "data" in self.__file.fp:
                if self.__dataset is None:
                    self.__dataset = self.__file.fp["data"]
                json_properties = self.__dataset.attrs.get("properties", "")
                self.__close_fp()
                os.remove(self.__file_path)
                data_files_logger.debug("data file deleted: %s, file type HDF5, reason data reserved", self.__file_path)
                self.__file.open()
            # For compressed storage, we need to choose a larger chunk size for optimal performance. Generally,
            # larger seems better, but we don't want to go too large. 4.8 MB seems to be a good compromise.
            # reserve the data
            chunks = get_write_chunk_shape_for_data(data_shape, data_dtype, data_descriptor, target_chunk_size=4800000)
            self.__dataset = self.__file.fp.require_dataset("data", shape=data_shape, dtype=data_dtype, fillvalue=0, chunks=chunks, compression=hdf5plugin.Bitshuffle(cname="lz4"))
            if json_properties is not None:
                self.__dataset.attrs["properties"] = json_properties
            self.__file.fp.flush()
            if data_files_logger.isEnabledFor(logging.DEBUG):
                dtype = numpy.dtype(data_dtype)
                data_files_logger.debug("data file created: %s, file type HDF5, shape %s, dtype %s", self.__file_path, data_shape, dtype)
                data_files_logger.debug("data reserved: %s, file type HDF5, shape %s, dtype %s", self.__file_path, data_shape, dtype)

    def write_properties(self, properties: PersistentDictType, file_datetime: datetime.datetime) -> None:
        with self.__lock:
            self.__ensure_dataset()
            self.__write_properties_to_dataset(properties)
            self.__file.fp.flush()

    def read_properties(self) -> PersistentDictType:
        with self.__lock:
            self.__ensure_dataset()
            json_properties = self.__dataset.attrs.get("properties", "")
            return typing.cast(PersistentDictType, json.loads(json_properties))

    def read_data(self) -> typing.Optional[_NDArray]:
        with self.__lock:
            self.__ensure_dataset()
            if self.__dataset.shape == (0, ):
                return None
            return typing.cast(typing.Optional[_NDArray], self.__dataset)

    def remove(self) -> None:
        self.__close_fp()
        if os.path.isfile(self.__file_path):
            os.remove(self.__file_path)
            data_files_logger.debug("data file deleted: %s, file type HDF5", self.__file_path)

    def __close_fp(self) -> None:
        self.__dataset = None
        self.__file.close()


class HDF5HandlerFactory(StorageHandler.StorageHandlerFactoryLike):

    def get_storage_handler_type(self) -> str:
        return "hdf5"

    def is_matching(self, file_path: str) -> bool:
        if file_path.endswith(".h5") and os.path.exists(file_path):
            return True
        return False

    def make(self, file_path: pathlib.Path) -> StorageHandler.StorageHandler:
        return HDF5Handler(self.make_path(file_path))

    def make_path(self, file_path: pathlib.Path) -> str:
        return str(file_path.with_suffix(self.get_extension()))

    def get_extension(self) -> str:
        return ".h5"


def _create_dataset(data_group: typing.Any, dataset_id: str, data: numpy.typing.NDArray[typing.Any]) -> typing.Any:
    data_shape = data.shape

    # create the dataset, preallocate space.
    ds = data_group.create_dataset(dataset_id, shape=data_shape, dtype=data.dtype)

    # search for the chunk size by iterating backwards through the shape and finding the
    # largest chunk size that is less than 64MB.
    index_count = 0
    chunk_size = 1
    for n in reversed(data_shape):
        if chunk_size * n > 64 * 1024 * 1024:
            break
        index_count += 1
        chunk_size *= n

    # iterate over the remaining dimensions so that we can write the data in chunks.
    for index in numpy.ndindex(*data_shape[:len(data_shape) - index_count]):
        selection = tuple(index) + (slice(None),) * index_count
        ds[selection] = data[selection]

    return ds


class HDFImportExportDriver:
    def __init__(self) -> None:
        pass

    def read_data(self, file_path: pathlib.Path, storage_handler_provider: StorageHandler.StorageHandlerProvider) -> StorageHandler.StorageHandlerImportData:
        storage_handlers = list[StorageHandler.StorageHandler]()
        uuid_map = dict[uuid.UUID, uuid.UUID]()
        items = list[PersistentDictType]()
        fp = h5py.File(file_path, "r")
        if "data" in fp:
            data_group = fp["data"]
            for key in sorted(data_group.keys()):
                ds = data_group[key]
                data_item_uuid = uuid.uuid4()
                data_item_properties = json.loads(ds.attrs["properties"])
                data_item_data = ds
                if "uuid" in data_item_properties:
                    uuid_map[uuid.UUID(data_item_properties["uuid"])] = data_item_uuid
                data_item_properties["uuid"] = str(data_item_uuid)
                is_sequence = data_item_properties.get("is_sequence", False)
                collection_dimension_count = data_item_properties.get("collection_dimension_count", 0)
                datum_dimension_count = data_item_properties.get("datum_dimension_count", 0)
                data_descriptor = DataAndMetadata.DataDescriptor(is_sequence, collection_dimension_count, datum_dimension_count)
                assert data_descriptor.expected_dimension_count == len(ds.shape)
                storage_handler_attributes = StorageHandler.StorageHandlerAttributes(
                    data_item_uuid,
                    DateTime.utcnow(),
                    data_item_properties.get("session_id", None),
                    ds.nbytes
                )
                storage_handler = storage_handler_provider.make_storage_handler(storage_handler_attributes)
                storage_handler.write_data(data_item_data, data_descriptor, storage_handler_attributes.created_local)
                storage_handler.write_properties(data_item_properties, storage_handler_attributes.created_local)
                storage_handlers.append(storage_handler)
        if "index" in fp:
            index_group = fp["index"]
            for key in sorted(index_group.attrs.keys()):
                items.append(json.loads(index_group.attrs[key]))
        fp.close()
        return StorageHandler.StorageHandlerImportData(storage_handlers, uuid_map, items)

    def write_display_item(self, path: pathlib.Path, items: typing.Sequence[StorageHandler.StorageHandlerExportItem]) -> None:
        path.unlink(missing_ok=True)
        fp = h5py.File(path, "a")
        index_group = fp.create_group("index")
        data_group = fp.create_group("data")
        data_index = 0
        for index, item in enumerate(items):
            index_group.attrs["1"] = json.dumps(item.write_to_dict())
            for data_item in item.data_items:
                ds = _create_dataset(data_group, str(data_index), data_item.data)
                ds.attrs["properties"] = json.dumps(data_item.write_to_dict())
                data_index += 1
        fp.close()


class HDFImportExportDriverFactory:
    driver_id = "nhdf-io-handler"
    title = "NData HDF"
    extensions = ["nhdf"]

    def make_import_export_driver(self) -> HDFImportExportDriver:
        return HDFImportExportDriver()


Registry.register_component(HDFImportExportDriverFactory(), {"import-export-driver-factory"})


"""
Architectural Decision Records.

ADR 2024-02-19. Do not use Single Writer Multiple Reader (SWMR) mode for HDF5 files. This requires the writing process
to set the flag and we don't have control of the writers outside of our process. In addition, the docs curently say that
SWMR is not supported on Windows.
"""

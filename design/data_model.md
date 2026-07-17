# Nion Data Model

## Annotated Array

An **annotated array** is one complete unit of data: an underlying array, array descriptor, and array metadata. The implementation class name is `AnnotatedArray`; text uses "annotated array"; "underlying array" always refers to the raw value buffer inside an annotated array. This section describes the annotated array model in two parts: the current implementation state and the planned state.

### Current Implementation

This section uses annotated-array and axis-group terminology where possible, although the current implementation calls an annotated array a `DataAndMetadata` or `xdata`.

An annotated array is organized into three ordered sections: an optional sequence axis of rank 1, an optional collection axis group of rank 1 or 2, and a signal axis group of rank 0, 1, 2.

An annotated array holds values of type scalar, complex, RGB, or RGBA.

Each axis has a single calibration associated with it. The calibration may be an identity calibration.

### Planned Implementation

The planned annotated array model specifies an ordered list of axis groups, each with a rank, and a value type.

Value types are scalar, complex, RGB, RGBA, or fixed-length vector (1/2/3).

An annotated array always contains at least one axis group. All axis groups must have at least one axis except the final axis group may have zero.

Coordinate systems are physical coordinate spaces typically representing an orientation of axes in space.

Coordinate mappings are mappings from the index coordinate space of an axis group into calibrated coordinates.

Each axis group has zero or more associated coordinate mappings. One coordinate mapping may be designated the primary coordinate mapping.

Each axis group designates the coordinate system of its index coordinate space. The designated coordinate system may be null, indicating that the coordinate system is unknown.

Axis groups in different annotated arrays are correlated when they reference the same coordinate system.

Within a coordinate mapping, each axis has exactly one associated calibration or coordinate array.

An annotated array contains an underlying array, array descriptor, and array metadata.

The array descriptor contains the intrinsic fields used to interpret the array.

The array metadata contains a creation time, extension records, and free-form metadata.

An array header packages an array descriptor, storage data type, and array metadata.

Future revisions may expand the value types and/or support variable length (ragged) value types.

### Terms and Definitions

An **annotated array** is one complete unit of data: an underlying array, array descriptor, and array metadata.

An **array header** is a utility value containing an array descriptor, storage data type, and array metadata without an underlying array.

An **array descriptor** contains the intrinsic fields required to interpret an underlying array.

An **intrinsic field** is information whose semantics and invariants are part of the annotated array model, such as axis groups, coordinate mappings, coordinate system references, and intensity calibrations.

**Array metadata** is contextual information that travels with an annotated array but is not required to interpret its underlying array.

An **extension record** is versioned, code-interpreted array metadata whose semantics are owned outside the fundamental annotated array model. Examples are acquisition coordinate context and computation provenance.

**Free-form metadata** is information that travels with an annotated array without a machine-enforced schema and is not interpreted by the annotated array model.

An **axis group** is an ordered group of axes in an annotated array. The rank of an axis group is the number of axes in the group.

The **signal axis group** is the final axis group in an annotated array. *Note on nomenclature:* "signal" is not a perfect term - axes outside the signal axis group may also carry meaningful signal - but it is the least bad of the candidates considered and a clear improvement over the previous term "datum," which read as surveying jargon and was an awkward singular of "data."

A **value type** is one of the supported value types: scalar, complex, RGB, RGBA, or vector.

A **coordinate system** represents a physical coordinate space, typically defined by an orientation of axes, and contains an ordered list of coordinate axes. Each coordinate system has a unique identifier that solely determines its identity; systems with identical axes are distinct if their identifiers differ. Coordinate systems are shared objects and may be referenced by axis groups in multiple annotated arrays.

A **coordinate system axis** is a per-dimension component of a coordinate system: a name and optional direction metadata. Coordinate system axes carry no units; units belong to calibrations.

A **coordinate system graph** is the set of coordinate system definitions and the current coordinate system transforms. The coordinate system graph is maintained outside annotated arrays, at the instrument level.

A **calibration** is a structure containing `scale`, `offset`, and `units` used to map index values to calibrated values using the formula `x' = x * scale + offset`. A calibration is a linear transform on a single axis. A calibration exists within a coordinate mapping, one per axis. Calibrations support sampled (uniformly spaced) axes.

A **coordinate array** is a structure containing arrays that map index values to coordinate values. Coordinate arrays support non-sampled (non-uniformly spaced) axes.

An **index coordinate space** is the space of index values of an axis group.

A **coordinate mapping** is a mapping from the index coordinate space of an axis group into calibrated coordinates, consisting of one calibration or coordinate array per axis. An axis group may have zero or more coordinate mappings; coordinate mappings are coherent across all axes of the group.

A **primary coordinate mapping** is the coordinate mapping of an axis group used by default for display and by consumers unaware of multiple coordinate mappings.

A **coordinate system transform** is an invertible affine transform from one coordinate system to another. Coordinate system transforms are relationships in the coordinate system graph and typically compose only with isotropic coordinate mappings.

An **isotropic coordinate mapping** is a coordinate mapping in which every axis has the same units and the same scale. Offsets may differ between axes; the classification considers units and scale only. Example: a camera image with square pixels calibrated in nm, with the origin at the image center.

An **anisotropic coordinate mapping** is a coordinate mapping in which every axis has the same units but the scales differ between axes. Example: a camera image with rectangular pixels calibrated in nm.

A **mixed coordinate mapping** is a coordinate mapping in which the axes have different units. Example: a coordinate mapping with one axis calibrated in eV (energy) and another in nm (position).

### Array Header and Metadata

An array header can be derived from an annotated array and passed independently of the underlying array for inspection, allocation, streaming, serialization, and computation planning. The array shape is derived from the bound axis groups in its array descriptor; the storage data type is retained separately so that an exact underlying array can be allocated or validated. Pairing an underlying array with a header validates the array against the header and produces an annotated array whose descriptor and metadata are direct fields.

The array descriptor and array metadata are separate fields because computations handle them differently. A computation produces a descriptor consistent with the structure and interpretation of its result, while array metadata follows metadata-specific propagation rules.

Each extension record has a globally unique extension type identifier, schema version, and opaque encoded payload. The component that defines an extension owns its validation, encoding, decoding, schema migration, and semantic access. Extension records are accessed through their defined interfaces rather than as reserved free-form metadata keys.

Lossless serialization and exact copying preserve all extension records, including extension types unknown to the consumer. A computation includes an extension record in a derived annotated array only when the computation or extension definition supplies an explicit rule to preserve, transform, replace, or generate it.

### Coordinate System Graph

The coordinate system graph is maintained outside annotated arrays, typically at the instrument level. Examples of coordinate systems in the graph include camera space, scan space, and stage space.

An external coordinate tool translates a point between two annotated arrays by composition: from index coordinate space to calibrated coordinates via a coordinate mapping, when necessary between coordinate systems via a transform from the coordinate system graph, and back to index coordinate space via the inverse coordinate mapping.

Point translation is exact and produces fractional index values. Combining or overlaying data between coordinate systems requires resampling with interpolation, which is a computation, not a data model operation.

### Coordinate Mapping Use Cases

Translate a point on an image from one camera to the equivalent point on another camera, where the cameras differ in rotation, flip, pixel size, or binning.

Map a point on a camera image to stage coordinates for stage movement.

### Detailed Use Case: Camera Image with Multiple Coordinate Mappings, Graphics, and Overlays

A camera image has two isotropic coordinate mappings — real space in nm and angular in rad — and the real-space coordinate mapping is designated primary. An external coordinate tool derives stage-oriented coordinates by composing a coordinate mapping with the camera-to-stage transform from the coordinate system graph; the real-space coordinate mapping is used because stage space is in length units, although because both coordinate mappings are isotropic, the same rotation applies to either.

The image displays in index coordinate space. The user chooses whether the scale marker and mouse-over readout show nm or rad; switching changes the readout only, not the displayed data.

Graphics are drawn in graphics coordinates — a fixed per-axis scaling of index coordinate space in which each axis spans 0 to 1 — independent of any coordinate mapping. A graphic may instead be defined in stage coordinates: an external coordinate tool converts its points through the coordinate system graph and then to fractional indices through inverse coordinate mapping. An axes indicator showing the stage directions uses only the rotational component of the camera-to-stage transform supplied by the coordinate system graph, sized and positioned in graphics coordinates.

All of this is point translation; no data is resampled. The external coordinate tool uses the coordinate system graph to map a stage-space graphic into each image's referenced coordinate system.

### Open Questions

- Pixel center versus pixel corner convention for index values (deliberately deferred).

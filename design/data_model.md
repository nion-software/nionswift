# Nion Data Model

## Annotated Array

An **annotated array** is one complete unit of data: an underlying array, array descriptor, and array metadata. The implementation class name is `AnnotatedArray`; text uses "annotated array"; "underlying array" always refers to the raw value buffer inside an annotated array. This section describes the annotated array model in two parts: the current implementation state and the planned state.

### Current Implementation

This section uses annotated-array and axis-group terminology where possible, although the current implementation calls an annotated array a `DataAndMetadata` or `xdata`.

An annotated array is organized into three ordered sections: an optional sequence axis of rank 1, an optional collection axis group of rank 1 or 2, and a signal axis group of rank 0, 1, 2.

An annotated array holds values of type scalar, complex, RGB, or RGBA.

Each axis has a single calibration associated with it. The calibration may be an identity calibration.

### Planned Implementation

An annotated array contains an underlying array, array descriptor, and array metadata. An array header packages the descriptor and metadata with the storage data type.

The array metadata contains a creation time, free-form attributes, and structured extension records. An extension record is a versioned, typed container for an opaque encoded payload whose semantics and access interface are defined outside the annotated array model. Extension records track things like computation provenance and coordinate transforms.

The array descriptor contains an ordered list of axis groups and a value type. At least one axis group is required; only the final group may have rank zero.

Each axis group may have coordinate mappings and may reference the coordinate system in which its mapped coordinates are interpreted. One coordinate mapping may be primary.

### Terms and Definitions

An **annotated array** is one complete unit of data: an underlying array, array descriptor, and array metadata.

An **array descriptor** contains the intrinsic fields required to interpret an underlying array.

**Array metadata** is contextual information that travels with an annotated array but is not required to interpret its underlying array.

An **array header** is a utility value containing an array descriptor, storage data type, and array metadata without an underlying array.

An **intrinsic field** is information whose semantics and invariants are part of the annotated array model, such as axis groups, coordinate mappings, coordinate system references, and intensity calibrations.

The **storage data type** specifies how values are represented in the underlying array. It is distinct from the value type, which describes the meaning of one logical value.

The **creation time** is the time at which an annotated-array value is created.

An **extension record** is versioned, code-interpreted array metadata whose semantics are owned outside the fundamental annotated array model. Examples are acquisition coordinate context and computation provenance.

**Free-form metadata** is information that travels with an annotated array without a machine-enforced schema and is not interpreted by the annotated array model.

An **axis group** is an ordered group of axes in an annotated array. The rank of an axis group is the number of axes in the group.

A **bound axis group** is an axis group in which every axis has a concrete positive size. Its axis sizes determine the shape of the group.

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

### Array Metadata

The array descriptor and array metadata are separate fields because computations handle them differently. A computation produces a descriptor consistent with the structure and interpretation of its result, while array metadata follows metadata-specific propagation rules.

The creation time records when the annotated-array value is created. A derived result has its own creation time; an acquisition time that must survive derivation belongs in an acquisition extension record.

The creation time is timezone-aware. Its timezone object carries the UTC offset and, when represented by an IANA timezone, the IANA zone identifier; array metadata has no separate timezone or timezone-offset fields.

Each extension record has a globally unique extension type identifier, schema version, and opaque encoded payload. The component that defines an extension owns its validation, encoding, decoding, schema migration, and semantic access. Extension records are accessed through their defined interfaces rather than as reserved free-form metadata keys.

Lossless serialization and exact copying preserve all extension records, including extension types unknown to the consumer. A computation includes an extension record in a derived annotated array only when the computation or extension definition supplies an explicit rule to preserve, transform, replace, or generate it.

### Array Header

An array header can be derived from an annotated array and passed independently of the underlying array for inspection, allocation, streaming, serialization, and computation planning. The array shape is derived from the bound axis groups in its array descriptor; the storage data type is retained separately so that an exact underlying array can be allocated or validated. Pairing an underlying array with a header validates the array against the header and produces an annotated array whose descriptor and metadata are direct fields.

### External Coordinate Systems

Coordinate-system definitions and transforms are maintained outside annotated arrays. Annotated arrays participate in coordinate translation through the coordinate-system references and coordinate mappings in their axis groups.

Point translation, transform composition, resampling boundaries, and display use cases are described in [Coordinate Translation and Display](./coordinate_translation.md).

### Open Questions

- Pixel center versus pixel corner convention for index values (deliberately deferred).

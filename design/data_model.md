# Nion Data Model

## Annotated Array

An **annotated array** is one complete unit of data: an underlying array, array descriptor, and array metadata. The implementation class name is `AnnotatedArray`; text uses "annotated array"; "underlying array" always refers to the raw value buffer inside an annotated array. This section describes the annotated array model in two parts: the current implementation state and the planned state.

### Current Implementation

This section uses annotated-array and axis-group terminology where possible, although the current implementation calls an annotated array a `DataAndMetadata` or `xdata`.

An annotated array is organized into three ordered sections: an optional sequence axis of rank 1, an optional collection axis group of rank 1 or 2, and a signal axis group of rank 0, 1, 2.

An annotated array holds values of type scalar, complex, RGB, or RGBA.

Each axis has a single calibration associated with it. The calibration may be an identity calibration.

### Planned Implementation

The planned model expands the current representation so it can support more axis groups, multiple calibrations per axis group, and extensions such as provenance and coordinate transformations without reshaping the core structure. It also leaves room for richer coordinate-system references, non-uniform coordinates, and additional value types as the model evolves.

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

An **axis group** is an ordered group of axes in an annotated array. The rank of an axis group is the number of axes in the group. Each axis object includes a display label and a positive concrete size.

The **array rank** (called `ndim` in NumPy-oriented code) is the total number of axes in an annotated array, equal to the sum of axis-group ranks.

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

An array header can be derived from an annotated array and passed independently of the underlying array for inspection, allocation, streaming, serialization, and computation planning. The array shape is derived from the axis groups in its array descriptor; the storage data type is retained separately so that an exact underlying array can be allocated or validated. Pairing an underlying array with a header validates the array against the header and produces an annotated array whose descriptor and metadata are direct fields.

### Persistent Storage

An annotated array in persistent storage consists of two distinct components: the underlying array data and associated metadata. This separation reflects different access patterns and storage requirements; an application may need to read or write metadata independently of large array data.

The metadata component is further organized into three parts:

**Essential keys** comprise the array descriptor and creation time. These are the minimum information required to correctly interpret and contextualize the underlying array data. The array descriptor must be present and valid; the creation time must be timezone-aware. Essential keys are always persisted and always retrieved together with the underlying array.

**Free-form attributes** are user-supplied or application-supplied metadata with no enforced schema. These are carried alongside the array for contextual information and may be inspected, modified, or extended without schema migration.

**Extension records** are versioned, code-interpreted metadata owned by components outside the annotated array model. Each extension record contains a globally unique type identifier, schema version, and opaque encoded payload. Extension records are preserved during lossless storage operations and exact copying, though computations may apply explicit rules to transform, replace, or generate them.

This storage model is format-agnostic and may be implemented in diverse ways: as a single file with structured sections (e.g., HDF5 with explicit layout), as separate files (e.g., NumPy `.npy` for data with JSON for metadata), as entries in a database with blob storage for array data, as records in a custom binary format, or through other mechanisms. The essential keys must be retrievable to validate, allocate, and construct in-memory annotated arrays; the persistence mechanism ensures these invariants are maintained.

Although array shape is implicit in the data itself, it is explicitly included in the metadata descriptor. This redundancy is intentional: in search and cataloging workflows, metadata must be readable without accessing the underlying array data. Keeping shape explicit in the descriptor enables efficient metadata inspection, filtering, and indexing—critical for large-scale data discovery. On read, implementations must validate that loaded data matches the descriptor; desynchronization is an error condition.

#### Metadata Dictionary Layout

The metadata component, when serialized in a JSON-compatible format, follows this structure:

```json
{
  "descriptor": {
    "axis_groups": [
      {
        "axes": [
          {
            "label": "y",
            "size": 512
          },
          {
            "label": "x",
            "size": 512
          }
        ],
        "coordinate_system_id": "camera",
        "coordinate_mappings": {
          "spatial": [
            {
              "scale": 0.1,
              "offset": 0.0,
              "unit": "nm"
            },
            {
              "scale": 0.1,
              "offset": 0.0,
              "unit": "nm"
            }
          ],
          "angular": [
            {
              "scale": 0.002,
              "offset": 0.0,
              "unit": "rad"
            },
            {
              "scale": 0.002,
              "offset": 0.0,
              "unit": "rad"
            }
          ]
        },
        "primary_mapping_key": "spatial"
      }
    ],
    "intensity_calibrations": {
      "calibrations": {
        "counts": {
          "scale": 1.0,
          "offset": 0.0,
          "unit": "counts"
        },
        "energy": {
          "scale": 0.5,
          "offset": 0.0,
          "unit": "eV"
        }
      },
      "primary_key": "counts"
    },
    "value_type": "scalar"
  },
  "created": "2026-07-21 15:30-07:00[America/Los_Angeles]",
  "attributes": {
    "sample_name": "specimen_CTS",
    "instrument": "Nion UltraSTEM",
    "user": "researcher",
    "notes": "Room temperature acquisition"
  },
  "extensions": [
    {
      "type": "nion.acquisition_context",
      "schema_version": 1,
      "payload": "..."
    },
    {
      "type": "nion.computation_provenance",
      "schema_version": 1,
      "payload": "..."
    }
  ]
}
```

**Key definitions:**

- `descriptor`: The array descriptor from essential keys. Contains:
  - `axis_groups`: An ordered list of axis groups (see below for structure).
  - `intensity_calibrations`: A `CalibrationSet` for intensity (value) calibrations, with named calibrations and a primary key.
  - `value_type`: A string describing the semantic type of array values. One of `"scalar"`, `"complex"`, `"rgb"`, `"rgba"`, or `"vector"`. This field is inferred from the storage data type and validated against it; it may be omitted during serialization if it matches the default value type inferred from the actual array dtype.
- `axis_groups[*]`: Each axis group contains:
  - `axes`: An ordered list of axis objects, each containing `label` and `size` (positive integer).
  - `coordinate_system_id`: Identifier referencing an external coordinate system (e.g., `"camera"`).
  - `coordinate_mappings`: A dict mapping keys (e.g., `"spatial"`, `"angular"`) to coordinate mapping tuples; each tuple has one calibration per axis in the group, ordered to match `axes`.
  - `primary_mapping_key`: The key of the primary coordinate mapping for this axis group.
- `axes[*]`: Each axis object contains:
  - `label`: The display label for this axis.
  - `size`: The positive integer size of this axis.
- `created`: The creation time from essential keys, represented as an ISO 8601-derived string with timezone offset and IANA timezone identifier (format: `YYYY-MM-DD HH:MM±HH:MM[IANA/Timezone]`).
- `attributes`: The free-form attributes dict. May contain any user- or application-supplied keys and values; no schema is enforced.
- `extensions`: An array of extension record objects. Each extension record contains:
  - `type`: A globally unique identifier for the extension type (reverse-DNS convention recommended).
  - `schema_version`: An integer version number for schema migration.
  - `payload`: An opaque string or encoded bytes representing the extension data. Encoding (e.g., base64) and interpretation are extension-specific.

Calibrations for axis coordinates are stored only in `coordinate_mappings` at the axis-group level, not per axis. This makes mapping keys group-scoped by construction and avoids per-axis key synchronization problems. Within one axis group, every mapping key resolves to a complete per-axis calibration tuple, so a key always describes one coherent coordinate mapping for the whole group. Persistent serialization omits fields whose value is `null`.

### External Coordinate Systems

Coordinate-system definitions and transforms are maintained outside annotated arrays. Annotated arrays participate in coordinate translation through the coordinate-system references and coordinate mappings in their axis groups.

Point translation, transform composition, resampling boundaries, and display use cases are described in [Coordinate Translation and Display](./coordinate_translation.md).

### Open Questions

- Pixel center versus pixel corner convention for index values (deliberately deferred).

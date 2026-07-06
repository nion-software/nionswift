# Nion Data Model

## Annotated Array

An **annotated array** is one complete unit of data: an underlying array, descriptor, dimensions, and associated metadata. The name reflects the composition: an array, annotated with axis groups, calibrations, coordinate system references, and metadata. The implementation class name is `AnnotatedArray`; text uses "annotated array"; "underlying array" always refers to the raw value buffer inside an annotated array. This section describes the annotated array model in two parts: the current implementation state and the planned state.

### Current Implementation

This section uses annotated-array and axis-group terminology where possible, although the current implementation calls an annotated array a `DataAndMetadata` or `xdata`.

An annotated array is organized into three ordered sections: an optional sequence axis of rank 1, an optional collection axis group of rank 1 or 2, and a signal axis group of rank 0, 1, 2.

An annotated array holds values of type scalar, complex, RGB, or RGBA.

Each axis has a single calibration associated with it. The calibration may be an identity calibration.

### Planned Implementation

The planned annotated array model specifies an ordered list of axis groups, each with an identifier and rank, and a value type.

Value types are scalar, complex, RGB, RGBA, or fixed-length vector (1/2/3).

An annotated array always contains at least one axis group. All axis groups must have at least one axis except the final axis group may have zero.

Coordinate systems are physical coordinate spaces typically representing an orientation of axes in space.

Coordinate mappings are mappings from the index coordinate space of an axis group into calibrated coordinates.

Each axis group has zero or more associated coordinate mappings. One coordinate mapping may be designated the primary coordinate mapping.

Each axis group designates the coordinate system of its index coordinate space. The designated coordinate system may be null, indicating that the coordinate system is unknown.

Within a coordinate mapping, each axis has exactly one associated calibration or coordinate array.

The annotated array has zero or more coordinate system transforms, which are affine transforms from one coordinate system to another, recorded at acquisition time. They normally only apply to isotropic coordinate mappings.

Future extensions may expand the value types and/or support variable length (ragged) value types.

### Terms and Definitions

An **annotated array** is one complete unit of data: an underlying array together with its annotations (axis groups, coordinate mappings, coordinate system transforms, and metadata). The implementation class name is `AnnotatedArray`. *Note on nomenclature:* "annotations" here means the structural and calibration metadata attached to the array - not display graphics such as rectangles, lines, or region markers drawn on a displayed image.

An **axis group** is an ordered group of axes in an annotated array. The rank of an axis group is the number of axes in the group.

The **signal axis group** is the final axis group in an annotated array. *Note on nomenclature:* "signal" is not a perfect term - axes outside the signal axis group may also carry meaningful signal - but it is the least bad of the candidates considered and a clear improvement over the previous term "datum," which read as surveying jargon and was an awkward singular of "data."

A **value type** is one of the supported value types: scalar, complex, RGB, RGBA, or vector.

A **coordinate system** is a physical coordinate space, typically representing an orientation of axes in space, consisting of an ordered list of coordinate system axes; it is the node type of the coordinate system graph. Each coordinate system has a unique identifier; identity is by identifier, so two coordinate systems with identical coordinate system axes are still distinct systems. Coordinate systems are shared: axis groups in one or more annotated arrays may designate the same coordinate system.

A **coordinate system axis** is a per-dimension component of a coordinate system: a name and optional direction metadata. Coordinate system axes carry no units; units belong to calibrations.

A **coordinate system graph** is the set of coordinate system definitions and the current coordinate system transforms. The coordinate system graph is maintained outside annotated arrays, at the instrument level.

A **calibration** is a structure containing `scale`, `offset`, and `units` used to map index values to calibrated values using the formula `x' = x * scale + offset`. A calibration is a linear transform on a single axis. A calibration exists within a coordinate mapping, one per axis. Calibrations support sampled (uniformly spaced) axes.

A **coordinate array** is a structure containing arrays that map index values to coordinate values. Coordinate arrays support non-sampled (non-uniformly spaced) axes.

An **index coordinate space** is the space of index values of an axis group.

A **coordinate mapping** is a mapping from the index coordinate space of an axis group into calibrated coordinates, consisting of one calibration or coordinate array per axis. An axis group may have zero or more coordinate mappings; coordinate mappings are coherent across all axes of the group.

A **primary coordinate mapping** is the coordinate mapping of an axis group used by default for display and by consumers unaware of multiple coordinate mappings.

A **coordinate system transform** is an invertible affine transform from one coordinate system to another, stored with the annotated array and typically recorded from the coordinate system graph at acquisition time. Coordinate system transforms typically compose only with isotropic coordinate mappings.

An **isotropic coordinate mapping** is a coordinate mapping in which every axis has the same units and the same scale. Offsets may differ between axes; the classification considers units and scale only. Example: a camera image with square pixels calibrated in nm, with the origin at the image center.

An **anisotropic coordinate mapping** is a coordinate mapping in which every axis has the same units but the scales differ between axes. Example: a camera image with rectangular pixels calibrated in nm.

A **mixed coordinate mapping** is a coordinate mapping in which the axes have different units. Example: a coordinate mapping with one axis calibrated in eV (energy) and another in nm (position).

### Coordinate System Graph

The coordinate system graph is maintained at the instrument level; an annotated array's coordinate system transforms are recorded from it at acquisition time. Examples: camera space, scan space, stage space.

A point is translated between two annotated arrays by composition: from index coordinate space to calibrated coordinates via a coordinate mapping, between coordinate systems via a coordinate system transform, and back to index coordinate space via the inverse coordinate mapping.

Point translation is exact and produces fractional index values. Combining or overlaying data between coordinate systems requires resampling with interpolation, which is a computation, not a data model operation.

### Coordinate Mapping Use Cases

Translate a point on an image from one camera to the equivalent point on another camera, where the cameras differ in rotation, flip, pixel size, or binning.

Map a point on a camera image to stage coordinates for stage movement.

### Detailed Use Case: Camera Image with Multiple Coordinate Mappings, Graphics, and Overlays

A camera image is acquired with two isotropic coordinate mappings — real space in nm and angular in rad — and one coordinate system transform, the camera-to-stage rotation recorded at acquisition. The real-space coordinate mapping is designated primary. Stage-oriented coordinates are derived by composing a coordinate mapping with the coordinate system transform; the real-space coordinate mapping is used because stage space is in length units, although because both coordinate mappings are isotropic, the same rotation applies to either.

The image displays in index coordinate space. The user chooses whether the scale marker and mouse-over readout show nm or rad; switching changes the readout only, not the displayed data.

Graphics are drawn in graphics coordinates — a fixed per-axis scaling of index coordinate space in which each axis spans 0 to 1 — independent of any coordinate mapping. A graphic may instead be defined in stage coordinates: its points are converted to fractional indices through inverse coordinate mapping. An axes indicator showing the stage directions uses only the rotational component of the stored coordinate system transform, sized and positioned in graphics coordinates.

All of this is point translation; no data is resampled. Because the coordinate system transform is recorded at acquisition-time, stage-space graphics remain correctly positioned offline, and a second image acquired at a different rotation carries its own coordinate system transform, so the same stage-space graphic maps correctly onto both images.

### Open Questions

- Pixel center versus pixel corner convention for index values (deliberately deferred).

# Nion Data Model

## Dataset

A **Dataset** is one complete unit of data: array, descriptor, dimensions, and associated metadata. This section describes the Dataset model in two parts: the current implementation state and the planned state.

### Current Implementation

This section uses dataset and axis-set terminology where possible, although the current implementation calls dataset a `DataAndMetadata` or `xdata`.

A Dataset is organized into three ordered sections: an optional sequence axis of rank 1, an optional collection axis set of rank 1 or 2, and a datum axis set of rank 0, 1, 2.

A Dataset holds values of type scalar, complex, RGB, or RGBA.

Each axis has a single calibration associated with it. The calibration may be an identity calibration.

### Planned Implementation

The planned Dataset model specifies an ordered list of axis sets, each with an identifier and rank, and a Dataset value type.

Value types are scalar, complex, RGB, RGBA, or fixed-length vector (1/2/3).

A Dataset always contains at least one axis set. All axis sets must have at least one axis except the final axis set may have zero.

Each axis set has an optional associated coordinate system reference.

Each axis has zero or more associated calibrations or coordinates.

Future extensions may expand the value types and/or support variable length (ragged) value types.

### Glossary

- **Axis set:** An ordered set of axes in a Dataset. The rank of an axis set is the number of axes in the group.
- **Datum axis set:** The final axis set in a Dataset.
- **Value type:** The value types: scalar, complex, RGB, RGBA, vector.
- **Calibration:** A structure containing `scale`, `offset`, and `units` used to map index values to calibrated values using the formula `x' = x * scale + offset`. Calibrations support sampled (uniformly spaced) axes.
- **Coordinate:** A structure containing coordinate arrays that map index values to coordinate values. Coordinates support non-sampled (non-uniformly spaced) axes.
- **Coordinate System:** A shared coordinate system common to axis sets in one or more Datasets.

## Iteration

Iteration describes how a computation traverses a Dataset.

For iteration, one axis set is designated as the compute axis set and the others become the navigation axis sets. The navigation axis sets are in the order they appear in the original Dataset. The compute axis set is the input to the computation at each iteration position.

At each iteration position, defined by one point from each axis included in the navigation axis sets, a slice of the compute axis set called the compute slice is sent to a computation. The outputs of the computation are assembled into a new Dataset.

At each iteration position, a mask can be applied to the compute slice before being passed to the computation. The mask must have axes matching the compute axis set.

Iteration supports windowed iteration for axis sets with one axis. The window is passed to the computation as compute slice with an extra dimension.

Iteration supports tiled iteration. The tile is passed to the computation as compute slice and assembled automatically into a new axis set.

Iteration supports paired iteration with broadcasting.

Iteration computations will support stateful aggregation style computations, for example computing a sum or mean along an iterated axis.

The output Datasets are constructed by replacing the compute axis set of the original Dataset with an axis set with the shape, calibrations, and value type of the computation outputs. Computations with multiple outputs are supported.

Iteration is limited to one axis set.

Iteration staging is where multiple iterations are stacked together. For example, first measure shifts, then apply shifts and sum. The output of the first iteration (shifts) is used as input to the second iteration (apply shifts and sum).

Iteration pipelining is where the output of one computation is passed as input to the next computation within the same iteration. For example, first apply a blur to each slice, then compute the mean of each blurred slice.

### Future Extensions

- Iteration over multiple axis sets.
- Iteration over a subset of axes in a particular axis set.

### Iteration Use Cases

Apply a pixel to pixel transformation to each computed slice. Result has same shape/calibrations as input. Example is applying a blur to each 2D computed slice of a sequence of 2D images.

Apply a reduction function to each computed slice, for example computing the mean of each slice. Result has the same shape/calibrations as the iterated dimensions, but the axes or axis set used for the computed slice are removed.

Apply a reduction to each 2D image in a collection by integrating along the y-axis to produce 1D data.

Apply computation or reduction to the first axis set (collection) or second axis set (image) in a 4D-image dataset.

Align and sum is two operations: first computes a shift dataset by aligning all slices to a reference slice, second applies the shifts to the original dataset and sums the shifted data.

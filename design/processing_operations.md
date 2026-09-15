# Processing Operations

## Overview

This document describes the standard operations for scientific image processing of annotated arrays in the Nion data model.

The terms *annotated array*, *descriptor*, *axis group*, and the signal, collection, and sequence axis groups are defined by the Nion data model specification and are used here without redefinition.

The organization uses two complementary views:

- **Execution-scope categories**: target axis-group operations, data reshaping primitives, higher-order operations, sequence/collection operations, and data generation operations.
- **Target-operation families** (within target axis-group operations): base array transformations, geometric transforms, filtering and frequency-domain operations, value transformations, and analysis/feature extraction.

## Scope and Execution Boundary

This document defines **operation semantics**, not execution orchestration.

- Processing operations specify what a function does on its selected input rank (for example, 1D or 2D signal data) and how descriptor/metadata are transformed.
- Iteration across non-selected axes or axis groups is handled by the computation infrastructure.
- Dimension-reducing behavior is defined by the operation (for example, `mean` reducing one axis), while orchestration of reductions across larger workloads is handled by the computation infrastructure.

As a result, map/reduce-style scheduling, chunking, threading, parallelization, cancellation, and progress reporting are intentionally out of scope for this document.

### Mapping and Reduction

For the purposes of this document:

- **Mapping** applies a base processing operation to a particular axis group while iterating independently over the remaining axis groups, so that the operation is evaluated on the axis-group data at each iteration point.
- **Reduction** maps a processing operation across the axis-group data at each iteration point and then combines the results with an aggregation function.

This is the intended execution model for higher-level computation infrastructure, but the individual processing operation definitions remain local and selector-agnostic.

### Mutation Semantics

Processing operations are not in-place. Each operation returns a new annotated array value with updated descriptor and metadata as required by the operation semantics.

## Operation Compatibility

Operation compatibility defines operation constraints and supported modes. The vocabulary for each field is defined once here, independently of the operation families that use it; the subsections below appear in the same order as the fields do in an operation's `Compatibility` block.

Every operation in this document carries a `Compatibility` block. Ten fields are always present, in this order: `Input Dimensionality`, `Output Dimensionality`, `Input Value Type`, `Input Cardinality`, `Output Value Type`, `Output Container Model`, `Output Cardinality`, `Data-Modification Behavior`, `Coordinate Calibration`, and `Intensity Calibration`. Two further fields follow them conditionally. `Domain` is given only where the operation's own definition references a domain — where it requires input in one, produces output in one, or moves between them. `Spectrum Symmetry` is given only where the operation constrains or determines the symmetry of a spectrum it consumes, produces, or forms internally.

A field value may be a single term from the relevant vocabulary, or a qualified statement that names the condition under which each term applies (for example, per variant, per mode, or per parameter setting). Qualified values are expected wherever an operation's behavior genuinely varies. Where one of the ten mandatory fields does not apply to an operation, it is recorded explicitly as `n/a` with a short reason, so that a genuinely undetermined field is distinguishable from one that has simply not been filled in.

`Domain` and `Spectrum Symmetry` are the two exceptions to that convention: they are omitted entirely rather than recorded as `n/a` when they do not apply. The exception is deliberate. Their applicable set is small and follows from the operation's own definition, so a blanket `n/a` on the remaining operations would add lines without adding information. Note also that an unconstrained `Either` is equivalent to omission, and is written only where a mode or format parameter makes the constraint conditional.

### Input Dimensionality and Output Dimensionality

Rank is recorded as two separate fields. `Input Dimensionality` states the rank of the selected target axis-group data the operation consumes; `Output Dimensionality` states the rank of the result. The two fields draw on the same value set:

- **0D**
- **1D**
- **2D**
- **1D or 2D**
- **0D, 1D, or 2D**

`Output Dimensionality` additionally admits **same as input** for the common case where the operation preserves rank, and a rank expression (for example, `input rank minus the number of reduced axes`) where the result depends on parameters.

Reshaping primitives and orchestration-level operations are not defined on a fixed selected target rank; they record `n/a` for `Input Dimensionality`. Nullary generators have no array input and record `n/a` for `Input Dimensionality`, with the generated rank stated under `Output Dimensionality`.

### Value Type

No compatibility field carries this name on its own. These are the semantic value types that `Input Value Type Compatibility` and `Output Value Type` are both defined in terms of, listed once here so that both can refer to them.

- **Scalar**
- **Complex**
- **RGB/RGBA**
- **Vector**

### Input Value Type Compatibility

Operations are classified by what semantic value types they accept as input. This is distinct from whether they preserve or convert the value type in the output.

- **Any**: Value-type agnostic operations. Accepts real scalar, complex scalar, vector, and RGB/RGBA inputs. Examples: transpose, reshape, squeeze, flip, pad, crop, redimension.
- **Linear**: Requires addition and scalar multiplication semantics. Accepts real scalar, complex scalar, and (when defined component-wise) vector inputs; may also accept RGB/RGBA with explicit per-channel application policy. Typical examples: add, subtract, negate, mean, sum, interpolation, convolution, FFT.
- **Ordered**: Requires a total ordering on values. Accepts real scalar or boolean inputs. Examples: min, max, argmin, argmax, median, quantile, thresholding, median filter, bilateral filtering, and morphological rank/ordering operations.
- **Requires Complex**: Requires complex-valued scalar input. Examples: real/imaginary/phase extraction and complex-specific value conversions.
- **Requires Vector**: Requires vector-valued input. Examples: vector magnitude, vector projection, vector normalization, vector coordinate transforms.
- **Requires RGB/RGBA**: Requires RGB- or RGBA-valued input. Examples: channel extraction and brightness/luminance conversion.

### Input Cardinality

Operations are classified by how many array-type inputs they require, distinct from scalar parameters. Array-type inputs are subject to shape compatibility and broadcasting rules.

- **Nullary**: Generates output from scalar parameters alone; no array inputs required. Examples: random array, linspace, constant arrays.
- **Unary**: Operates on a single array input (the selected target axis-group data). Examples: negate, magnitude, FFT, auto-correlate, spatial filters.
- **Binary**: Requires two array-type inputs. The primary input is the selected target axis-group data; a secondary array input participates in the operation (subject to broadcasting or alignment constraints). Examples: add (scalar or array), cross-correlate, multiply.
- **N-ary**: Accepts a variable number of array inputs. Examples: concatenate (multiple arrays), stack (multiple arrays).

**Note**: Scalar parameters such as threshold values, kernel sizes, or standard deviations are not counted in input cardinality; they are documented in the operation's parameters section.

### Output Value Type

The `Output Value Type` compatibility field records the **output semantic value type** (scalar, complex, RGB/RGBA, or vector) and whether the operation preserves or converts it. The following further properties are implied by that semantic type and are documented per operation only where they are not obvious:

- **Output storage/data representation**: compatible with expected representation class (for example, RGB-compatible integer storage, complex storage, floating-point scalar storage, or vector storage).
- **Output value dimensionality**: number and structure of components per logical value (for example, scalar=1, complex=2 components, RGB=3 channels, RGBA=4 channels, vector=n components).
- **Output conversion behavior**: whether the operation preserves value type or converts it (for example, complex -> scalar magnitude, RGB -> scalar brightness).

### Output Container Model

- **Annotated Array**: output is one annotated array (including 0-D scalar arrays).
- **Structured Table**: output is tabular/record-oriented structured data (for example, component, particle, peak, descriptor, or moment tables).
- **Mixed Bundle**: output combines arrays and structured tables.

### Output Cardinality

Operations are classified by the number and arity model of logical outputs they produce. A logical output can be an annotated array, a structured table (for example component/particle/peak/descriptor/moment tables), or a mixed bundle of these. Output cardinality is a structural property independent of input cardinality and value-type conversions.

- **Unary** (single output): Produces exactly one logical output. Most operations fall into this category. Examples: negate, magnitude, FFT, transpose, thresholding, and table-only outputs such as shape-descriptor or image-moment tables.
- **Binary** (dual output): Produces exactly two logical outputs. Examples in this document: `Connected Component Analysis (Labeling)` (labeled array + component table), and `Masking (Preprocessing Operation)` in `ignore` mode (masked data + companion participation mask).
- **Fixed N-ary** (fixed multi-output): Produces a fixed number `N > 2` of logical outputs determined by operation definition (not data-dependent). Example in this document: `Coordinate Grid` when configured to emit one coordinate array per axis.
- **Variadic List Output** (data/spec-dependent multi-output): Produces a list of outputs whose length is determined at runtime by input data shape or explicit split specification. Examples in this document: `Split` and `Unstack`.

**Note**: Scalar outputs (such as summary statistics: mean, max, etc.) are typically wrapped in zero-dimensional (0-D) arrays rather than treated as separate logical outputs. Structured tables are first-class logical outputs and are counted in output cardinality the same way arrays are.

### Data-Modification Behavior

- **Layout-only**: operation preserves element count and per-element values while changing only structural interpretation (for example, axis ordering, orientation, indexing interpretation, or rank/shape reinterpretation); this category also includes the degenerate no-change case where values and element count are preserved and only companion structural/participation metadata is attached or reinterpreted (for example, transpose, flip, 90° rotate, squeeze, redimension, flatten, unflatten, integer shift with wrap boundary handling, and masking in `ignore` mode).
- **Extent-changing, values preserved**: operation changes structural extent (size or shape) while preserving the values of all retained or inserted elements (for example, crop, pad, concatenate, split, unstack, decimation without anti-aliasing).
- **Value-modifying**: operation changes one or more values without changing structural extent (for example, filtering, interpolation, thresholding, and integer shift when boundary fill introduces new values).
- **Structure and value-modifying**: operation changes both structural extent and values (for example, resample with interpolation, rebin, decimation with anti-aliasing).

These four values partition the space of input-transforming operations: every such operation changes extent, values, both, or neither. Operations whose output is a Structured Table have no output array whose extent and values can be compared against the input, and record `n/a` for this field; the `Output Container Model` field carries that distinction instead.

### Coordinate Calibration

What the operation assumes about the calibration of its axes, and how axis calibration is transformed on output.

- **Calibration-agnostic**: operation does not require calibrated coordinates.
- **Calibrated coordinates required**: operation requires coordinate calibration metadata.
- **Uniform-sampled only**: operation assumes sampled axes represented by linear calibration.
- **Non-uniform supported**: operation supports coordinate arrays for non-uniform axes.
- **Isotropic only**: operation assumes isotropic coordinate calibration.
- **Anisotropic supported**: operation supports anisotropic coordinate calibration.
- **Mixed-units supported**: operation supports mixed coordinate calibration units.

### Intensity Calibration

How the operation propagates the intensity calibration of the values themselves. This is a separate concern from coordinate calibration and is not expressible in the vocabulary above, so it is recorded as a propagation rule rather than as a term:

- **preserved from input**: output values carry the input intensity unit unchanged.
- **converted**: the operation produces a stated new unit — a product, ratio, power, angular unit, or intensity-per-coordinate-unit.
- **discarded**: output values are dimensionless (for example, a boolean mask or a normalized vector).
- **n/a**: output values are not measurements in an intensity unit at all (for example, integer component labels, index positions, or displacement vectors, which carry coordinate units instead).

Operations that change the range or meaning of values — normalization, thresholding, absolute value, and the frequency-domain transforms — must state which of these applies.

### Domain

- **Spatial-domain**
- **Reciprocal-domain**
- **Spatial-domain or reciprocal-domain**

Operations that move data between domains record the transition using arrow notation, for example `spatial-domain -> reciprocal-domain`.

### Spectrum Symmetry

- **Hermitian**
- **Non-Hermitian**
- **Either**

This field may constrain the input, describe the output, or both, and an operation must say which. Because symmetry is usually contingent — on the input value type, on an output format selection, or on a mode parameter — qualified statements of the form *`Hermitian` when X, `Non-Hermitian` otherwise* are the normal case rather than an exception. An entry that names no term from the list above is not a valid value for this field.

## Selector Model

The selector model defines how the scope of an operation is chosen before a processing operation is applied. Selectors are primitive operations or computation-layer constructs, not concerns of the individual processing algorithms themselves.

- A selector may produce a new annotated array or a selected view that is then passed to a processing operation.
- A processing operation should not need to know whether its input was produced by slicing, indexing, or another selector mechanism.
- When a selector targets an axis group or subset of an axis group, the selected data is the input to the algorithm; the algorithm only defines semantics for the selected input.
- For many operations, a selector can be applied before execution to target a subset of axes or elements without changing the algorithm definition.

This keeps selectors reusable across operations and avoids duplicating selection logic inside each algorithm implementation.

The selector model is broader than slicing: slicing is the primary structural selector primitive within an axis group, but the selector model also includes higher-order selection constructs such as tiling, rolling-window traversal, and predicate-based filtering over iterator axis groups.

### Slicing as a Selector Primitive

Slicing is the fundamental selector primitive for reducing the scope of an operation within an axis group.

- **Full-span selection** is the null case of slicing: the entire axis group is included.
- **Range selection** is slicing over a subrange and includes what would otherwise be described as cropping.
- **Single-index selection** is slicing whose selected length is 1 and includes what would otherwise be described as indexing.

In this model, cropping and indexing are not separate selector concepts; they are specific forms of slicing. This is a statement about semantics, not about API surface; see `Cropping (Target Axis Group)`.

Semantically, slicing produces selected axis-group data with the corresponding descriptor and calibration updates.

Operationally, slicing can often be realized without an additional data copy. When a sliced result is consumed immediately by a downstream operation, the computation infrastructure may incorporate the slice directly into the iteration plan rather than materializing an intermediate annotated array. This is an execution optimization, not part of the meaning of slicing itself.

Accordingly, slicing is not always part of iteration. It is always part of the selector model, and computation infrastructure may absorb it into iteration when that is advantageous.

### Selector Examples Beyond Basic Slicing

- **Tiling** partitions an axis group into multiple non-overlapping regions processed as a set. This is a higher-order selector pattern built from repeated slicing.
- **Rolling window** traversal generates overlapping windows along an axis group. This is not one slice; it is an iteration pattern that repeatedly applies slicing with shifted bounds.
- **Filtering a sequence by a function** selects which elements of an iterator axis group participate based on a predicate. This is part of the selector model, but it is not slicing because the selection is defined by a function over iteration points rather than by axis bounds alone.
- **Masking on iterator axis groups** is better described as filtering or predicate selection over iteration points, not as target-data masking. It determines which iteration points are visited.

### Masking as a Separate Preprocessing Operation

Masking is distinct from slicing and from filtering over iterator axis groups.

- **Slicing** changes which structural portion of an axis group is presented to downstream operations.
- **Masking** leaves the structural extent of the selected target axis-group data unchanged and modifies which values within that extent participate in the downstream operation.
- **Iterator filtering** changes which iteration points are visited before the target axis-group data is presented to the processing operation.

In this document, masking is treated as a separate preprocessing operation that may be inserted after slicing and before the main processing operation. A processing operation therefore consumes either unmasked selected target-axis-group data or pre-masked selected target-axis-group data, but it does not define masking semantics internally.

By contrast, if the goal is to choose which sequence elements, collection elements, or other iteration points participate at all, that should be described as iterator filtering or predicate selection rather than masking.

Operationally, computation infrastructure may fuse masking with adjacent selection or processing steps, but that fusion is an execution optimization rather than part of the masking definition.

Windowing (for spectral analysis) follows the same preprocessing principle as masking: it preserves structural extent and modifies values prior to a downstream operation. In this model, windowing is represented either by generating a window array (`Windowing Generators`) and applying it via `Multiply`, or as an equivalent explicit preprocessing operation.

The formal operation definition is specified under `Target Axis-Group Operations` as `Masking (Preprocessing Operation)`.

## Target Axis-Group Operations (1D and 2D)

Target axis-group operations are defined on selected target axis-group 1D or 2D data. They are selector-agnostic and iteration-agnostic: selector and iteration machinery determine which target data is presented, and the operation defines only the specific operation on that target data.

### Effect of Non-Signal Target Selection

When the target axis group is the signal axis group, operations transform signal values directly. When the target axis group is a non-signal axis group (collection or sequence), operations restructure where signal values end up in the output array.

For example, applying a shift to a collection axis group moves which signal elements land at which collection positions in the output. The individual signal values are unchanged but their output positions are determined by the transformation applied to the non-signal axis group.

This means that the choice of target axis group changes the semantic meaning of the operation as a whole, not just which data is processed.

**Geometric transforms and signal interpolation:** when any geometric transform applied to a non-signal axis group maps signal values to non-integer positions on the output grid, the signal values must be interpolated. This is a general principle that applies to:

- **Fractional shift**: a 0.5-pixel shift in a collection dimension places signal values halfway between output collection grid positions, requiring signal interpolation.
- **Non-90° rotation**: rotating a collection axis group by an arbitrary angle places signal values at rotated positions that do not align to the output grid.
- **Non-integer scale/zoom**: scaling a non-signal axis group by a non-integer factor produces signal positions that fall between output grid points.
- **Affine transforms**: the general case combining shift, rotation, scale, and shear on a non-signal axis group may produce off-grid signal positions.
- **Warp fields**: spatially varying distortion applied to a non-signal axis group maps each signal value to an individually displaced, potentially non-integer output position.

Operations that are grid-preserving — integer shifts, flips, and rotations by exact multiples of 90° — do not displace signal values to off-grid positions and therefore do not require signal interpolation even when applied to non-signal axis groups.

### Null (Identity) Operator

The null operator is the identity processing operation.

The null operator performs no value-domain transformation and preserves selected target axis-group data as-is.

In this model, the null operator is primarily a selector/iteration-level utility and not a replacement for explicit target-axis-group crop semantics.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only (degenerate no-change case)
- Coordinate Calibration: Calibration-agnostic
- Intensity Calibration: preserved from input

**Parameters:**
- None

**Notes:**
- Useful as a canonical no-op in composition pipelines.
- Useful for cropping higher dimensions; see `Cropping (Target Axis Group)` for the first-class crop operation and the note there on how the three descriptions relate.

### Cropping (Target Axis Group)

Cropping is an explicit target axis-group operation for 1D or 2D data. It returns a new annotated array whose selected target axis-group extent is reduced to the requested bounds.

Cropping may be implemented internally using slicing/view mechanics, but it remains a first-class operation in this API surface.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: Calibration-agnostic; per-axis calibration offset is advanced to the new start bound and scale is unchanged
- Intensity Calibration: preserved from input

**Parameters:**
- Target axis group
- Per-axis crop bounds (start, stop)

**Note on layering:** Cropping is described in three places in this document, at three different levels. `Slicing as a Selector Primitive` describes its *semantics* — a crop is a form of range slicing. This section defines it as a first-class *API surface* operation that exists regardless of that equivalence. The `Null (Identity) Operator` notes describe its use as a *higher-dimension trimming utility*. These are three levels of description of one behavior, not competing definitions.

### Masking (Preprocessing Operation)

Masking is a formal preprocessing operation that marks or modifies which values within selected target axis-group data participate in a downstream operation while preserving structural extent.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Any; the mask array itself must be boolean or integer
- Input Cardinality: Binary in `mask_array` mode (target data + mask array); Unary in `predicate` mode (target data only)
- Output Value Type: preserved from input; the companion participation mask emitted in `ignore` mode is boolean
- Output Container Model: Annotated Array (two annotated arrays in `ignore` mode)
- Output Cardinality: Unary for `fill_value` and `nan`; Binary for `ignore` (masked data + companion boolean participation mask)
- Data-Modification Behavior: Value-modifying for `fill_value` and `nan`; Layout-only for `ignore` as the degenerate no-change case, because excluded values are propagated unchanged and participation state is carried only in the companion mask
- Coordinate Calibration: Calibration-agnostic; coordinate calibration is unchanged and the companion mask inherits it
- Intensity Calibration: preserved for retained values; the constant supplied in `fill_value` mode is interpreted in the input intensity calibration, and the companion participation mask is dimensionless

**Parameters:**
- **Mask specification mode**: `mask_array` or `predicate`
  - **Mask array**: a boolean or integer array broadcast-compatible with the selected target axis-group shape; `True`/non-zero entries mark participating elements.
  - **Predicate**: a callable or expression evaluated element-wise on the selected target data, producing a boolean mask at runtime.
- **Participation semantics**:
  - `include`: elements where the mask is `True`/non-zero participate; all others are excluded.
  - `exclude`: elements where the mask is `True`/non-zero are excluded; all others participate.
- **Fill/exclusion policy**:
  - `fill_value` (scalar): excluded positions receive a constant fill value (e.g., `0`, `NaN`, `+/-Inf`).
  - `nan`: shorthand for IEEE NaN fill, meaningful for floating-point scalar and complex arrays.
  - `ignore`: excluded positions are propagated unmodified and a companion boolean participation mask is emitted so downstream operations can honor exclusion semantics.

**Notes:**
- Statistics (`mean`, `sum`, `std`, etc.) and `Histogram` consume pre-masked data; masking is applied before those operations run.
- Predicate-based and mask-array-based masking are semantically equivalent; predicate mode is evaluated to a boolean mask before application.

### Base Array Transformations

Base array transformations are one family of target axis-group operations. They modify the structure or sampling of the selected target axis-group data while typically preserving the conceptual meaning of its contents.

This family covers grid-preserving structural operations. Some operations, such as resample, are value-modifying despite operating on structure.

Cropping is defined as a first-class operation under `Target Axis-Group Operations`. Asymmetric adjustment - cropping one side and padding the other - can be composed of the two operations.

Reshaping primitives such as `squeeze` and `redimension` are defined in a separate section because they change dimensional interpretation across axis groups rather than acting as local 1D/2D processing kernels.

#### Transpose (Flip, Rotate)

Permutes the order of axes within or across axis groups. Related operations include:

- **Transpose**: Reorder axes according to a permutation specification.
- **Flip**: Reverse the direction along one or more axes (vertical, horizontal, etc.).
- **Rotate**: Rotate array around one or more axes by multiples of 90°.

These operations update axis ordering in their respective axis groups and adjust calibrations accordingly. Flips and rotations may reverse or reorder scale values and offsets depending on the operation.

Rotations by exact multiples of 90° are grid-preserving. Arbitrary-angle rotation requires interpolation and is defined under `Geometric Transforms`.

**Compatibility:**
- Input Dimensionality: 2D for `Transpose` and 90° `Rotate` (both require rank >= 2); 1D or 2D for `Flip`
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only
- Coordinate Calibration: Anisotropic supported; per-axis scale/offset are permuted with the axes, and flips and rotations reverse offsets on the affected axes
- Intensity Calibration: preserved from input

**Parameters:**
- Operation variant (`transpose`, `flip`, `rotate_90`)
- Axis permutation specification (for `transpose`)
- Axis or axes to reverse (for `flip`)
- Rotation quarter-turn count (for `rotate_90`)

#### Rebin

Combines neighboring elements along one or more axes by integer factors into groups, then aggregates each group. Rebinning reduces array size.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear; RGB/RGBA accepted per channel with `mean` or `median` aggregation only
- Input Cardinality: Unary
- Output Value Type: preserved from input; storage type must widen for `sum` aggregation on bounded integer or RGB storage
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying (reduces axis extent and aggregates multiple input values into one output value per group)
- Coordinate Calibration: Uniform-sampled only; per-axis scale is multiplied by the binning factor and offset advances by half a bin
- Intensity Calibration: preserved under `mean` and `median` aggregation; `sum` accumulates the input unit over each group

**Parameters:**
- Axis or axes to rebin
- Binning factors per axis
- Aggregation method (sum, mean, median, etc.)

#### Decimation

Reduces sampling along one or more axes by selecting every N-th sample. Decimation can optionally include anti-aliasing filtering to prevent aliasing artifacts.

Decimation differs from rebin in that it performs index selection rather than aggregation.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Any when no anti-aliasing filter is applied; Linear when an anti-aliasing filter is applied
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved if no anti-aliasing filter is applied; Structure and value-modifying if an anti-aliasing filter is applied
- Coordinate Calibration: Uniform-sampled only; per-axis scale is multiplied by the decimation factor
- Intensity Calibration: preserved from input

**Parameters:**
- Axis or axes to decimate
- Decimation factors per axis
- Optional anti-aliasing method (none, gaussian, ideal)

**Notes:**
- Decimation by factor N is mathematically related to resampling by factor 1/N but uses index selection semantics rather than interpolation.
- The choice between decimation (index selection) and resampling (interpolation) depends on whether the desired operation is downsampling with or without value reconstruction.

#### Resample

Interpolates data to new sampling on one or more axes. Resampling may increase or decrease the number of samples. Common interpolation methods include linear, cubic, and band-limited interpolation. Resample operations update axis sizes and calibration scales to reflect new sampling rates.

Resample is mathematically equivalent to a uniform affine scale with interpolation, but is described here as a sampling-rate operation because it is specified by target sample count or rate rather than a coordinate matrix, and its primary output semantics are the new axis size and updated calibration.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear; RGB/RGBA accepted per channel
- Input Cardinality: Unary
- Output Value Type: preserved from input; integer storage is promoted to floating point unless an explicit rounding policy is supplied
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying
- Coordinate Calibration: Uniform-sampled only; per-axis scale is rescaled by the sampling-rate ratio
- Intensity Calibration: preserved from input

**Parameters:**
- Axis or axes to resample
- Target sample counts or sampling rates
- Interpolation method

**Notes:**
- On complex input, real and imaginary parts are interpolated independently. Interpolating magnitude and phase separately is a different operation and produces different results near phase wraps.

#### Pad

Extends the extent of one or more axes by adding synthetic values outside the current boundary. Padding increases axis sizes and adjusts calibration offsets to reflect the new origin.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved (existing values are retained unchanged; inserted values are synthesized by the pad mode)
- Coordinate Calibration: Calibration-agnostic; per-axis offset is retreated by the leading pad amount and scale is unchanged
- Intensity Calibration: preserved from input; synthesized pad values are interpreted in the input intensity calibration

**Parameters:**
- Axis or axes to pad
- Pad amounts per side (before, after)
- Pad mode (zero, constant, reflect, wrap, edge repeat, etc.)

### Geometric Transforms

Geometric transforms are a family of target axis-group operations that map positions in the input to positions in the output according to a coordinate transform, typically requiring interpolation of values at non-integer output positions. Most geometric transforms are therefore value-modifying, with grid-aligned special cases (for example, integer shift with wrap boundary handling) treated as layout-only.

When applied to a non-signal axis group, the coordinate transform restructures where signal values land in the output and requires signal interpolation (see `Effect of Non-Signal Target Selection`).

#### Shift (Translate)

Translates the target axis-group data along one or more axes by a specified offset. Shift is the translation component of an affine transform.

- **Integer shift**: a special case where all displaced positions remain on integer grid coordinates. No interpolation is required.
- **Fractional shift**: positions are displaced to non-integer output coordinates. Interpolation is required.
- **Fractional shift on a non-signal axis group**: signal values are displaced to sub-grid positions on the output grid and must be interpolated, even though the shift was expressed on the non-signal axis group.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Any for integer shift; Linear for fractional shift (RGB/RGBA accepted per channel)
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only for integer shift with wrap boundary handling; Value-modifying for integer shift with constant/edge/reflect boundary fill (new boundary values are introduced) and for all fractional shifts
- Coordinate Calibration: Calibration-agnostic for integer shift; Uniform-sampled only for fractional shift
- Intensity Calibration: preserved from input; any boundary fill value is interpreted in the input intensity calibration

**Parameters:**
- Axis or axes to shift
- Shift amount per axis (integer or fractional)
- Boundary fill value or boundary handling (zero, reflect, wrap)
- Interpolation method (for fractional shifts)

#### Arbitrary-Angle Rotation

Rotates the target axis-group data by an arbitrary angle. Output values are computed by interpolation since rotated input positions generally do not align to integer output coordinates.

**Compatibility:**
- Input Dimensionality: 2D
- Output Dimensionality: same as input
- Input Value Type: Linear; RGB/RGBA accepted per channel
- Input Cardinality: Unary
- Output Value Type: preserved from input; integer storage is promoted to floating point under interpolation
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Isotropic only. Anisotropic calibration requires manual scaling to physical coordinates before rotation, or the rotation will distort aspect ratios.
- Intensity Calibration: preserved from input

**Parameters:**
- Rotation angle
- Rotation center (pixel, calibrated, or axis-group center)
- Interpolation method
- Boundary handling (zero, reflect, wrap, etc.)
- **`rotate_components`** (boolean, default `false`): when the input is vector-valued, specifies whether the vector components at each position are also rotated by the same rotation matrix applied to positions. If `true`, both positions and vector components are transformed (physically correct for vector fields such as displacement or flow). If `false`, only positions are remapped; vector components retain their original orientation in the output frame (appropriate for pseudo-vector quantities or when component orientation is defined in a fixed external frame).

**Notes:**
- If input axes have anisotropic calibration (different scales/units), rotation in pixel space will distort the physical shape. Consider resampling to isotropic space first, or applying calibration-aware rotation.

#### Affine Transform

Applies a general affine transform (any combination of shift, scale, rotation, and shear) to the target axis-group. The transform is expressed as a matrix mapping input coordinates to output coordinates. Interpolation is required for all non-integer-exact transforms.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Any when the affine matrix is grid-preserving (integer translation, axis flips, and rotations by exact multiples of 90°), since no interpolation is required; Linear otherwise, with RGB/RGBA accepted per channel
- Input Cardinality: Unary
- Output Value Type: preserved from input; integer storage is promoted to floating point when interpolation is required
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only for a grid-preserving matrix with wrap boundary handling; Value-modifying for a grid-preserving matrix with boundary fill, and for any non-grid-preserving matrix under the `same as input` output shape policy; Structure and value-modifying when output shape is computed from transform bounds
- Coordinate Calibration: Isotropic only when the transform includes rotation or shear components; Anisotropic supported for pure shift and axis-aligned scale. Anisotropic calibration with rotation or shear may require calibration-aware transformation or pre-processing to isotropic space.
- Intensity Calibration: preserved from input

**Parameters:**
- Affine matrix (2×3 for 2D, 1×2 for 1D)
- Interpolation method
- Boundary handling
- Output shape policy (same as input, or computed from transform bounds)
- **`rotate_components`** (boolean, default `false`): when the input is vector-valued, specifies whether vector components at each position are transformed by the linear (rotation/shear/scale) part of the affine matrix in addition to positional remapping. If `true`, vector components are multiplied by the linear submatrix of the affine transform (physically correct for contravariant vector fields). If `false`, only positions are remapped; vector components retain their original orientation in the output frame.

**Notes:**
- For anisotropic calibration, rotation and shear components of the affine transform distort physical aspect ratios in pixel space. Consider transforming to calibration-aware (physical) coordinates if geometric fidelity is required.
- `Shift (Translate)` is the translation-only special case of this operation and is typed conditionally on the same grid-preserving/non-grid-preserving distinction. `Arbitrary-Angle Rotation` is not, because 90° rotations are routed to `Transpose (Flip, Rotate)` rather than handled as a special case within it. `Warp` is not, because grid alignment of a displacement field is a property of the field data rather than of the operation's parameters and so cannot be determined at invocation.

#### Warp

Applies a spatially varying displacement field to the target axis-group. Each output position is mapped to a (potentially fractional) input position according to a per-pixel displacement or coordinate map.

**Compatibility:**
- Input Dimensionality: 2D
- Output Dimensionality: same as input
- Input Value Type: Linear; RGB/RGBA accepted per channel
- Input Cardinality: Binary (target data + displacement field/coordinate map)
- Output Value Type: preserved from input; integer storage is promoted to floating point under interpolation
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Isotropic only. Pixel-based warping assumes isotropic space; calibration-aware warping requires explicit coordinate transformation when the displacement field encodes physically measured geometric structure.
- Intensity Calibration: preserved from input

**Parameters:**
- Displacement field or coordinate map (array of the same spatial extent as the target axis group)
- Interpolation method
- Boundary handling
- **`rotate_components`** (boolean, default `false`): when the input is vector-valued and the displacement field encodes a spatially varying deformation, specifies whether vector components at each position are rotated by the local Jacobian of the warp field in addition to positional remapping. If `true`, vector components are transformed by the local rotation implied by the displacement gradient (physically correct for vector fields that must follow the deformation). If `false`, only positions are remapped; vector components retain their original orientation in the output frame.

**Notes:**
- Displacement fields are typically defined in pixel space. If input has anisotropic calibration and warping is meant to be physically meaningful (e.g., removing optical distortion), the displacement field coordinates may need calibration adjustment.

### Filtering and Frequency-Domain Operations

These operations are another family of target axis-group operations. They apply filters in the spatial or frequency domain, or analyze spectral content.

FFT and inverse FFT are in this family because they are frequency-domain transforms of selected target axis-group data, even though they still follow the same target-operation execution model.

#### Spatial Filters

Linear and nonlinear filters that operate on local neighborhoods. All spatial filters operate on the signal axis group and may add or modify metadata describing filter parameters.

**Smoothing and Noise Reduction:**
- **Gaussian**: Applies a Gaussian blur with specified standard deviation.
- **Uniform (Box)**: Applies a uniform (box) filter with specified kernel size.
- **Median**: Applies a median filter with specified kernel size.
- **Bilateral**: Applies edge-preserving bilateral filtering with spatial and intensity standard deviations.

**Edge Detection and Enhancement:**
- **Sobel**: Applies a Sobel edge-detection filter (returns magnitude).
- **Prewitt**: Applies a Prewitt edge-detection filter as an alternative to Sobel.
- **Laplacian**: Applies a Laplacian filter for edge detection or second-derivative computation.
- **Unsharp Mask**: Sharpens the image by enhancing high-frequency components via subtraction of a blurred version.

**Morphological Operations:**
- **Erosion**: Reduces features by removing outer pixels; common on binary data.
- **Dilation**: Expands features by adding pixels; common on binary data.
- **Opening**: Erosion followed by dilation; removes small objects and noise.
- **Closing**: Dilation followed by erosion; fills small holes and gaps.

Morphological operations are most commonly applied to binary (boolean or thresholded) data.

**Compatibility:**
- Input Dimensionality: 1D or 2D for Gaussian, Uniform (Box), Median, Laplacian, and Unsharp Mask; 2D for Sobel, Prewitt, Bilateral, and the morphological operations
- Output Dimensionality: same as input
- Input Value Type by filter:
  - **Gaussian, Uniform (Box), Sobel, Prewitt, Laplacian, Unsharp Mask**: Linear
  - **Median, Bilateral**: Ordered
  - **Erosion, Dilation, Opening, Closing** (Morphological): Ordered (typically boolean or integer thresholded data)
- Input Cardinality: Unary (kernel sizes and standard deviations are scalar parameters, not array inputs)
- Output Value Type: preserved from input, except `Sobel` and `Prewitt`, which return a non-negative real scalar magnitude regardless of input sign
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying (extent is preserved; boundary handling supplies values outside the input extent)
- Coordinate Calibration: Uniform-sampled only when kernel sizes or standard deviations are expressed in calibrated units; Calibration-agnostic when they are expressed in samples
- Intensity Calibration: preserved by the smoothing and morphological filters; `Sobel`, `Prewitt`, and `Laplacian` produce intensity per coordinate unit when kernel spacing is calibrated

**Parameters:**
- Filter type
- Kernel size(s) or parameters (e.g., standard deviation for Gaussian, intensity difference threshold for bilateral)
- Boundary handling (zero-padding, reflection, etc.)
- RGB/RGBA handling policy for filters typed `Linear` (`per_channel` | `reject`; default `per_channel`). Filters typed `Ordered` (`Median`, `Bilateral`, and morphological operations) reject RGB/RGBA input regardless of this policy.

#### Convolution

Applies a user-defined kernel to the target axis group via convolution. Convolution is the fundamental operation underlying all spatial filtering; this operation enables custom kernels beyond predefined filters.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear
- Input Cardinality: Binary (primary input array + kernel array)
- Output Value Type: follows standard convolution algebra — complex if either input or kernel is complex; real if both are real
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying when output extent mode is `'same'`; Structure and value-modifying when output extent mode is `'valid'` or `'full'`
- Coordinate Calibration: Uniform-sampled only; output calibration offset shifts under `'valid'` and `'full'` extent modes to track the changed origin
- Intensity Calibration: product of the input and kernel intensity units; normalizing by kernel sum restores the input unit

**Parameters:**
- Kernel array (1D or 2D, matching dimensionality of target axis group)
- Output extent mode: `'same'` (output same size as input), `'valid'` (output smaller, no padding), `'full'` (output larger, full convolution extent)
- Boundary/padding handling: `zero`, `reflect`, `wrap`, `edge`, or equivalent explicit extension rule used when the kernel overhangs the input extent
- Optional bias/offset to add to convolution result
- Optional normalization (normalize by kernel sum, by kernel size, etc.)

**Current Limitations (Future Extensions):**
- Currently supported on **signal axis group only**
- Non-signal axis group convolution deferred (requires careful specification of boundary semantics and signal interpolation when needed)

**Notes:**
- Convolution with constant kernel is equivalent to linear filtering; all predefined spatial filters are special cases of convolution
- Common output extent modes: `'same'` most useful for filtering (preserves data size); `'valid'` for feature detection (only regions with full kernel overlap); `'full'` for exact mathematical convolution
- Computationally, small kernels use spatial-domain convolution; large kernels may internally use FFT-based convolution for efficiency
- Related to Cross-Correlate: convolution reverses the kernel; cross-correlation does not

#### FFT (Fast Fourier Transform)

Computes the discrete Fourier transform of the signal axis group along specified axes. FFT transforms the signal axis group into frequency space. Axes are reinterpreted with new calibrations reflecting frequency (reciprocal of the original calibration units).

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear
- Input Cardinality: Unary
- Output Value Type: complex (Hermitian-packed complex when the Hermitian output format is selected)
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying for full output; Structure and value-modifying for Hermitian output because the transformed extent is reduced along the transformed axis
- Coordinate Calibration: Uniform-sampled only; transformed axes receive reciprocal-unit calibration
- Intensity Calibration: determined by the selected scaling method; under `none` the output unit is the input unit scaled by the transform length `N`
- Domain: spatial-domain -> reciprocal-domain
- Spectrum Symmetry (output): `Hermitian` if and only if the input is real-valued; `Non-Hermitian` for complex input

**Parameters:**
- Axes to transform
- Optional output format (full, hermitian, etc.)
- Scaling method (see below)

**Scaling Methods:**

Each FFT and Inverse FFT operation independently chooses how to scale its output. Let `N` be the product of lengths of the transformed axes. For Hermitian storage, `N` is the full logical transform length along each transformed axis, not the number of stored elements. The choice of scaling determines both per-operation amplitudes and round-trip normalization:

- **None**: No explicit normalization by `N`.
- **1/√N**: Symmetric (unitary/orthonormal) normalization; preserves energy under the transform pair.
- **1/N**: Full normalization by `N` for that operation.

**Common Scaling Combinations:**
- FFT with no scaling + Inverse FFT with 1/N scaling -> exact round-trip reconstruction under the raw DFT/IDFT convention.
- FFT with 1/√N + Inverse FFT with 1/√N -> exact round-trip reconstruction with symmetric unitary normalization.
- FFT with 1/N scaling + Inverse FFT with no scaling -> exact round-trip reconstruction with amplitude-preserving forward spectrum (`X[0] = mean(x)`).
- FFT with no scaling + Inverse FFT with no scaling -> round-trip gain of `N`.

#### Inverse FFT

Computes the inverse discrete Fourier transform, returning from frequency space to the spatial domain.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Requires Complex
- Input Cardinality: Unary
- Output Value Type: complex; real scalar when the input is Hermitian and a real-valued result is requested
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying for full input; Structure and value-modifying for Hermitian input because the transformed extent expands along the reconstructed axis
- Coordinate Calibration: Uniform-sampled only; transformed axes receive reciprocal-unit calibration relative to the frequency axes
- Intensity Calibration: determined by the selected scaling method, mirroring the forward transform
- Domain: reciprocal-domain -> spatial-domain
- Spectrum Symmetry (input): `Either`; `Hermitian` input is accepted only when the caller asserts a real-valued result, which is what licenses reconstruction of the full spectrum

**Parameters:**
- Axes to transform
- Scaling method (see FFT scaling methods; chosen independently)

#### Auto-Correlate

Computes the auto-correlation of the array along specified axes, typically using FFT-based convolution. Auto-correlation measures self-similarity at different lags.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear
- Input Cardinality: Unary
- Output Value Type: preserved from input (real for real input, complex for complex input)
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying when output extent mode is `'same'`; Structure and value-modifying when output extent mode is `'valid'` or `'full'`
- Coordinate Calibration: Uniform-sampled only; output axes are lag axes carrying the input spatial units with the origin at zero lag
- Intensity Calibration: square of the input intensity unit; `unbiased` and `biased` normalization divide by a sample count and preserve that unit
- Domain: spatial-domain -> spatial-domain (lag domain); computed internally via the reciprocal domain

**Parameters:**
- Axes on which to compute auto-correlation
- Boundary/padding handling: `zero`, `reflect`, `wrap`, `edge`, or equivalent explicit extension rule used when the lag window overhangs the input extent
- Output extent mode: `'same'` (same extent as input), `'valid'` (smaller extent with only fully overlapping lags), or `'full'` (full lag extent)
- Optional normalization (unbiased, biased, etc.)

#### Cross-Correlate

Computes the cross-correlation between two arrays along specified axes, typically using FFT-based convolution. Cross-correlation measures similarity between arrays as a function of lag.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear
- Input Cardinality: Binary (primary input array + second input array)
- Output Value Type: real if both inputs are real; complex if either input is complex
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying when output extent mode is `'same'`; Structure and value-modifying when output extent mode is `'valid'` or `'full'`
- Coordinate Calibration: Uniform-sampled only; both inputs must share compatible axis calibration, and output axes are lag axes with the origin at zero lag
- Intensity Calibration: product of the two input intensity units; normalization divides by a sample count and preserves that unit
- Domain: spatial-domain -> spatial-domain (lag domain); computed internally via the reciprocal domain

**Parameters:**
- Second input array
- Axes on which to compute cross-correlation
- Boundary/padding handling: `zero`, `reflect`, `wrap`, `edge`, or equivalent explicit extension rule used when the lag window overhangs the input extent
- Output extent mode: `'same'` (same extent as primary input), `'valid'` (smaller extent with only fully overlapping lags), or `'full'` (full lag extent)
- Optional normalization (unbiased, biased, etc.)

#### Power Spectrum

Computes the power spectral density (PSD) of the data, quantifying the distribution of signal power across frequency components. Power spectrum is typically computed from the Fourier transform as the magnitude-squared of the frequency-domain representation.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear
- Input Cardinality: Unary
- Output Value Type: real scalar, non-negative (converts complex intermediate to real magnitude-squared)
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying (values are squared magnitudes and, in one-sided mode, the transformed extent is reduced)
- Coordinate Calibration: Uniform-sampled only; output axes carry reciprocal units
- Intensity Calibration: square of the input intensity unit; per-Hz scaling divides it by the frequency unit
- Domain: spatial-domain -> reciprocal-domain
- Spectrum Symmetry (input): `Hermitian` required in one-sided mode, which is therefore valid only for real-valued input; `Either` in two-sided mode

**Parameters:**
- Optional scaling/normalization method (one-sided vs. two-sided, per-Hz scaling, etc.)

**Output:**
- Real-valued array in frequency domain
  - Two-sided mode: frequency-domain shape matches the FFT output shape on transformed axes.
  - One-sided mode: Hermitian-reduced shape on transformed axes (for real-valued input), retaining non-negative frequencies only.
- Calibration axes reflect frequency units (reciprocal of input calibration units)

**Notes:**
- Applied to the full selected target axis-group domain.
- Power spectrum is mathematically |FFT(data)|² (with optional normalization applied independently).
- Windowing is NOT a parameter of this operation. Apply windowing as preprocessing before Power Spectrum, for example by generating a window (`Windowing Generators`) and applying it with `Multiply` to the selected target axis-group data. This keeps Power Spectrum orthogonal to preprocessing choices and consistent with the masking/preprocessing model.
- Often used in signal analysis to identify dominant frequency components.
- Windowing choice significantly affects spectral resolution vs. leakage trade-offs depending on signal characteristics.
- Related to FFT + magnitude operation chain; conceptually belongs in frequency-domain analysis family.

#### Frequency Domain Filter

Attenuates or preserves frequency components according to a configurable filter mode. Supports low-pass, high-pass, and bandpass filtering for noise reduction, trend removal, frequency band extraction, and frequency-response analysis.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear (real-valued only under the current limitation below)
- Input Cardinality: Unary; Binary when a custom symmetric mask array is supplied rather than a named mask type
- Output Value Type: preserved from input; under the current real-input-only limitation this means a real-valued output array
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying (frequency components are attenuated according to mode; extent is preserved)
- Coordinate Calibration: Uniform-sampled only; cutoff frequencies are interpreted against the reciprocal of the input axis calibration
- Intensity Calibration: preserved from input
- Domain: spatial-domain -> spatial-domain; computed internally via the reciprocal domain
- Spectrum Symmetry (internal): `Hermitian` — the frequency mask is real and symmetric, so the intermediate spectrum retains the Hermitian symmetry of the real input and the operation is zero-phase by construction

**Parameters:**
- **Filter mode**: `'low-pass'`, `'high-pass'`, or `'bandpass'`
  - Low-pass: attenuates high frequencies, preserves low frequencies
  - High-pass: attenuates low frequencies, preserves high frequencies
  - Bandpass: preserves frequencies within a specific band, attenuates outside
- **Cutoff frequency** (for low-pass and high-pass modes): expressed in frequency domain units (Hz, cycles/sample, normalized frequency [0, 1], or wavenumber/reciprocal-space units)
- **Lower and upper cutoff frequencies** (for bandpass mode only): same units as above
- Mask type: Gaussian, ideal (sharp brick-wall), Hann-windowed, or custom symmetric mask

**Output:**
- Spatial-domain array with the same shape as the input; output value type matches the input value type. Under the current real-input-only limitation, this means a real-valued output array.

**Current Limitations (Future Extensions):**
- Currently supported on **signal axis group only**
- Non-signal axis group filtering deferred
- Real-valued signals only (complex input: future extension)

**Notes:**
- Applied to the full selected target axis-group domain.
- Filter behavior is mathematically equivalent to: `ifft(fft(data) * frequency_mask)` where the mask is mode-dependent
  - Low-pass: mask = 1 at low frequencies, 0 at high
  - High-pass: mask = 0 at low frequencies, 1 at high
  - Bandpass: mask = 1 between lower and upper cutoff, 0 elsewhere
- Gaussian masks provide smooth transition (reduced ringing); ideal brick-wall masks may cause ringing artifacts
- Common use cases: noise reduction, anti-aliasing, signal smoothing (LP); detrending, edge enhancement, DC offset removal (HP); frequency band extraction, periodic component isolation, interference removal (BP)
- For bandpass, Q-factor or bandwidth specification available as alternative to explicit frequency bounds

### Value Transformations

Value transformations are another family of target axis-group operations. They modify individual element values according to mathematical rules, without changing the selected target axis-group structure.

#### Math Functions

Point-wise arithmetic operations:

- **Add**: Element-wise addition with a scalar or compatible array.
- **Subtract**: Element-wise subtraction.
- **Multiply**: Element-wise multiplication.
- **Divide**: Element-wise division.
- **Negate**: Element-wise negation.
- **Absolute Value**: Element-wise absolute value (`abs`) for scalar-valued inputs.

**Compatibility:**
- Input Dimensionality: 0D, 1D, or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear; `Absolute Value` additionally accepts complex input and returns real magnitude
- Input Cardinality: Binary for `Add`, `Subtract`, `Multiply`, and `Divide` when the second operand is array-valued; Unary for `Negate`, `Absolute Value`, and scalar-operand forms of arithmetic operations
- Output Value Type: promoted type of the operands (real + complex -> complex; integer + float -> float); `Absolute Value` converts complex to real scalar
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Calibration-agnostic; array operands must be broadcast-compatible and carry matching coordinate calibration
- Intensity Calibration: combined by the operation: `Multiply` and `Divide` produce product and ratio units respectively; `Add` and `Subtract` require matching intensity units and preserve them; `Negate` and `Absolute Value` preserve

**Notes:**
- These operations may also include broadcasting rules when combining arrays of different shapes. Metadata and calibrations are propagated or adjusted according to the operation semantics.

#### Value-Type Cast

Converts array values between compatible value/storage types while preserving shape, axis groups, and calibrations.

Common casts include integer-to-float promotion, float precision changes, scalar-to-complex casting (zero imaginary part), and compatible channel/storage casts for RGB/RGBA representations.

**Compatibility:**
- Input Dimensionality: 0D, 1D, or 2D
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: the requested target value/storage type
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying (rounding and saturation may alter values; a lossless widening cast is the degenerate case in which no value changes)
- Coordinate Calibration: Calibration-agnostic; carried through unchanged
- Intensity Calibration: preserved from input

**Parameters:**
- Target value/storage type
- Rounding policy (for float-to-integer casts)
- Saturation/clipping policy (for bounded target types)
- Complex-cast policy (e.g., keep real part only, or reject non-zero imaginary input)

#### Complex Construction

Constructs complex-valued arrays from scalar inputs.

- **Real/Imaginary (R/I) Construction**: Builds complex values from separate real and imaginary arrays.
- **Magnitude/Phase (M/P) Construction**: Builds complex values from magnitude and phase arrays.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear (real scalar inputs)
- Input Cardinality: Binary (two real scalar arrays)
- Output Value Type: complex (converts real scalar to complex)
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Calibration-agnostic; both inputs must carry matching coordinate calibration
- Intensity Calibration: in `real_imag` mode both inputs must share an intensity unit, which is preserved; in `magnitude_phase` mode the magnitude unit is preserved and the phase input must be angular

**Parameters:**
- Construction mode: `real_imag` | `magnitude_phase`
- Input arrays (shape-compatible under broadcasting/alignment rules)
- Phase units (radians or degrees, for M/P mode)

**Output:**
- Complex-valued array

#### Vector Construction

Constructs vector-valued arrays from scalar component inputs.

- **Component Packing**: Combines component arrays (e.g., x, y, z) into vector values.
- **Magnitude/Direction Construction**: Builds vectors from magnitude plus direction representation (for supported dimensions).

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear (real scalar inputs)
- Input Cardinality: N-ary (one array per component, or magnitude plus direction arrays)
- Output Value Type: vector (converts real scalar to vector); component count equals the number of packed inputs
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Calibration-agnostic; all component inputs must carry matching coordinate calibration
- Intensity Calibration: all component inputs must share an intensity unit, which is preserved on the vector output

**Parameters:**
- Construction mode and target component count
- Component arrays or magnitude+direction inputs
- Coordinate convention (e.g., Cartesian, polar for 2D direction)

**Output:**
- Vector-valued array

#### RGB/RGBA Construction

Constructs RGB/RGBA arrays from scalar channel inputs.

- **Channel Combine**: Combines separate channel arrays into RGB or RGBA values.
- **Alpha Injection**: Adds an alpha channel to RGB input using a constant or array-valued alpha.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear (real scalar channel inputs) for `Channel Combine`; Requires RGB/RGBA for the primary input of `Alpha Injection`
- Input Cardinality: N-ary for `Channel Combine`; Binary for `Alpha Injection` with an array-valued alpha, Unary with a constant alpha
- Output Value Type: RGB (3 channels) or RGBA (4 channels)
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Calibration-agnostic; all channel inputs must carry matching coordinate calibration
- Intensity Calibration: the channel value-range convention of the inputs becomes the output intensity convention

**Parameters:**
- Target format: `rgb` | `rgba`
- Channel arrays (R, G, B, optional A)
- Channel ordering policy
- Channel value-range policy (e.g., normalized float vs integer range)

**Output:**
- RGB- or RGBA-valued array

#### Complex-to-Real Conversion

Extracts real-valued quantities from complex-valued arrays:

- **Magnitude**: Computes the absolute value (modulus) of complex elements.
- **Real**: Extracts the real part.
- **Imaginary**: Extracts the imaginary part.
- **Phase**: Computes the phase angle.

**Compatibility:**
- Input Dimensionality: 0D, 1D, or 2D
- Output Dimensionality: same as input
- Input Value Type: Requires Complex
- Input Cardinality: Unary
- Output Value Type: real scalar (converts complex to scalar); `Magnitude` is non-negative
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Calibration-agnostic
- Intensity Calibration: preserved by `Magnitude`, `Real`, and `Imaginary`; `Phase` replaces it with an angular unit (radians by default) and requires a stated wrapping convention

**Notes:**
- These operations change the value type from complex to scalar and may adjust calibration units (e.g., magnitude preserves units; phase may be expressed in radians).
- `Domain` and `Spectrum Symmetry` are not recorded for these operations. They are value transformations that neither read nor change the domain interpretation of their input: the modulus of a complex value is the same computation whether the array is spatial or reciprocal. That complex data frequently originates from an FFT is a fact about usage, not a property of the operation.

#### RGB-to-Real Conversion

Extracts scalar values from multi-channel color data:

- **Extract Channel**: Selects a specific color channel (red, green, blue, or alpha).
- **Brightness**: Computes brightness using a specified method:
  - **Luminance**: Weighted combination (e.g., ITU-R BT.709: 0.2126·R + 0.7152·G + 0.0722·B).
  - **Simple Average**: Unweighted average of color channels.
  - **Maximum**: Maximum across channels.
  - **Minimum**: Minimum across channels.

**Compatibility:**
- Input Dimensionality: 0D, 1D, or 2D
- Output Dimensionality: same as input
- Input Value Type: Requires RGB/RGBA
- Input Cardinality: Unary
- Output Value Type: real scalar (converts RGB/RGBA to scalar)
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Calibration-agnostic
- Intensity Calibration: the channel value-range convention of the input carries into the output

**Notes:**
- These operations change the value type from RGB or RGBA to scalar.

#### Vector-to-Real Conversion

Extracts real-valued quantities from vector-valued arrays:

- **Magnitude**: Computes the Euclidean norm (length) of vector elements.
- **Component**: Extracts a specific vector component (e.g., x, y, z from a 3D vector).
- **Dot Product**: Computes the dot product of each vector with a reference direction, producing a scalar projection.
- **Angle**: Computes the angle between each vector and a reference direction.

**Compatibility:**
- Input Dimensionality: 0D, 1D, or 2D
- Output Dimensionality: same as input
- Input Value Type: Requires Vector
- Input Cardinality by operation: `Dot Product` and `Angle` are Binary when the reference direction is array-valued and Unary when it is constant; `Magnitude` and `Component` are Unary
- Output Value Type: real scalar (converts vector to scalar); `Magnitude` is non-negative
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Calibration-agnostic
- Intensity Calibration: `Magnitude` and `Component` preserve; `Dot Product` produces product units; `Angle` replaces it with an angular unit

**Notes:**
- These operations change the value type from vector to scalar. Magnitude preserves calibration units; angle is typically expressed in radians or degrees.

#### Vector-to-Vector Transformation

Transforms vector-valued arrays while preserving vector value type:

- **Normalize**: Scales each vector to unit length (Euclidean norm = 1).
- **Scale Magnitude**: Scales the magnitude of each vector by a scalar factor while preserving direction.
- **Rotate**: Rotates vectors by a rotation matrix (2D or 3D depending on vector dimensionality).
- **Project**: Projects each vector onto a target vector subspace (for example, a plane in 3D), preserving vector-valued output in the same coordinate basis.
- **Cross Product**: Computes the cross product between two vector fields (3D vectors only), producing a new vector-valued array.
- **Coordinate Transform**: Transforms between coordinate systems (e.g., Cartesian to polar, Cartesian to spherical) while preserving vector semantics.

**Compatibility:**
- Input Dimensionality: 0D, 1D, or 2D
- Output Dimensionality: same as input
- Input Value Type: Requires Vector; `Cross Product` requires 3-component vectors
- Input Cardinality by operation: `Cross Product` is Binary when the second vector field is array-valued and Unary when the second operand is constant; `Normalize`, `Scale Magnitude`, `Rotate`, `Project`, and `Coordinate Transform` are Unary when their additional parameters are constant
- Output Value Type: vector (preserved); `Project` reduces the component count to the dimension of the target subspace
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Calibration-agnostic
- Intensity Calibration: `Normalize` discards it (output is dimensionless); `Cross Product` produces product units; the remaining operations preserve it

**Notes:**
- These operations preserve the vector value type and may require a reference direction, rotation matrix, or target plane depending on the operation.
- Projection onto a single direction (yielding a scalar) is covered under `Vector-to-Real Conversion` as `Dot Product`.

#### Thresholding

Applies a threshold operation with specified output format.

- **Boolean Output**: Returns True/False for values above/below the threshold.
- **Zero Output**: Returns the original value for values above the threshold, 0.0 for values below.

**Compatibility:**
- Input Dimensionality: 0D, 1D, or 2D
- Output Dimensionality: same as input
- Input Value Type: Ordered
- Input Cardinality: Unary; Binary when the threshold is supplied as a per-element array rather than a scalar
- Output Value Type: boolean in `Boolean Output` mode; preserved from input in `Zero Output` mode
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying
- Coordinate Calibration: Calibration-agnostic
- Intensity Calibration: threshold values are interpreted in the input intensity calibration; `Boolean Output` discards it, `Zero Output` preserves it

**Parameters:**
- Threshold value(s)
- Comparison method (below, above, outside range, inside range, etc.)
- Output format

### Analysis and Feature Extraction

Analysis, statistics, and feature-extraction operations are target axis-group operation families. They do not transform their input in place; they compute derived results whose extent, value type, and container may be unrelated to the input. Most carry reduction semantics that lower dimensionality.

#### Statistics

Compute scalar summary statistics.

- **Mean**: Average value (per axis, per axis group, or global).
- **Sum**: Aggregate sum.
- **Min/Max**: Minimum and maximum values.
- **Argmin/Argmax**: Index location(s) of minimum and maximum values.
- **Standard Deviation**: Measure of dispersion.
- **Median**: Median value.
- **Quantile**: Arbitrary quantile values.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: input rank minus the number of reduced axes; 0D for a full reduction
- Input Value Type by statistic:
  - **Mean, Sum**: Linear
  - **Standard Deviation**: Linear
  - **Min/Max, Argmin/Argmax, Median, Quantile**: Ordered
- Input Cardinality: Unary
- Output Value Type: preserved from input for `Mean` and `Sum`; real scalar for `Standard Deviation`; real scalar for `Min/Max`, `Median`, and `Quantile`; integer index or vector-valued index coordinate for `Argmin`/`Argmax`
- Output Container Model: Annotated Array (0-D scalar array for a full reduction)
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying (reduced axes are removed and the retained values are aggregates rather than input elements)
- Coordinate Calibration: Calibration-agnostic; reduced axes are removed from the output descriptor. `Argmin`/`Argmax` require Calibrated coordinates when the calibrated-coordinate output mode is selected.
- Intensity Calibration: preserved by `Mean`, `Min`, `Max`, `Median`, `Quantile`, and `Standard Deviation`; `Sum` accumulates the input unit; `Argmin`/`Argmax` return positions and carry the coordinate unit instead

Statistics may be computed globally, along specific axes, or on data that has already been structurally selected and optionally pre-masked.

**Output:**
- Reduction over all selected elements produces a 0-D scalar array.
- Reduction over a subset of axes produces reduced-rank arrays (1D or higher as determined by remaining axes).
- For `Argmin`/`Argmax`, reducing over one axis returns an integer index array over the remaining axes; reducing over multiple axes returns one index tuple per output element (vector-valued coordinate output). Optional output mode may convert those coordinates to calibrated coordinates.

For standard deviation, output is real-valued. On complex input, standard deviation is defined from variance `E[|x - μ|^2]`. On vector input, an explicit policy is required (per-component standard deviation vs. norm-based reduction).

**Parameters:**
- Statistic type
- Axis or axes along which to compute (reduces dimensionality)
- Optional output mode for index-returning statistics (raw index coordinates or calibrated coordinates)
- Optional selection specification handled before the operation

**Note on `Sum`:** The overlap between this operation and `Summation` under `Higher-Order Operations` is intentional. `Statistics` -> `Sum` is a target axis-group reduction defined on selected target data. `Summation` is an orchestration-level operation over iteration space with its own index and range selection modes. The two occupy different execution scopes and are both retained deliberately.

#### Histogram

Computes a histogram of values within the array, with flexible scope options. Histograms measure the distribution of values and support multiple levels of aggregation.

**Scope Options:**

- **Whole Data**: Computes a single histogram of all values across the entire annotated array. Returns a 1D histogram array.
- **Per Axis Group**: Computes a histogram for values within a specified axis group only (e.g., signal axis group), excluding values from other axis groups. Returns a 1D histogram array.
- **Per Sequence Element**: When the array contains a sequence axis, computes a separate histogram for each element along the sequence. Returns a 2D array where the first axis corresponds to sequence elements and the second to histogram bins. Useful for tracking value distribution evolution across acquisition sequences.

**Use Cases:**

- **Whole data histograms** are most common for understanding the overall value distribution.
- **Per axis group histograms** are useful in scientific workflows where you care about signal value distributions specifically, separate from collection or sequence metadata structure.
- **Per-sequence-element histograms** reveal how distributions vary across individual elements in a sequence (e.g., how signal evolves through time steps or acquisitions).

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: 1D in `whole` and `axis_group` scope; 2D in `per_sequence` scope
- Input Value Type: Ordered
- Input Cardinality: Unary; Binary when an explicit weighting array is supplied
- Output Value Type: integer counts, or real scalar when weighting or `probability`/`density` normalization is applied
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying (input axes are replaced by a bin axis and values become counts)
- Coordinate Calibration: Calibration-agnostic for input coordinate calibration, which is discarded
- Intensity Calibration: the input intensity calibration becomes the calibration of the output bin axis; the count axis is dimensionless

**Parameters:**
- Number of bins
- Value range (or automatic range detection)
- Scope: `"whole"` (default) | `"axis_group"` | `"per_sequence"`
- Target axis group (when scope is `"axis_group"`, typically `"signal"`)
- Optional selection or masking handled before the operation
- Optional axis weighting (e.g., compute weighted histogram)

#### Multivariate Histogram Analysis

Computes joint histograms across two or more variables to analyze relationships between dimensions or channels.

- **2D Joint Histogram**: Counts co-occurrence in paired variables (for example, channel A vs. channel B, or intensity vs. gradient).
- **N-D Joint Histogram**: Generalized co-occurrence counts across multiple variables.
- **Marginal Histograms**: Optional marginals per variable derived from the joint histogram.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: rank equals the number of participating variables
- Input Value Type: Ordered
- Input Cardinality: Unary when the variables are axes or channels of one array; N-ary when each variable is supplied as a separate array
- Output Value Type: integer counts, or real scalar under weighting or `probability`/`density` normalization
- Output Container Model: Annotated Array
- Output Cardinality: Unary by default; Fixed N-ary when per-variable marginals are requested as separate outputs
- Data-Modification Behavior: Structure and value-modifying (input axes are replaced by one bin axis per variable and values become counts)
- Coordinate Calibration: Calibration-agnostic for input coordinate calibration, which is discarded
- Intensity Calibration: each output bin axis inherits the intensity calibration of its corresponding variable; the count axis is dimensionless

**Parameters:**
- Variables/axes/channels to include (2 to N)
- Bin count per variable
- Value range per variable (or automatic range detection)
- Optional weighting
- Optional normalization (`count`, `probability`, or `density`)

**Output:**
- N-dimensional histogram array where each axis corresponds to one input variable
- Optional per-variable marginal histograms

**Notes:**
- Useful for correlation structure analysis, feature-space inspection, and multi-channel classification workflows.
- A 2D joint histogram is a common special case.

#### Derivative Operations (1st and 2nd)

Computes numerical derivatives along selected axes for slope, curvature, and edge/feature characterization.

- **First Derivative**: Estimates local rate of change.
- **Second Derivative**: Estimates curvature and inflection behavior.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear
- Input Cardinality: Unary
- Output Value Type: preserved from input; integer storage is promoted to signed floating point because derivatives are signed
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying (extent is preserved; boundary handling supplies end values)
- Coordinate Calibration: Uniform-sampled only. Calibrated coordinates are required when the spacing source is calibrated.
- Intensity Calibration: intensity per coordinate unit; per coordinate unit squared for second derivatives

**Parameters:**
- Derivative order (`1` or `2`)
- Axis or axes to differentiate
- Spacing source (unit spacing or calibrated spacing)
- Numerical method (`forward`, `backward`, `central`)
- Boundary handling at axis ends

**Output:**
- Derivative array with same shape as input

**Notes:**
- First derivative is commonly used for gradient/slope analysis.
- Second derivative is commonly used for peak refinement and edge/feature enhancement.
- Calibrated spacing should be used when derivatives are interpreted in physical units.

#### Savitzky-Golay Filtering and Derivatives

Applies local polynomial regression to smooth data and optionally compute stable first or second derivatives.

- **Savitzky-Golay Smoothing**: Preserves peak shape better than many moving-average smoothers.
- **Savitzky-Golay Derivative**: Computes derivative estimates from fitted local polynomials.

**Compatibility:**
- Input Dimensionality: 1D (primary); 2D as an optional extension via separable application per axis
- Output Dimensionality: same as input
- Input Value Type: Linear
- Input Cardinality: Unary
- Output Value Type: preserved from input; integer storage is promoted to floating point
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Value-modifying (extent is preserved; boundary mode supplies end values)
- Coordinate Calibration: Uniform-sampled only. Calibrated coordinates are required when the spacing source is calibrated.
- Intensity Calibration: preserved at derivative order `0`; intensity per coordinate unit at orders `1` and `2`

**Parameters:**
- Window length (odd integer)
- Polynomial order
- Derivative order (`0`, `1`, or `2`)
- Axis to process
- Spacing source (unit spacing or calibrated spacing)
- Boundary mode

**Output:**
- Smoothed or derivative array with same shape as input

**Notes:**
- This operation is a convenience function that combines smoothing and derivative estimation.
- Particularly useful for noisy spectroscopy and line-profile analysis.
- Polynomial order must be less than window length.

#### Peak Detection and Fitting

Operations for identifying and characterizing peaks (local maxima) in 1D and 2D data:

- **Peak Detection**: Identifies local maxima (peaks) in the data.
  - **1D**: Detects peaks along an axis; useful for spectroscopy and signal analysis.
  - **2D**: Detects local maxima in 2D arrays (images); useful for particle detection and feature localization.
  - **Parameters**: Detection threshold/prominence, minimum separation between peaks, optional smoothing pre-processing.

- **Peak Fitting**: Fits parametric models to identified peaks or peak regions.
  - **1D**: Fits models (Gaussian, Lorentzian, Voigt, etc.) to 1D peak profiles; commonly used in spectroscopy.
  - **2D**: Fits 2D models (2D Gaussian, 2D Lorentzian, etc.) to 2D peak regions; useful for sub-pixel localization of features.
  - **Parameters**: Model type, initial guess or ROI around peak, fit method (least-squares, max-likelihood), optional background subtraction.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: n/a — output is a Structured Table, which has no array rank
- Input Value Type: Ordered (detection requires comparison of neighboring values)
- Input Cardinality: Unary (`Peak Fitting` additionally consumes a peak table, which is structured data rather than an array input)
- Output Value Type: n/a — the output is a structured table of per-peak records, not an array of semantic values
- Output Container Model: Structured Table (peak list / fitted-parameter table), optionally Mixed Bundle when combined with derived masks or overlays
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — output is a Structured Table, with no output array to compare against the input
- Coordinate Calibration: Uniform-sampled only. Calibrated coordinates are required when peak positions and fitted widths are to be reported in physical units.
- Intensity Calibration: fitted amplitudes carry the input intensity unit; fitted positions and widths carry the coordinate unit

#### Particle Finding (Planned)

Planned general algorithms for identifying and characterizing particle-like features in 2D target axis-group data.

**Compatibility:**
- Input Dimensionality: 2D
- Output Dimensionality: n/a — output is a Structured Table, which has no array rank
- Input Value Type: Ordered
- Input Cardinality: Unary
- Output Value Type: n/a — the output is a structured table of per-particle records, not an array of semantic values
- Output Container Model: Structured Table (particle table), optionally Mixed Bundle when derived masks/overlays are emitted
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — output is a Structured Table, with no output array to compare against the input
- Coordinate Calibration: Isotropic only for shape and size criteria; Calibrated coordinates required for physical-unit reporting
- Intensity Calibration: intensity fields of the particle table carry the input intensity unit; geometric fields carry coordinate units

This section is intentionally high-level until concrete implementation and API details are finalized.

Potential capabilities include:

- **Particle Detection**: Find candidate particle positions from local contrast/shape criteria.
- **Particle Characterization**: Estimate properties such as centroid, area, intensity, and orientation.
- **Particle Filtering**: Keep or reject candidates based on size, shape, intensity, or confidence criteria.

Potential outputs include a structured particle table and optional derived masks or overlays.

Potential parameters include detection scale, thresholding strategy, expected size range, and post-filter criteria.

#### Connected Component Analysis (Labeling)

Identifies and labels spatially connected regions (components) in binary or thresholded 2D data. This operation is essential for separating distinct features and analyzing their properties.

- **Connected Component Labeling**: Assigns unique integer labels to each distinct connected region. Regions may be defined by:
  - **4-connectivity**: Regions connected through orthogonal neighbors (up, down, left, right).
  - **8-connectivity**: Regions connected through orthogonal and diagonal neighbors.
  - **Custom connectivity**: User-defined connectivity patterns.

- **Output**: A labeled array where each pixel contains the integer label (ID) of its component, plus a component table with properties (size, bounding box, centroid location, etc.).

**Compatibility:**
- Input Dimensionality: 2D
- Output Dimensionality: same as input for the labeled array; n/a for the component table
- Input Value Type: Ordered (boolean or thresholded integer data)
- Input Cardinality: Unary
- Output Value Type: integer scalar labels for the labeled array
- Output Container Model: Mixed Bundle (labeled annotated array + component table)
- Output Cardinality: Binary
- Data-Modification Behavior: Value-modifying for the labeled array (extent is preserved; values are replaced by integer labels); n/a for the component table, which is not an array
- Coordinate Calibration: Calibration-agnostic for the labeled array, which inherits input coordinate calibration. Isotropic only for the geometric fields of the component table (bounding box extent, centroid distances).
- Intensity Calibration: n/a for the labeled array, whose integer labels are identifiers rather than measured values; intensity fields of the component table carry the input intensity unit

**Parameters:**
- Connectivity mode (4-connectivity, 8-connectivity, or custom)
- Background/foreground identification (e.g., zero = background, non-zero = foreground)
- Optional size filtering (e.g., discard components smaller than N pixels)

**Notes:**
- Often applied after thresholding or peak detection to identify distinct feature regions.
- Output component table is structured data (not a regular array) and may be represented as a separate output or metadata extension.
- Complements peak detection by identifying extended features rather than point maxima.

#### Shape Descriptors

Computes morphological and geometric properties of regions or features in 2D data. Shape descriptors characterize detected features and are commonly computed from labeled components or peak regions.

- **Area**: Total pixel count or calibrated area for each region.
- **Perimeter**: Boundary length of each region (reported in pixels or calibrated distance).
- **Centroid**: Center of mass coordinates for each region.
- **Bounding Box**: Minimum and maximum coordinates along each axis.
- **Eccentricity**: Elongation measure from the best-fit ellipse, `e = sqrt(1 - b^2/a^2)` with `a >= b` (0 = circle, approaching 1 = line).
- **Circularity**: Compactness measure, typically `4π * area / perimeter^2` (1 = perfect circle).
- **Solidity**: Ratio of region area to convex hull area (1 = convex region).
- **Aspect Ratio**: Ratio of major-axis to minor-axis length.
- **Orientation**: Angle of major axis relative to horizontal.

**Compatibility:**
- Input Dimensionality: 2D
- Output Dimensionality: n/a — output is a Structured Table, which has no array rank
- Input Value Type: Ordered (an integer label array from Connected Component Analysis, or a detected peak list)
- Input Cardinality: Unary
- Output Value Type: n/a — the output is a structured table of per-region records, not an array of semantic values
- Output Container Model: Structured Table (descriptor table)
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — output is a Structured Table, with no output array to compare against the input
- Coordinate Calibration: Isotropic only for `Perimeter`, `Circularity`, `Eccentricity`, `Aspect Ratio`, and `Orientation`; Anisotropic supported for `Area`, `Centroid`, and `Bounding Box` when per-axis scales are applied. Calibrated coordinates required for physical-unit reporting.
- Intensity Calibration: n/a — shape descriptors are geometric and carry coordinate units or are dimensionless ratios; none carries the input intensity unit

**Parameters:**
- Feature source (labeled component array from Connected Component Analysis, or detected peak list)
- Which descriptors to compute
- Optional calibration units for area and perimeter
- Optional background/foreground logic

**Notes:**
- Typically applied after peak detection, particle finding, or connected component analysis.
- Provides quantitative metrics for feature classification and filtering workflows.
- For physically meaningful geometric descriptors, anisotropic calibration must be handled explicitly. `Perimeter`, `Circularity`, `Eccentricity`, `Aspect Ratio`, and `Orientation` can be biased if computed directly in pixel space with unequal axis scales.
- Preferred approaches for anisotropic data are calibration-aware metric computation or resampling to isotropic coordinates before descriptor extraction.

#### Image Moments

Computes statistical moments of image regions, which characterize spatial distribution and shape properties. Moments are fundamental for sub-pixel feature localization and shape analysis.

- **Spatial Moments**: Zero-order (M₀₀ = area), first-order (centroid coordinates), and higher-order moments up to user-specified degree.
- **Central Moments**: Moments computed relative to the centroid (invariant to translation).
- **Normalized Central Moments**: Central moments normalized by M₀₀ (invariant to scale).
- **Hu Moments**: Seven moment invariants (invariant to rotation, scale, and translation); useful for shape recognition.

**Compatibility:**
- Input Dimensionality: 1D or 2D
- Output Dimensionality: n/a — output is a Structured Table, which has no array rank
- Input Value Type: Linear
- Input Cardinality: Unary; Binary when an explicit region mask array is supplied
- Output Value Type: n/a — the output is a structured table of moment values, not an array of semantic values
- Output Container Model: Structured Table (moment table/invariant table)
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — output is a Structured Table, with no output array to compare against the input
- Coordinate Calibration: Anisotropic supported for raw spatial and central moments computed in index space; Isotropic only for `Normalized Central Moments` and `Hu Moments`, whose rotation invariance assumes equal axis scales
- Intensity Calibration: raw and central moments carry the input intensity unit multiplied by coordinate units raised to the moment order; normalized central and Hu moments are dimensionless

**Parameters:**
- Moment type (spatial, central, normalized central, or Hu invariants)
- Maximum moment order (for spatial and central moments)
- Optional region mask or component selection
- Optional intensity weighting (compute weighted vs. unweighted moments)

**Common Uses:**
- **Centroid refinement**: Use first-order moments to localize features at sub-pixel precision.
- **Inertia tensor**: Second-order moments (M₂₀, M₁₁, M₀₂) form inertia tensor; used to compute principal axes and orientation.
- **Shape classification**: Hu moment invariants enable shape matching independent of pose and scale.
- **Background subtraction**: Weighted moments allow intensity-based feature analysis.

**Notes:**
- Often computed from regions identified by peak detection, particle finding, or connected components.
- Moments are building blocks for many advanced feature descriptors and can be composed into custom metrics.

#### Line Profile and Radial Profile

Extract 1D intensity distributions from 2D data for analysis along specific geometric paths or distances.

- **Line Profile**: Extracts intensity values along a specified line segment within a 2D image.
  - **Parameters**: Start point, end point, interpolation method, optional line width
  - **Output**: A 1D array of intensity values sampled along the line, with optional distance calibration
  - **Common Uses**: Analyzing intensity trends across features, measuring gradients, evaluating contrast

- **Radial Profile**: Extracts intensity as a function of distance from a center point in 2D data.
  - **Parameters**: Center point, radial extent, optional angular extent (for angular sectors), radial binning method
  - **Output**: A 1D or 2D array depending on whether angular extent is specified (1D radial histogram or 2D radial-angular map)
  - **Common Uses**: Analyzing radial symmetry, measuring particle size distributions, studying circular features

**Compatibility:**
- Input Dimensionality: 2D
- Output Dimensionality: 1D for `Line Profile` and for `Radial Profile` without angular extent; 2D for `Radial Profile` with angular extent
- Input Value Type: Linear; RGB/RGBA accepted per channel for `Line Profile`
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying (input spatial axes are replaced by a distance axis, optionally with an angle axis)
- Coordinate Calibration:
  - **Line Profile**: Anisotropic supported, but under anisotropic calibration the distance along an arbitrary line segment is not represented by a single pixel-unit scale. The output distance axis must be calibration-aware (computed from physical coordinates or an equivalent anisotropy-aware mapping).
  - **Radial Profile**: Isotropic only for physically meaningful results. With anisotropic calibration, "radial distance" becomes elliptical in pixel space, distorting measured radii. If anisotropic input is provided, consider resampling to isotropic space first or applying calibration-aware distance metrics.
- Intensity Calibration: preserved from input

**Notes:**
- Line profiles and radial profiles are 1D projections derived from 2D data; results are lower-dimensional analysis arrays.
- Both operations typically use interpolation to handle sub-pixel positions along the extraction path.
- Often used for visualizing and quantifying spatial intensity patterns without full feature detection.
- For anisotropic calibration, output distance/spatial axes should reflect calibration units; pure pixel-based radial profiles may be physically misleading.

## Data Reshaping Primitives

These operations change dimensional interpretation or axis-group structure. They are higher-order reshaping primitives rather than target axis-group 1D/2D processing operations.

Because they operate on the descriptor rather than on a selected 1D/2D target, they record `n/a` for `Dimensionality`.

Concatenate and stack are intentionally defined under `Sequence and Collection Operations` rather than here. They compose multiple input arrays and define inter-element organization, while reshaping primitives reinterpret a single array's descriptor/axis-group structure.

### Squeeze

Removes axes of size 1 from an axis group.

`squeeze` belongs in reshaping rather than target axis-group processing because it acts on dimensional structure (descriptor shape and axis-group rank), not on value-domain neighborhoods or transforms of selected 1D/2D target data.

**Compatibility:**
- Input Dimensionality: n/a — operates on descriptor rank, not a selected target rank
- Output Dimensionality: input rank minus the number of removed size-1 axes
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only
- Coordinate Calibration: Calibration-agnostic; the calibration of each removed axis is discarded unless retained in an extension record
- Intensity Calibration: preserved from input

**Parameters:**
- Axis group or specific axes of size 1 to remove

### Redimension

Moves axes from one axis group to another. This operation restructures the logical organization (descriptor/axis-group interpretation) of an annotated array without changing per-element values. For example, moving a channel axis from the collection axis group to the signal axis group changes how the array is interpreted without modifying values.

Semantically, `redimension` is descriptor-level reinterpretation. Implementations may realize this as a view-only remap or may materialize/reorder storage for execution reasons; such realization details are not part of the operation definition.

**Compatibility:**
- Input Dimensionality: n/a — operates on axis-group membership, not a selected target rank
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only
- Coordinate Calibration: Calibration-agnostic; each moved axis carries its calibration into the target axis group unchanged
- Intensity Calibration: preserved from input

**Parameters:**
- Axes to move
- Source axis group
- Target axis group
- Position within target axis group

### Expand Dims (`unsqueeze`)

Inserts a size-1 axis at a specified position in an axis group.

`expand_dims` is the structural inverse of `squeeze` and is useful when preparing data for broadcasting, alignment, or explicit axis-group conventions.

**Compatibility:**
- Input Dimensionality: n/a — operates on descriptor rank, not a selected target rank
- Output Dimensionality: input rank plus one
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only
- Coordinate Calibration: Calibration-agnostic; the inserted axis receives calibration per the axis label/calibration policy parameter, defaulting to unit integer indexing
- Intensity Calibration: preserved from input

**Parameters:**
- Axis group in which to insert the axis
- Insertion position
- Optional axis label/calibration policy for the inserted axis

### Flatten

Merges multiple axes into one axis within a specified axis group (or across an explicitly permitted boundary), producing a lower-rank descriptor interpretation.

Flatten does not modify per-element values; it changes structural interpretation and axis calibration mapping.

**Compatibility:**
- Input Dimensionality: n/a — operates on descriptor rank, not a selected target rank
- Output Dimensionality: input rank minus the number of merged axes, plus one
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only
- Coordinate Calibration: Calibration-agnostic. Merging two calibrated axes generally produces an axis with no meaningful linear calibration; the default merge policy drops calibration on the merged axis and records the originals for later reversal by `Unflatten`.
- Intensity Calibration: preserved from input

**Parameters:**
- Axis group and contiguous axis range to merge
- Output axis position and naming policy
- Calibration merge policy

### Unflatten

Splits one axis into multiple axes according to a requested shape and calibration policy.

Unflatten is the structural inverse of flatten when target shape and ordering are compatible.

**Compatibility:**
- Input Dimensionality: n/a — operates on descriptor rank, not a selected target rank
- Output Dimensionality: input rank minus one, plus the number of split axes
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only
- Coordinate Calibration: Calibration-agnostic; split axes receive calibration per the supplied policy, or from records preserved by a prior `Flatten`
- Intensity Calibration: preserved from input

**Parameters:**
- Axis to split
- Output shape for split axes
- Output axis labels and calibration policy

## Higher-Order Operations

Map-reduce and other operations that combine or orchestrate results across iterations or multiple elements.

Scope: execution/composition semantics across iteration space; not axis-group-specific structural organization.

Compatibility for orchestration-level operations is largely inherited from the mapped operation rather than defined locally; fields that are inherited are recorded as such.

### Generic Reduction

Defines map-reduce composition as a first-class operation: map a target operation over iteration points, then reduce mapped outputs with an aggregation function.

**Compatibility:**
- Input Dimensionality: n/a — orchestration over iteration space; the mapped operation defines the target rank
- Output Dimensionality: inherited from the mapped operation, less the reduced iterator axes
- Input Value Type: inherited from the mapped operation; the reduction aggregator must additionally accept the mapped operation's output value type (`min`, `max`, and `median` aggregators require `Ordered`)
- Input Cardinality: inherited from the mapped operation
- Output Value Type: determined by the aggregator applied to the mapped operation's output value type
- Output Container Model: inherited from the mapped operation; aggregation over Structured Table outputs is not defined
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying (the iterator domain is reduced and values are aggregates)
- Coordinate Calibration: inherited from the mapped operation; reduced iterator axes are removed from the output descriptor
- Intensity Calibration: inherited from the mapped operation and then combined by the aggregator; `sum` accumulates that unit, the remaining aggregators preserve it

**Parameters:**
- Map operation (any compatible target axis-group operation)
- Iterator domain (sequence axis, collection axis, or both)
- Optional iterator selector/filter
- Reduction aggregator (`sum`, `mean`, `min`, `max`, `median`, custom)
- Optional reduction axes/order

**Output:**
- Reduced annotated array after aggregation over iterator domain

**Notes:**
- This is an orchestration-level operation, distinct from single-array reduction operations in `Analysis and Feature Extraction`.
- `Summation` is a common specialization of generic reduction.

### Summation

Aggregates data along specified axes:

- **Sum Specific Axis**: Reduces dimensionality by summing along one or more axes.
- **Sum with Index**: Sums values at specific indices along one axis.
- **Sum with Range**: Sums values within a range along one axis.

**Compatibility:**
- Input Dimensionality: n/a — orchestration over iteration space
- Output Dimensionality: input rank minus the number of summed axes
- Input Value Type: Linear
- Input Cardinality: Unary
- Output Value Type: preserved from input; storage widens as needed to hold the accumulated sum
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying (summed axes are removed and values are accumulated sums)
- Coordinate Calibration: Calibration-agnostic; summed axes are removed from the output descriptor
- Intensity Calibration: accumulates the input intensity unit

**Parameters:**
- Axis or axes to sum
- Selection method (all, indices, range)

**Note:** `Sum` also appears under `Analysis and Feature Extraction` -> `Statistics`. This duplication is intentional: that entry is a target axis-group reduction on selected target data, while this one is orchestration over iteration space with index and range selection modes. Neither supersedes the other.

## Sequence and Collection Operations

Operations that work with sequence or collection organization, including temporal workflows and cross-element alignment.

Scope: axis-group-specific structural and alignment operations on sequence/collection dimensions; not map-reduce orchestration semantics.

These operations act on sequence or collection axes rather than on a selected 1D/2D signal target, and therefore record `n/a` for `Dimensionality` unless otherwise noted.

### Sequence Selection and Extraction

Sequence-local structural selection follows the selector model and uses slicing semantics.

This umbrella entry defines the common semantics for range selection, single-index selection, and trim-by-offsets. The explicit user-facing operations below (`Trim`, `Slice Sequence`, `Extract Sequence Element`) are retained as convenience forms over the same selector model.

**Compatibility:**
- Input Dimensionality: n/a — acts on a sequence axis, not a selected target rank
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: Calibration-agnostic; the sequence-axis offset advances to the new start and the scale is multiplied by `step` when a step is supplied
- Intensity Calibration: preserved from input

**Parameters:**
- Selection mode: `range` | `single_index` | `trim_offsets`
- `start`, `stop`, optional `step` (for `range`)
- `index` (for `single_index`)
- `trim_start`, `trim_end` (for `trim_offsets`)

### Filter Sequence

Selects sequence elements by predicate, mask, or index set, producing a filtered sequence while preserving element order unless explicitly re-ordered.

This operation is the explicit sequence-level predicate selection form referenced by the selector model.

**Compatibility:**
- Input Dimensionality: n/a — acts on a sequence axis, not a selected target rank
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Binary in `boolean_mask` mode (sequence data + mask array); Unary in `predicate` and `index_set` modes
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: Non-uniform supported. Under `preserve_original_indices` the retained sequence positions are generally non-uniformly spaced, requiring coordinate-array calibration on the sequence axis; `compact_indices` reindexes to a uniform axis and discards the original spacing.
- Intensity Calibration: preserved from input

**Parameters:**
- Filter mode: `predicate` | `boolean_mask` | `index_set`
- Predicate function or expression (for `predicate` mode)
- Boolean mask (for `boolean_mask` mode)
- Index set/list (for `index_set` mode)
- Optional reindexing policy (`preserve_original_indices` | `compact_indices`)

**Output:**
- Filtered sequence annotated array (or view)

### Sequence-Axis Resample / Interpolate

Resamples sequence-axis data to a new sampling grid along the sequence dimension, with optional interpolation between sequence elements.

This operation is sequence-axis specific and distinct from signal-axis `Resample`.

**Compatibility:**
- Input Dimensionality: n/a — acts on a sequence axis, not a selected target rank
- Output Dimensionality: same as input
- Input Value Type: Linear
- Input Cardinality: Unary; Binary when target sampling coordinates are supplied as an array
- Output Value Type: preserved from input; integer storage is promoted to floating point under interpolation
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying
- Coordinate Calibration: Non-uniform supported. When sequence calibration is non-uniform, coordinate-aware interpolation must be used; the output sequence axis receives the requested sampling calibration.
- Intensity Calibration: preserved from input

**Parameters:**
- Sequence-axis target sample count or target sampling coordinates
- Interpolation method (`nearest`, `linear`, `cubic`, etc.)
- Boundary handling (`clamp`, `reflect`, `wrap`, fill value)
- Optional anti-aliasing policy for downsampling

**Output:**
- Sequence-resampled annotated array with updated sequence-axis calibration

**Notes:**
- Useful for temporal alignment to uniform sampling, rate conversion, and sequence-domain interpolation.

### Registration

Registration estimates relative displacements between elements and returns vector-valued shift arrays.

**Compatibility:**
- Input Dimensionality: n/a — iterates over a sequence or collection axis; per-element comparison is 1D or 2D
- Output Dimensionality: signal axes are replaced by a single vector-valued displacement per registered element
- Input Value Type: Linear
- Input Cardinality: Unary
- Output Value Type: vector (per-element displacement, one component per aligned axis)
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Structure and value-modifying (the signal axes are replaced by displacement components, one vector per registered element)
- Coordinate Calibration: Uniform-sampled only
- Intensity Calibration: n/a — output values are displacements and carry the coordinate unit, reported in index units unless calibrated coordinates are present

Common registration modes include:

- **Reference-index registration**: compare each element to a designated reference element.
- **Pairwise registration**: compare each element to the previous element (or another neighbor policy).
- **Global registration policy**: estimate shifts against a synthetic or aggregated reference.

**Output:**
- Vector-shift array

### Shift Application

Applies precomputed shift vectors to sequence or collection data to produce aligned output.

**Compatibility:**
- Input Dimensionality: n/a — acts on a sequence or collection axis; per-element displacement is 1D or 2D
- Output Dimensionality: same as input
- Input Value Type: Linear
- Input Cardinality: Binary (target data + shift-vector array)
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Layout-only for integer shifts with wrap boundary handling; Value-modifying for integer shifts with boundary fill and for all fractional shifts
- Coordinate Calibration: Uniform-sampled only for fractional shifts; the shift-vector array must be expressed in the same coordinate convention as the target data
- Intensity Calibration: preserved from input

Common shift-application modes include:

- **Apply shifts to sequence**: align a sequence axis using the provided shift vectors.
- **Apply shifts to collection**: align collection-organized data using the provided shift vectors.
- **Apply with interpolation policy**: choose interpolation and boundary behavior when shifting.

**Output:**
- Aligned annotated array

### Trim

Removes elements from the beginning and/or end of a sequence, reducing sequence length without changing internal structure.

This is a convenience alias of sequence range slicing.

**Compatibility:**
- Input Dimensionality: n/a — acts on a sequence axis, not a selected target rank
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: Calibration-agnostic; the sequence-axis offset advances by `trim_start`
- Intensity Calibration: preserved from input

**Parameters:**
- Trim amounts (`trim_start`, `trim_end`)

### Slice Sequence

Extracts a contiguous subsequence from a sequence axis.

This is the explicit range-selection form under the selector model.

**Compatibility:**
- Input Dimensionality: n/a — acts on a sequence axis, not a selected target rank
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: Calibration-agnostic; the sequence-axis offset advances to `start` and the scale is multiplied by `step`
- Intensity Calibration: preserved from input

**Parameters:**
- Start and stop indices
- Optional step

### Extract Sequence Element

Selects a single sequence element by index.

This is the explicit single-index selection form under the selector model.

**Compatibility:**
- Input Dimensionality: n/a — acts on a sequence axis, not a selected target rank
- Output Dimensionality: same as input
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: Calibration-agnostic; the selected sequence coordinate is recorded on the reduced descriptor
- Intensity Calibration: preserved from input

**Parameters:**
- Sequence element index

### Concatenate

Combines multiple annotated arrays along a specified axis, creating a longer sequence or larger collection.

**Compatibility:**
- Input Dimensionality: n/a — acts on a named axis of the full descriptor, not a selected target rank
- Output Dimensionality: same as input
- Input Value Type: Any; all inputs must share the same semantic value type
- Input Cardinality: N-ary
- Output Value Type: preserved from inputs
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: All input arrays must have compatible calibrations on the concatenation axis (matching scale, offset, and units up to continuity). If concatenation-axis calibrations are incompatible (for example, non-matching units/scales or discontinuous offsets), the operation **fails** with a calibration-mismatch error. On all non-concatenation axes, calibrations must match exactly (same scale, offset, and units). If calibrations on non-concatenation axes differ across inputs, the operation **fails** with a calibration-mismatch error unless an explicit mismatch policy is provided. The mismatch policy options are:
- Intensity Calibration: all inputs must share an intensity unit, which is preserved; the mismatch policy governs coordinate calibration only
  - `fail` (default): raise an error if any non-concatenation axis calibrations differ.
  - `drop`: drop calibrations for any axis where inputs disagree, leaving those axes uncalibrated in the output.
  - `use_first`: use the calibration from the first input array and discard calibrations from subsequent inputs.

**Parameters:**
- Axis along which to concatenate
- Sequence of annotated arrays
- Calibration mismatch policy (`fail` | `drop` | `use_first`; default `fail`)

### Stack

Combines annotated arrays into a new higher-dimensional structure. Stacking creates a new axis group or adds a sequence axis.

**Compatibility:**
- Input Dimensionality: n/a — acts on the full descriptor, not a selected target rank
- Output Dimensionality: input rank plus one
- Input Value Type: Any; all inputs must share the same semantic value type
- Input Cardinality: N-ary
- Output Value Type: preserved from inputs
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: All input arrays must have identical calibrations (matching scale, offset, and units) on every existing axis. If any input array's calibration on a shared axis differs from the others, the operation **fails** with a calibration-mismatch error unless an explicit mismatch policy is provided. The new stacking axis receives its own calibration derived from `new_axis_calibration` (see Parameters). The mismatch policy options are:
- Intensity Calibration: all inputs must share an intensity unit, which is preserved; the mismatch policy governs coordinate calibration only
  - `fail` (default): raise an error if any shared-axis calibrations differ across inputs.
  - `drop`: drop calibrations for any shared axis where inputs disagree, leaving those axes uncalibrated in the output.
  - `use_first`: use the calibration from the first input array for any disagreeing shared axis.

**Parameters:**
- Arrays to stack
- New axis label and size (derived from number of arrays)
- Target axis group (sequence, collection, or signal)
- Calibration mismatch policy (`fail` | `drop` | `use_first`; default `fail`)
- Optional `new_axis_calibration`: calibration for the newly introduced stacking axis (scale, offset, units); defaults to unit integer indexing if not specified

### Split

Splits one annotated array along a specified axis into multiple annotated arrays.

Split is the natural counterpart to `Concatenate` and preserves per-element values while partitioning structural extent.

**Compatibility:**
- Input Dimensionality: n/a — acts on a named axis of the full descriptor, not a selected target rank
- Output Dimensionality: same as input, per emitted partition
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array (one per emitted partition)
- Output Cardinality: Variadic List Output
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: Calibration-agnostic; each output partition receives the split-axis offset corresponding to its start boundary
- Intensity Calibration: preserved from input

**Parameters:**
- Axis to split
- Split specification (equal chunks or explicit boundaries)

### Unstack

Removes one axis by producing a list of annotated arrays, one per index along that axis.

Unstack is the natural counterpart to `Stack` and is equivalent to repeated single-index selection along the chosen axis with descriptor adjustment.

**Compatibility:**
- Input Dimensionality: n/a — acts on a named axis of the full descriptor, not a selected target rank
- Output Dimensionality: input rank minus one, per emitted element
- Input Value Type: Any
- Input Cardinality: Unary
- Output Value Type: preserved from input
- Output Container Model: Annotated Array (one per index along the unstacked axis)
- Output Cardinality: Variadic List Output
- Data-Modification Behavior: Extent-changing, values preserved
- Coordinate Calibration: Calibration-agnostic; each output records the coordinate of its index on the removed axis
- Intensity Calibration: preserved from input

**Parameters:**
- Axis to unstack
- Optional index subset/order

## Data Generation Operations

These operations generate new annotated arrays without requiring array-type input data. They are useful for initialization, testing, simulation, and as reference arrays in later computations.

Because they have no array input, `Data-Modification Behavior` does not apply to any operation in this section.

### Full / Constant

Generates an array filled with a constant value. `zeros` is the special case where the fill value is `0`.

**Compatibility:**
- Input Dimensionality: n/a — no array input
- Output Dimensionality: 1D or 2D
- Input Value Type: n/a — no array input
- Input Cardinality: Nullary
- Output Value Type: the requested output value/storage type
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — no input to modify
- Coordinate Calibration: Calibration-agnostic; output calibration is taken from the optional calibration parameter, defaulting to unit integer indexing
- Intensity Calibration: taken from the optional calibration parameter; dimensionless by default

**Parameters:**
- Output shape
- Fill value
- Output value/storage type
- Optional calibration and axis labels

### Linspace

Generates linearly spaced samples between bounds along one axis (or per axis for separable construction).

**Compatibility:**
- Input Dimensionality: n/a — no array input
- Output Dimensionality: 1D or 2D
- Input Value Type: n/a — no array input
- Input Cardinality: Nullary
- Output Value Type: real scalar (floating point by default)
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — no input to modify
- Coordinate Calibration: Calibration-agnostic; the generated axis may be given a linear calibration matching the requested bounds
- Intensity Calibration: the generated values carry the unit of the requested bounds

**Parameters:**
- Output shape or sample count
- Start and stop bounds
- Endpoint policy (include or exclude endpoint)
- Optional per-axis linspace definition for 2D
- Output value/storage type
- Optional calibration and axis labels

### Ramp

Generates linearly varying values along one or more axes.

**Compatibility:**
- Input Dimensionality: n/a — no array input
- Output Dimensionality: 1D or 2D
- Input Value Type: n/a — no array input
- Input Cardinality: Nullary
- Output Value Type: real scalar (floating point by default)
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — no input to modify
- Coordinate Calibration: Calibration-agnostic; ramp bounds may be interpreted in index units or in the supplied axis calibration
- Intensity Calibration: the generated values carry the unit of the ramp bounds

**Parameters:**
- Output shape
- Ramp definition per axis (`start`, `stop`, or `start` + `step`)
- Combination mode for multi-axis ramps (e.g., additive or separable)
- Output value/storage type
- Optional calibration and axis labels

### Coordinate Grid

Generates coordinate arrays over the selected domain, equivalent to mesh/grid generators used for analytic constructions.

**Compatibility:**
- Input Dimensionality: n/a — no array input
- Output Dimensionality: 1D or 2D
- Input Value Type: n/a — no array input
- Input Cardinality: Nullary
- Output Value Type: real scalar per emitted coordinate array, or vector when coordinates are packed into a single array (one component per axis)
- Output Container Model: Annotated Array
- Output Cardinality: Unary when output representation is packed vector-valued coordinates; Fixed N-ary when output representation is separate coordinate arrays (one per axis)
- Data-Modification Behavior: n/a — no input to modify
- Coordinate Calibration: Calibration-agnostic; coordinate ranges may be expressed in index units or in the supplied axis calibration
- Intensity Calibration: the emitted coordinate values carry the coordinate unit of their corresponding axis

**Parameters:**
- Output shape
- Coordinate ranges per axis
- Grid indexing convention (`ij` or `xy`)
- Output representation (separate coordinate arrays or packed vector-valued coordinates)
- Optional calibration and axis labels

### Random

Generates random-valued arrays from a chosen distribution.

Deterministic recomputation requires an explicit seed.

**Compatibility:**
- Input Dimensionality: n/a — no array input
- Output Dimensionality: 1D or 2D
- Input Value Type: n/a — no array input
- Input Cardinality: Nullary
- Output Value Type: the requested output value/storage type; `poisson` and other count distributions produce integer output
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — no input to modify
- Coordinate Calibration: Calibration-agnostic; output calibration is taken from the optional calibration parameter
- Intensity Calibration: taken from the optional calibration parameter; dimensionless by default

**Parameters:**
- Output shape
- Distribution type (`uniform`, `normal`, `poisson`, etc.)
- Distribution parameters
- Random seed (required, for reproducible recomputation)
- Output value/storage type
- Optional calibration and axis labels

### Windowing Generators

Generates standard analysis windows as arrays for direct use or composition with other operations.

- **Gaussian Window**
- **Hann Window**
- **Hamming Window**
- **Blackman Window**
- **Blackman-Harris Window**
- **Bartlett (Triangular) Window**
- **Kaiser Window**
- **Tukey Window**

**Compatibility:**
- Input Dimensionality: n/a — no array input
- Output Dimensionality: 1D or 2D
- Input Value Type: n/a — no array input
- Input Cardinality: Nullary
- Output Value Type: real scalar, dimensionless, non-negative
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — no input to modify
- Coordinate Calibration: Calibration-agnostic; the generated window should match the shape of the data it will multiply
- Intensity Calibration: n/a — window values are dimensionless weights

**Parameters:**
- Output shape
- Window type
- Window parameters (for example, Gaussian sigma, Kaiser beta, Tukey alpha)
- Optional normalization policy
- Optional separable 2D construction policy
- Output value/storage type
- Optional calibration and axis labels

**Notes:**
- 2D windows may be generated directly or by separable outer-product construction from 1D windows.

### Sinusoidal Gratings

Generates sinusoidal patterns for simulation, calibration, and frequency-response testing.

**Compatibility:**
- Input Dimensionality: n/a — no array input
- Output Dimensionality: 1D or 2D
- Input Value Type: n/a — no array input
- Input Cardinality: Nullary
- Output Value Type: real scalar; complex when the complex output mode is selected
- Output Container Model: Annotated Array
- Output Cardinality: Unary
- Data-Modification Behavior: n/a — no input to modify
- Coordinate Calibration: Calibration-agnostic when frequency is expressed in cycles per pixel; Calibrated coordinates required when frequency is expressed in cycles per calibrated unit. Anisotropic supported, but the two frequency-unit interpretations then produce geometrically different patterns.
- Intensity Calibration: amplitude and DC offset carry the intensity unit given by the optional calibration parameter; dimensionless by default

**Parameters:**
- Output shape
- Amplitude
- Spatial frequency vector (fx, fy) in Cartesian form for 2D; scalar frequency for 1D
  - **Frequency units**: cycles per pixel (hardware) or cycles per calibrated unit (physical). Must be explicitly specified.
  - Under anisotropic calibration, these two interpretations produce geometrically different patterns.
- Phase offset
- DC offset (optional)
- Optional complex output mode (real cosine, sine, or complex exponential)
- Optional calibration and axis labels

**Notes:**
- Frequency is specified in Cartesian form (fx, fy) to avoid over-determination; orientation is implicitly encoded in the frequency vector direction.
- Useful for MTF-style tests, synthetic periodic signals, and validating Fourier-domain operations.
- When frequency is given in cycles per calibrated unit, the pixel-level pattern depends on the axis calibration scale; this is essential for anisotropic or non-uniform calibrations.

## Metadata and Extension Handling

Many operations require decisions about how to handle array metadata and extension records during transformation.

Coordinate and intensity calibration are not covered here. They are per-operation properties and are recorded in each operation's `Compatibility` block under `Coordinate Calibration` and `Intensity Calibration`.

### Metadata Propagation Rules

When an operation produces a derived annotated array, its metadata is propagated according to these principles:

- **Creation Time**: A derived result has its own creation time, not the source creation time.
- **Attributes**: Free-form attributes are typically preserved unchanged unless the operation explicitly modifies them.
- **Essential Metadata**: Array descriptor (axis groups, calibrations, value type) is recomputed to reflect the operation's output structure.
- **Extension Records**: Extension records are preserved, transformed, replaced, or removed according to explicit rules defined by the operation and the extension type. For example:
  - A **provenance extension** should be updated to record the applied operation.
  - An **acquisition context extension** may be preserved unchanged.
  - A **coordinate-transform extension** specific to the original axis ordering may need to be invalidated or recomputed.


## Future Extensions

As the annotated array model evolves, operations may be extended to support:

- **Non-uniform Coordinates**: Coordinate arrays for non-uniformly sampled data.
- **Partial Operations**: Operations conditioned on region of interest (ROI) or multi-resolution analysis.
- **Distributed Computing**: Chunked or lazy evaluation of operations.
- **GPU Acceleration**: GPU-backed implementations for performance-critical operations.
- **Custom Operations**: User-defined operations and extensions through a plugin mechanism.

## Notes

- **Axis Naming**: All operations preserve or explicitly redefine axis labels to maintain semantic clarity.
- **Calibration Consistency**: Operations ensure that calibration information remains consistent with array structure; validation on read is essential.
- **Error Handling**: Operations validate input dimensions, value types, and parameter ranges, raising informative errors for invalid inputs.
- **Performance Considerations**: Some operations have multiple implementations or parameterizable algorithms; documentation should guide selection for specific use cases.
# Computation Inputs

## Motivation

An input's data comes from a fixed list of named forms: `xdata`, `display_xdata`, `element_xdata`,
`cropped_xdata`, `cropped_display_xdata`, `filtered_xdata`. Each name stands for a whole combination.
When an operation needs a combination that is not on the list, someone has to add a name, a matching
query on the data source, and a bound item class to go with it.

Several useful combinations are missing. An operation that takes a list of images always gets whole
images, because a list element has nowhere to keep a crop graphic. An input can be cropped or masked,
but not both, because there is only one spare slot for a graphic. A script has to create a display
graphic before it can crop anything, and deleting that graphic later changes what the computation does.

Providers describe the same thing in steps. Reading an item, taking a view of it, and cropping it are
separate objects, and an object takes the others as its arguments. Cropping every element of a list uses
the same crop object that crops a single image. A crop of a normalized view works without anyone adding
it first.

Storing the steps buys two more things. The computation keeps them, so a document shows how its inputs
were produced; today provenance reconstructs that after the fact. And each step knows which objects it
reads, so it can say whether a change matters; today the code guesses from the declared form.

## Overview

Running a processing operation involves two described things and one piece of machinery between them.

- A **computation processor** describes an operation: the inputs it requires, the outputs it produces, and how it is executed.
- A **computation** describes how to produce the inputs for a processor, which axis group of each input the processor targets, and where the outputs go.
- The **iteration machinery** maps produced inputs onto the processor when there is more data than the processor is declared to handle, running it once per position and accumulating the results. It has no representation in the model.

This document is about the second one: how a computation describes the production of an input. It is also about what the other two should not describe.

The term *axis group* comes from the Nion data model specification.

## Current Implementation

### Selection Is Spread Across Layers

Four mechanisms currently answer "which part of the data does this input use," and three of them sit in the wrong layer.

**Declared data type** — on the processor input. The values in use are `xdata`, `display_xdata`, `element_xdata`, `cropped_xdata`, `cropped_display_xdata`, and `filtered_xdata`. These are combinations, not types: `cropped_display_xdata` means a crop of a display view, written as one word because there is no way to write it as two. It belongs to input production: it tells the computation how to obtain the data, when the processor should only state what it needs.

**Croppable flag** — on the processor input. Whether a source is cropped is a property of how that input was produced, not of the operation.

**Secondary specifier** — on the computation variable, which is the right layer. A variable holds a primary specifier for a data source and an optional secondary specifier holding a graphic. The slot is anonymous: the graphic means a crop only by convention, and the kind is recovered from the graphic's type, a rectangle supplying bounds and an interval a range.

**Input operation** — on the computation variable, identified by a string: `axes:datum`, `axes:collection`, `axes:sequence`, or `display`. One property, two unrelated meanings. `display` substitutes the element view of the data source and marks the input as depending on display state, so it selects which data. The `axes:` values pick the axis group the processor targets and leave the rest to be iterated, so they select how to map. Both belong on the computation, but they answer different questions and are consumed by different code, and sharing one property and one menu is why the concept is hard to explain.

Masks are in no layer at all. When a data source is bound, the display item's graphics are scanned for a `used_role` of `mask` or `fourier_mask` and any matches collected. The computation never references a mask and has no record of which ones it used.

### The Data Source Already Provides

The data source object holds a reference to a data item or display data channel with an optional graphic, and exposes a fixed set of named views of it: `data`, `xdata`, `data_metadata`, `element_xdata`, `display_xdata`, `display_rgba`, `normalized_xdata`, `adjusted_xdata`, `transformed_xdata`, `cropped_xdata`, `cropped_element_xdata`, and `filter_xdata`.

It answers a fixed set of queries instead of composing, and the declared `data_type` picks which query to ask. A combination nobody thought of — a crop of a normalized view — cannot be asked for, and every combination that is thought of has to be added by name.

### Limitations

**Selections do not compose.** One anonymous slot holds one graphic, so an input cannot be both cropped and masked. This is why masks needed a separate mechanism.

**List elements cannot carry a selection.** A list variable stores an ordered relationship of single specifiers, so inserting an item records only that specifier and discards any graphic passed with it. An operation taking a list of data inputs always receives whole data items.

**A crop must be a graphic.** A computation built through the API or a script cannot crop without first creating a display graphic, and deleting that graphic silently changes the computation's meaning.

**A selection cannot have parameters of its own.** A crop graphic carries both position and extent, so an operation wanting a uniform extent around each of several positions — a fixed-size box around every detected particle — cannot express it. Uniformity has to be enforced on every graphic individually, and drifts as soon as one is adjusted.

## Planned Implementation

### Data Providers

A computation fills each of a processor's inputs with a **provider**, written as a function applied to other providers:

    crop(project_item(image_A), bounds(rect_1))

The implementation names these `ValueProvider`, `ProjectItemProvider`, `ViewProvider`, `CropProvider`, `GraphicBoundsProvider`, and `GraphicIntervalProvider`. The notation here is shorthand for them: `bounds(rect_1)` is a `GraphicBoundsProvider`, and the qualifier is in the class name because a later phase adds bounds written as a literal, which in the notation is simply a literal.

A provider yields a typed value. Data inputs are filled by providers yielding arrays; parameters are filled by providers yielding whatever the parameter needs, such as a rect or an interval. The two are the same construct, distinguished by type rather than by role. A literal is the degenerate case, so `crop(project_item(image_A), (0, 0, 0.5, 0.5))` writes the bounds out instead of deriving them.

There are four kinds.

- **Project item.** Yields the value of an item in the project: a data item, a display data channel, a graphic. The leaf that reads from the project, as opposed to a generating provider, which makes its value.
- **View.** Applied to a provider yielding data, yields a view of it: the display, element, normalized, or transformed view. These are the views the data source already exposes.
- **Selecting.** Applied to a provider yielding data and a provider yielding the selection, narrows the first: crop, mask, slice.
- **Generating.** Yields a value with no upstream: constant arrays, coordinate grids, ranges.

The set is closed, and the boundary is architectural: **a provider is supplied by the framework; anything that needs a registered executor is a computation.** Every bound item kind that exists today is on the provider side of that line — `BoundData`, `BoundDisplayData`, `BoundCroppedData`, `BoundCroppedDisplayData`, `BoundFilteredData`, `BoundGraphic`, `BoundList` — and none of them invokes an executor. A transform that does real work, such as reducing an image to its mean, is a computation with a stored result, and an input that needs that result refers to it like any other project item.

This keeps the computation machinery out of input production. It also means a plugin extends the operation catalog, never the provider set, and that no pipeline can be hidden inside an input.

An input therefore holds an expression tree. `crop` takes two providers, one yielding the data and one yielding the bounds, and both are arguments in the same sense; the difference between them is the type of value each yields, not their structural role. Leaves are references to project items or literals.

What bounds the tree is not its shape but its vocabulary. The functions are a closed set, so no amount of nesting smuggles in work that belongs to a computation.

Naming the parameter's source removes a guess. Today the kind of crop is recovered by inspecting the graphic's class, a rectangle meaning bounds and an interval meaning a range. Writing `bounds(rect_1)` or `interval(line_1)` says which aspect of the graphic is used, so the expression states it rather than the code inferring it.

Composition replaces the `data_type` combinations: `cropped_display_xdata` becomes `crop(display(project_item(A)), bounds(g))`. It is also what makes a selection reusable — crop is written once and applies to a stored item, a view, or a generator alike, rather than being re-implemented in every supply function that might want it.

The secondary specifier goes away, since a crop's bounds are an ordinary parameter. A mask becomes a provider the computation references, rather than one found by scanning a display item.

### Change Propagation

A provider is also what notices change. It listens to what it depends on and fires when its value would
differ, and the computation recomputes.

Two obligations come with that. A provider fires only for changes that affect it: a crop responds to its
bounds and to its data, not to the graphic's label or color. And a provider does not amplify: one change
upstream produces one notification, not one per level of nesting. An unnecessary notification costs a
recompute, so the cost of getting this wrong is real rather than cosmetic.

This replaces `ComputationProcessorDataInput.needs_update_for_event`, which today decides the same thing
on the processor by matching against `data_type` and `is_croppable` — a fifth piece of input production
behavior living in the declaration. It decomposes along the provider kinds: a stored provider responds
to data changes, a display view provider to display data changes, a crop provider to changes in its
bounds plus whatever its upstream responds to. The match statement becomes one rule per kind, composed
the same way the providers are.

### What the Processor Declares

The processor declares what each input must be — its form, its rank, its value type — and nothing about how to obtain it. `data_type` keeps only the form the operation needs, an array or a scalar. The croppable flag is removed; whether an input was cropped is not the operation's concern.

### What the Iteration Machinery Does

A provider yields one value or several. A crop provider given one set of bounds yields one array; given several positions it yields several, and the same holds for a tiling or a rolling window. The multiplicity has to be intrinsic to the selection — several crops are several arrays — rather than a way of traversing one array, which is the machinery's business.

The computation records, for each input, which axis group the processor targets. The machinery runs the processor once per position of the remaining axes and accumulates the results. A provider never slices an array to iterate it; it yields the array, and the machinery slices.

The target is recorded rather than inferred, because inferring it is often ambiguous and always fragile. An FFT declaring a dimensionality of one or two, given a sequence of images, can target the datum group for a two-dimensional transform per frame or the sequence axis for a one-dimensional transform per pixel. Both are valid. Recording the choice also keeps a stored document's behavior fixed, which inference would tie to whatever rule the software applied at the time. The default when a computation is created is the datum axis group.

This splits the input operation in two. `display` becomes a view provider, produced like any other input, and composes with the rest of the expression: a crop of the displayed view needs no new name. The target axis group stays on the computation but is no longer an input operation, and no longer shares a control with the choice of view.

Providers cannot be evaluated independently, because every input has to agree on one iteration shape before any of them yields a value for a given position. Evaluation takes a context carrying that shape and the current position. The current implementation already computes such a plan across a computation's data sources and checks that their shapes are compatible.

### Providers and Operations

A crop can be a provider. It is also an operation in `Processing Operations`. The executor rule settles which applies: a crop is framework machinery, so it is a provider and is never materialized, while an operation with a registered executor always produces a result data item.

This is a change in cost as well as in structure. A mean used as a parameter becomes a stored result rather than something computed inside an input, which puts a data item in the library that a fused form would have avoided. The trade is deliberate: the intermediate is inspectable and reusable, and the machinery stays out of input production.

### Lists

A list input holds one provider per element, each independent of the others. An element that needs a crop holds a crop provider, so no list entry needs a secondary specifier.

## Worked Examples

    1  FFT of an image
       src:      project_item(image_A)
       target:   datum

    2  FFT of a cropped region
       src:      crop(project_item(image_A), bounds(rect_1))
       target:   datum

    3  FFT of the displayed frame of a sequence
       src:      display(project_item(seq_A))
       target:   datum                     one result, no iteration

    4  FFT of each frame of a sequence
       src:      project_item(seq_A)
       target:   datum                     one run per frame, accumulated

    5  FFT of a cropped region of each frame
       src:      crop(project_item(seq_A), bounds(rect_1))
       target:   datum

    6  Stack several data items into a sequence
       src_list: [ project_item(A), project_item(B), project_item(C) ]
       target:   none

    7  Stack several cropped data items
       src_list: [ crop(project_item(A), bounds(rect_a)),
                   crop(project_item(B), bounds(rect_b)),
                   crop(project_item(C), bounds(rect_c)) ]
       target:   none

    8  A uniform box around every particle
       src:      crop(project_item(image_A),
                      boxes(centers(project_item(particles)), size=(64, 64)))
       target:   datum                     one run per box, accumulated

    9  A generated source
       src:      crop(generate(sinewaves), bounds(rect_1))
       target:   datum

   10  A scalar parameter by reference, later
       src:      project_item(image_A)
       sigma:    project_item(mean_of_B)
       target:   datum

Examples 3 and 4 differ only in the expression, with the same target. That is the split of today's input operation made visible: one changes which data is used, the other changes how it is mapped.

Example 7 is impossible today, because a list entry records one specifier and has nowhere to put a crop.

Example 8 is the acceptance test. The crop is the ordinary crop, applying whatever bounds it is given; `boxes` yields several rects, so the crop yields several arrays and the machinery accumulates them. Multiplicity comes from the parameter rather than from a special provider. The size belongs to `boxes` rather than to each graphic, so every crop is the same size and stays that way when a position moves. `particles` is the stored result of a detection computation, referenced like any other project item.

Example 9 shows the reuse that composition buys: `crop` does not care that its upstream is generated rather than stored.

Example 10 is not built. It is listed because the shape should not be designed out: a parameter is filled by a provider like any other input, and a mean is an ordinary computation whose result is referred to.

## Consequences

**Persistence.** A provider expression persists as a nested structure of provider entities. Nesting itself is not new — `specifier` is already an entity written as a nested dict — but the nesting is now recursive and unbounded in depth rather than one level. Every computation with a secondary specifier or a combined `data_type` needs migration.

**Dependency tracking.** A provider has to report its base items all the way down, or recompute and delete propagation break. A bound list already unions the base items of its children, so the pattern exists.

**User interface.** An input is displayed by displaying its provider. The existing data source inspector, a chooser with a crop control, is already that display for the one case the current model can express.

## Open Questions

- Whether view providers are a distinct kind or a special case of selecting providers. The views are not all narrowing, which argues for keeping them distinct.
- How a provider references a graphic while remaining valid when the graphic is deleted, and whether deletion should invalidate the computation, fall back to a literal, or drop the selection.
- What happens when providers yield more values than the processor can be mapped over.
- What stores a scalar, when parameters by reference are added. A data item holding a zero dimensional array is the obvious candidate, and `Processing Operations` already wraps scalar outputs that way.

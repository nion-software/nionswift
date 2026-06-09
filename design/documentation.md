# Maintaining Documentation Files

This guide covers maintaining all documentation files in the nionswift project.

## General Guidelines

### Format & Structure
- The documentation files use ReStructuredText (RST)

### One Source of Truth

- Define each behavior, default, range, shortcut, and key term in one canonical location.
- When the same detail is needed in multiple places, document it once and link to it with `:ref:`.
- Avoid duplicating normative details across sections; duplicates drift and create conflicts.

## Diátaxis Framework

We are migrating documentation toward the **Diátaxis** framework, which organizes documentation into four complementary types:

### The Four Documentation Types

1. **Tutorials** (Learning-oriented)
   - Learn by doing with guided, hands-on lessons
   - Goal: Give confidence and understanding through concrete examples
   - Audience: New users or users learning a new feature
   - Characteristics: Conversational, step-by-step, results-oriented

2. **How-to Guides** (Problem-oriented)
   - Practical instructions to accomplish specific tasks
   - Goal: Help users solve real-world problems
   - Audience: Users who know what they want to do
   - Characteristics: Direct, concrete, goal-focused

3. **Reference** (Information-oriented)
   - Comprehensive, structured technical information
   - Goal: Provide accurate facts for lookup and verification
   - Audience: Users who need to understand details
   - Characteristics: Organized, exhaustive, dry/technical tone

4. **Explanation** (Understanding-oriented)
   - Contextual background and conceptual understanding
   - Goal: Build understanding of why things work as they do
   - Audience: Users seeking deeper knowledge
   - Characteristics: Discursive, narrative, explores reasoning

### Terminology Note: "section"

The word "section" is used in three distinct ways in this guide. To avoid confusion, the term is qualified wherever the meaning is not obvious:

- **Diátaxis type** (Tutorial, How-to, Reference, Explanation) — referred to as a "documentation type."
- **RST heading level** — referred to as a "heading" or "heading level" (page title, panel, section, subsection).
- **Inspector section** — a property group inside an inspector panel; referred to as an "inspector section."

### Migration Path

**For New Documentation:**
- Always consider which Diátaxis type(s) your documentation fits into
- Ensure content is organized according to its type's characteristics
- Structure and group content by type, but do not print a literal type label in the RST (see Maintenance Information Belongs in documentation.md)

**For Existing Documentation:**
- Phase 1 (Immediate): New content follows Diátaxis principles
- Phase 2 (Medium-term): Update high-priority sections during refinement passes
- Phase 3 (Long-term): Gradually reorganize remaining content as opportunities arise
- No requirement to immediately restructure all existing documentation

**Identifying Documentation Type:**
When writing or updating documentation, ask:
- Is this teaching someone to start? → Tutorial
- Is this solving a specific problem? → How-to Guide
- Is this reference material for lookup? → Reference
- Is this explaining concepts or rationale? → Explanation

## Formatting Conventions

Use formatting from the RST specification and Sphinx documentation: https://www.sphinx-doc.org/en/master/usage/restructuredtext/basics.html

### UI Element References
Use RST roles for consistency:
- Menu paths: `:menuselection:`Window --> Panel Name``
- UI labels: `:guilabel:`Button Name``
- Keyboard keys: `:kbd:`Enter``
- References to other sections: `:ref:`section-label``

### Literal / Code Formatting
- Use RST inline literals (double backticks) for exact values, file names, code identifiers, formulas, and text the user types.
- Use UI roles for named interface elements; do not use inline literals as a substitute for `:guilabel:`, `:menuselection:`, or `:kbd:`.
- Use code blocks only for multi-line code, commands, or structured examples.

### Descriptive Link Text
- Use link text that describes the destination or action.
- Avoid vague link text such as "here" or "this".
- Prefer text that stays meaningful out of context.

### Keyboard Shortcut Platform Wording
- When a shortcut differs by platform, document both forms in one sentence.
- Preferred pattern: `:kbd:`Ctrl+Key`` (or `:kbd:`Command+Key`` on macOS).
- Define the platform variant once in the section, then use the shorter form when repeating the same shortcut nearby.

### Lists
- Use **numbered** lists for ordered steps that must be performed in sequence.
- Use **bulleted** lists for unordered sets of options, properties, or parallel items.

### Admonitions
- Use `.. note::` for incidental information that helps but is not required to complete a task.
- Use `.. tip::` for optional shortcuts or best practices.
- Use `.. warning::` for actions that can cause data loss or irreversible change.
- Prefer a plain paragraph when the information is part of the normal flow; reserve admonitions for content that genuinely needs to stand out.

### Images and Figures
- Store images in the `graphics/` folder and reference them with relative paths.
- Always provide `:alt:` text that describes the image for accessibility and for readers who cannot see it.
- Set a `:width:` to keep rendered images at a consistent, readable size.
- Add a caption when the image needs a name, explanation, or reference in the surrounding text.
- Use descriptive, lowercase, hyphenated file names that identify the panel or feature shown.

### Tables
- Use tables for structured comparisons, repeated properties, or key/value data that is easier to scan in rows and columns.
- Keep table text short and consistent.
- Use bullets instead of a table when the information is not naturally tabular.

### Numbers, Units, and Ranges
- Include units when a value depends on measurement context.
- Use consistent unit spelling and abbreviations within a section.
- State defaults and valid ranges when they affect user choices or reproducibility.
- Use clear range wording, such as `0 to 1`, `-1.0 to 1.0`, or `1/10 to 10`.
- Use the same numeric precision as the product UI unless a different precision is needed for clarity.

### Heading Case
- Use title case for headings.
- Keep heading wording short and descriptive.

### Heading Dividers
- Each underline must be exactly the same length as the heading text.

### Cross-Reference Validation
- Verify that `:ref:` links resolve before merging changes.
- Update broken or renamed references whenever a heading or label changes.

### Glossary / Preferred Terms
- Use the same preferred term consistently for recurring UI concepts.
- If a term has an approved name, use that name rather than a synonym.
- Keep a short glossary or preferred-terms list when terms are easy to confuse or frequently repeated.

Preferred terms:

- **Data item**: A unit of data shown, selected, or edited in the application.
- **Display panel**: A workspace panel that shows one or more data items.
- **Inspector**: The panel that shows settings and properties for the selected item.
- **Inspector section**: A collapsible subsection within the Inspector.
- **Graphic**: A UI object drawn on data to define a region, measurement, or processing area.
- **Mask**: The region defined by a graphic, when referring to the effect rather than the graphic itself.
- **Tool Bar**: The bar that provides tools, zoom controls, and workspace controls.
- **Collection**: A named group used to organize data items.
- **Data Group**: A user-created collection in the Collections panel.
- **Session**: Use the panel or inspector context explicitly when referring to session information.
- **Line profile**: A graphic used to sample along a line.
- **Band-Pass Graphic**: A Fourier graphic that selects an annular frequency range.
- **Angular Graphic**: A Fourier graphic defined by start and end angles.
- **Lattice Graphic**: A Fourier graphic used to define a lattice-like selection.

## Writing Voice and Style

### Reader Definition
- Likely readers include scientists and engineers with general software proficiency
- Likely readers also include advanced users who need parameter-level precision for reproducibility
- Likely readers also include new lab members onboarding quickly and scanning for task-oriented steps
- Assumed baseline: comfortable with scientific concepts, data workflows, and standard UI interactions
- Do not assume deep programming knowledge or familiarity with internal architecture
- Non-goal: user-facing RST files are not API or internal developer documentation unless explicitly labeled elsewhere
- Reading mode: reference pages should optimize for lookup first and linear reading second
- Prefer precise product terms and short explanations of domain-specific behavior only when it directly affects user actions
- Prefer plain language, avoid idioms, and keep sentence complexity moderate for broader readability
- Prioritize practical outcomes (what to do, what changes, and why) over implementation details

### Paragraphs
Each paragraph should cover a single topic or idea. If a paragraph addresses two distinct points, split it into two paragraphs. Short single-sentence paragraphs are acceptable and often preferable to combining unrelated points.

### Grammar and Mechanics
- **Tense**: Use present tense (for example, "the panel shows", not "the panel will show").
- **Voice and person**: Default to active voice and the second person ("you"). Use the imperative for steps ("Click Apply").
- **Spelling**: Use U.S. English spelling throughout (for example, "color", "behavior", "judgment").

### Inclusive Language
- Use neutral, inclusive wording that does not assume gender, culture, or ability.
- Prefer concrete role-based terms over stereotypes or culture-specific references.
- Avoid phrases that could exclude readers unless they are required by the product or source material.

### UI-State Wording
- Describe UI conditions explicitly with "when" statements.
- Preferred pattern: "When [state], [result]." (for example, "When no display panel is selected, the Histogram panel is empty.")
- Avoid vague or predictive phrasing such as "if applicable" or "will show" when a concrete current-state statement is possible.

### Source Line Wrapping
- Use semantic line breaks: start a new source line at the end of each sentence (or major clause).
- Do not hard-wrap paragraphs at a fixed column width.
- This keeps diffs focused on the sentence that changed and supports the paragraph-splitting conventions above.

### Tone
- Write for end users in a clear, direct, professional tone
- Slightly instructional, not conversational — not harsh or terse, but not wordy either
- Scope: these tone rules govern Reference and How-to content (the current RST files). Tutorials may use a more conversational, guided voice as described in their Diátaxis characteristics.

### Instruction Style (Direct, Neutral, and Clear)
- Write primary instructions in a direct form, but prefer neutral patterns over abrupt command chains
- Recommended default: goal-first phrasing, *"To do X, do Y"* (for example, *"To move the line, drag anywhere along it."*)
- Also acceptable when clearer: *"Use X to do Y"* and *"When X, do Y"*
- Reserve "You can..." for general description of capabilities, or for genuinely optional or alternative actions (for example, *"You can also edit the value in the Inspector panel."*)
- Do not use "You can..." for primary instructions
- Avoid terse command-only sequences when they read as harsh (for example, *"Click this. Drag that. Press Enter."*)
- In most cases, do not place multiple goal-first instructions in one paragraph; split them so each goal/action pair stands on its own
- Limited exception: closely coupled micro-steps that users perform as one immediate action sequence

Examples:
- *"To move the line, drag anywhere along it."*
- *"To constrain the angle, hold Shift while dragging."*
- *"To select a graphic behind another, click its control points directly."*


### Avoid Judgment Language
- Do not require the user to make a subjective assessment before acting
- **Wrong:** *"If a graphic is difficult to select, click its control points."*
- **Right:** *"To select a graphic behind another, click its control points directly."*
- The technique should always be stated unconditionally

### Precision
- Describe what something *does*, not just what it *is*
- For graphics and UI elements, distinguish functional roles (processing, region selection) from annotation roles
- Use the specific product term for UI controls — do not paraphrase menu items or button names
- Avoid vague verbs like "highlight" when more precise alternatives exist ("mark", "define", "select", "annotate")

### Source Verification
- Describe behavior only when it is confirmed by the source code, product behavior, or another authoritative reference.
- If behavior is uncertain or experimental, say so explicitly instead of guessing.
- Do not invent or infer functionality that is not verified.

### Domain-Specific Details
- Avoid domain-specific jargon and references (e.g., electron microscopy terminology) unless essential for understanding the feature
- When functionality is highly specialized and specific to a domain (e.g., Fourier filtering graphics for diffractograms), a single clarifying sentence is warranted
- Use such references sparingly and only where they directly explain what a feature does or what data it applies to

## Tips

- Keep descriptions concise but complete
- Include value ranges and defaults where applicable
- Organize subsections under panels logically (Info, Display, Data, etc.)

## File-Specific Validation

### user_interface.rst

#### Scope

This file documents all user interface panels and features in the application, including:

- Panel descriptions and locations (via menu selections)
- Inspector sections and their properties
- UI controls (buttons, checkboxes, fields)
- Keyboard shortcuts and interactions
- Visual editing features (color pickers, sliders, etc.)

#### Confirming Content Accuracy

When updating `user_interface.rst`, validate the content by:

1. **Compare with Panel Implementations**: Review the actual panel code to ensure documentation matches current functionality
   - Examine `Inspector.py` for inspector-related panels and properties
   - Check other panel implementations in the nionswift codebase

2. **Review Recent Changes**: Look at the commit history to identify what panels and features have been modified
   - Check the git log since the last significant `user_interface.rst` commit to identify significant changes
   - Cross-reference these changes with the documentation

3. **Identify All Available Panels**: Ensure the documentation covers all registered panels
   - Search the nionswift package source for `Workspace.WorkspaceManager().register_panel` calls
   - Document each panel found in these registrations
   - Verify that all documented panels have corresponding register_panel calls in the source


### graphics.rst

#### Confirming Content Accuracy

When updating `graphics.rst`, validate the content by:

1. **Identify All Available Graphics**: Ensure the documentation covers all registered graphics
   - Examine `Graphics.py` for graphic objects, properties, and visual editing features
   - Document each graphic found in these registrations

2. **Review Recent Changes**: Look at the commit history to identify what graphics have been modified
   - Check the git log since the last significant `graphics.rst` commit to identify significant changes
   - Cross-reference these changes with the documentation

3. **Check Terminology and Conceptual Consistency**
   - Refer to UI tools as graphics; reserve mask for regions those graphics define
   - Keep Fourier tools named as graphics (for example: Spot Graphic, Angular Graphic, Band-Pass Graphic, Lattice Graphic)

4. **Check Interaction and Navigation Accuracy**
   - Verify selection/editing behavior is documented accurately
   - Examine or watch for changes to `adjust_part` methods in `Graphic` objects in `Graphics.py` to confirm interaction details
   - Examine `adjust_part` methods for their handling if `is_shape_locked`, `is_position_locked`, and `is_rotation_locked` properties to confirm that the documentation reflects the current behavior of these features

This validation process ensures the documentation remains accurate and complete as the codebase evolves.

## Building and Previewing the Documentation

Before committing, build the docs with Sphinx and verify that pages render correctly:
- Confirm headings nest as intended (no skipped or misordered levels).
- Confirm cross-references (`:ref:`) and menu/UI roles resolve without warnings.
- Confirm images load and their `:alt:` text is present.
- Treat Sphinx build warnings as errors to fix before merging.

## Maintenance Information Belongs in documentation.md

**Do not include in the RST files themselves:**
- Validation metadata (dates, versions, status)
- Maintenance checklists
- Known gaps or TODO items for maintainers
- Documentation type labels (e.g., "This is Reference documentation")

**Allowed in source:**
- Non-rendered RST comments (for example, lines starting with `..`) are acceptable for brief maintainer notes when they are not user-visible.
- Keep maintainer comments short and actionable, and remove them once no longer needed.

**Why:** Documentation files are for end users. Meta-information about maintenance and documentation type belongs in `documentation.md` or separate maintenance guides, not in rendered user-facing documentation.

**End-user focused:** Keep RST files clean with only actionable content users need to understand the UI and its features.



Contributing
============

Found a bug?
------------
Bug reports are welcome!  Please report all bugs on the GitHub [issue-tracker].

Before you submit a bug report, search the open (and closed issues to make
sure the issue hasn't come up before.

Make sure you can reproduce the bug with the latest released version (or, better,
the development version).

Your report should give detailed instructions for how to reproduce the problem.

You do not need to add labels, milestones, or assignees as these will be
assigned by the development team during bug triaging.

Have an idea for a new feature?
-------------------------------
First, search [group-discuss] and the issue tracker (both open and closed
issues) to make sure that the idea has not been discussed before.

Explain the rationale for the feature you're requesting.  Why would this
feature be useful?  Consider also any possible drawbacks, including backwards
compatibility, new library dependencies, and performance issues.

We recommend that you discuss a potential new feature on [group-discuss] before
opening an issue.

If entered into the issue tracker, limit the issue to one specific feature,
not a list of associated features.

If the feature request is a larger request involving multiple individual
features and capabilities, consider writing a 'spec' document and recording
it in the official specifications of the program.

Triaging and prioritization
---------------------------
We will periodically review new and open issues, adding labels, milestones,
and assignees to the issue. In addition we will prioritize issues according
to the following criteria:

* Prioritize urgent issues first, then important. Prioritize issues with dependencies.
* Prioritize by the value of the issue, as measured by below or by the number of
  users affected by the issue.
* Everything else equal, prioritize lengthier tasks first, but be flexible.

We will attempt to assign value to an issue based on various criteria, including:

* Addresses data loss or integrity (urgent)
* Time savings for regular users
* Overall ease of use for regular users
* Addresses performance issue
* Streamlines repetitive tasks
* Simplifies training
* Reduces support issues
* Improves demo or initial impression
* Introduces a new capability
* Time savings for installation
* Customer request
* Bug bounty

Patches and pull requests
-------------------------
Bugs in the issue tracker will have one or more labels used to indicate the
nature, priority, and status of the bug.

Patches and pull requests are welcome.  Before you put time into a nontrivial
patch, it is a good idea to discuss it on [group-discuss], especially if it is
for a new feature (rather than fixing a bug).

Please follow these guidelines:

1.  Each commit should make a single logical change (fix a bug, add
    a feature, clean up some code, add documentation).  Everything
    related to that change should be included (including tests and
    documentation), and nothing unrelated should be included.

2.  The first line of the commit message should be a short description
    of the commit (ideally <= 80 characters) followed by a blank line,
    followed by a more detailed description of the change.

3.  Follow the stylistic conventions you find in the existing code.  Use
    spaces, not tabs.

4.  Run the tests to make sure your code does not introduce new bugs.
    (See below under [Tests](#tests).)  All tests should pass.

5.  Add test cases for the bug you are fixing.  (See below under
    [Tests](#tests).)

6.  If you are adding a new feature, update the user's guide.

7.  All code must be released under the general license governing this
    project.

8.  Dependencies on new Python libraries should be avoided.

9.  Maintain compatibility with the officially supported Python versions.

Code
----
TODO: Describe how to find code and build the project.

Tests
-----
TODO: Describe how to run tests.
As much as possible, tests should test run high level functionality which
exercises low level functionality. This makes them most general.

[group-discuss]: https://groups.google.com/group/nionswift
[issue-tracker]: https://github.com/nion-software/nionswift/issues
[web-page]: http://nion.com/swift/

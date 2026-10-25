# Nion Swift Script Output

The Python console and the Run Script dialog each show what the code they run writes to standard output and standard error. Both can run at the same time, on different threads, and the two streams are shared by the whole process. So each piece of output goes to the window of the code which wrote it, and output which belongs to neither goes to the Output panel. The mechanism is in `nion/swift/model/Utility.py`.

## Where output goes

| Written by | Goes to |
|---|---|
| A console command | The command's result |
| A Run Script dialog's script | The dialog |
| An asyncio task started by a console command or a script, or a thread it starts with `contextvars.copy_context()` | Where the command's or the script's output goes, while that destination lasts |
| A thread started any other way | The Output panel |
| An API call made by a dialog's script | The dialog |
| A dialog script's `print`, from any thread | The dialog, until the run ends |
| Anything else, or anything after its destination ends | The Output panel |

If a destination goes away while something is still writing to it, such as a thread still running after its dialog has closed, the output goes to the Output panel instead.

## The Run Script dialog

A script's output goes to its dialog until the dialog runs the script again or is closed, since the dialog still shows that script's result. So a thread the script started keeps writing to the dialog after the script finishes, and a thread left over from an earlier run does not write into the next run's output.

## Running a script through the API

Given a `stdout`, the API's `run_script` sends everything written to standard output and standard error while the script runs, from any thread, to that stream. Without one, the output goes wherever the caller's output goes, such as a console command's result or the dialog of the script which called it.

## Decisions

Each destination is tied to the code's `contextvars` context. A script often does its work on threads it starts, and a context can be passed to a new thread, so those threads can write to the script's dialog.

A thread started without `contextvars.copy_context()` writes to the Output panel, because a new thread does not automatically know which thread started it or inherit that thread's context.

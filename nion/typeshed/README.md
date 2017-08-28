Introduction
============
This is a stub library that can imported to provide type checking, code completion, and
help for the Nion API, Interactive, and UI.

All Nion software requires Python 3.5 or later.

Suggested usage for the Nion API:

```
from nion.typeshed.API_1_0 import API

api = api_broker.get_api(version=API.version, ui_version="1")  # type: API
```

Suggested usage for the Nion Hardware Source API:

```
from nion.typeshed.HardwareSource_1_0 import HardwareSource

hardware_source = api.get_hardware_source_by_id(hardware_source_id, HardwareSource.version)  # type: HardwareSource
```

Suggested usage for the Nion Interactive API:

```
from nion.typeshed.Interactive_1_0 import Interactive

interactive = api_broker.get_interactive(version=Interactive.version)  # type: Interactive
```

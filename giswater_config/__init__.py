"""
Copyright © 2025 by BGEO. All rights reserved.
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""

import os

from plugins.giswater_config.controllers import GiswaterConfigController


name = "Giswater Config"


def load_plugin(app, handler):
    # check required config
    config = handler().config()
    output_config_path = config.get('output_config_path')
    if output_config_path is None or not os.path.isdir(output_config_path):
        app.logger.error(
            "Giswater Config plugin: "
            "Required config option 'output_config_path' is not set or invalid"
        )

    # create controller (including routes)
    GiswaterConfigController(app, handler)
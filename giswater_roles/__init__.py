"""
Copyright © 2026 by BGEO. All rights reserved.
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""

import os

from plugins.giswater_roles.controllers import GiswaterRolesController


name = "Giswater Roles"


def load_plugin(app, handler):
    config = handler().config()
    output_config_path = config.get('output_config_path')
    if output_config_path is None or not os.path.isdir(output_config_path):
        app.logger.error(
            "Giswater Roles plugin: "
            "Required config option 'output_config_path' is not set or invalid"
        )

    db_url = config.get('db_url')
    if db_url is None:
        app.logger.error(
            "Giswater Roles plugin: "
            "Required config option 'db_url' is not set"
        )

    keycloak_token_url = (config.get('giswater_keycloak_token_url') or '').strip()
    keycloak_client_id = (config.get('giswater_keycloak_client_id') or '').strip()
    keycloak_client_secret = (config.get('giswater_keycloak_client_secret') or '').strip()
    if not keycloak_token_url or not keycloak_client_id or not keycloak_client_secret:
        app.logger.warning(
            "Giswater Roles plugin: Keycloak settings are incomplete. "
            "Set giswater_keycloak_token_url, giswater_keycloak_client_id "
            "and giswater_keycloak_client_secret in adminGui config."
        )

    GiswaterRolesController(app, handler)

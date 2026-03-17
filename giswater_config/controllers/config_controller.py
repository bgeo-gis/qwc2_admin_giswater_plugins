"""
Copyright © 2025 by BGEO. All rights reserved.
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
from collections import OrderedDict
import datetime
import json
import os
from shutil import copyfile

from markupsafe import Markup
from json.decoder import JSONDecodeError

from ..i18n import i18n


class GiswaterConfigController():
    """Controller for giswater config editor"""

    def __init__(self, app, handler):
        """Constructor

        :param Flask app: Flask application
        :param TenantConfigHandler handler: Tenant config handler
        """
        app.add_url_rule(
            "/giswater_config", "giswater_config", self.index, methods=["GET"]
        )
        app.add_url_rule(
            "/giswater_config/giswaterConfig", "giswater_config_edit_giswater_config",
            self.edit_giswater_config, methods=["GET"]
        )
        app.add_url_rule(
            "/giswater_config/giswaterConfig", "giswater_config_update_giswater_config",
            self.update_giswater_config, methods=["POST"]
        )

        self.templates_dir = "plugins/giswater_config/templates"
        self.logger = app.logger
        self.handler = handler

    def index(self):
        """Show entry page."""
        from flask import render_template
        return render_template(
            "%s/index.html" % self.templates_dir,
            title=i18n.translate("title"),
            i18n=i18n
        )

    def edit_giswater_config(self):
        """Show editor for giswaterConfig.json."""
        from flask import url_for
        return self.edit_json_config(
            'giswaterConfig.json', url_for('giswater_config_update_giswater_config')
        )

    def update_giswater_config(self):
        """Update giswaterConfig.json."""
        from flask import url_for
        return self.update_json_config(
            'giswaterConfig.json', url_for('giswater_config_update_giswater_config')
        )

    def edit_json_config(self, file_name, action_url):
        """Show editor for a JSON config file.

        :param str file_name: Config file name
        :param str action_url: URL for form submit
        """
        from flask import flash, redirect, render_template, url_for
        try:
            config_data = self.load_config_file(file_name)
        except Exception as e:
            flash(
                Markup(
                    i18n.translate("could_not_read", file_name=file_name, error=str(e))
                ),
                'error'
            )
            return redirect(url_for('giswater_config'))

        title = i18n.translate("edit_file", file_name=file_name)

        return render_template(
            "%s/editor.html" % self.templates_dir, title=title,
            action=action_url, config_data=config_data, i18n=i18n
        )

    def update_json_config(self, file_name, action_url):
        """Update a JSON config file.

        :param str file_name: Config file name
        :param str action_url: URL for form submit
        """
        from flask import flash, redirect, render_template, request, url_for
        try:
            # update config file
            config_data = request.values.get('config_data')
            self.save_json_config_file(config_data, file_name)
            flash(i18n.translate("file_updated", file_name=file_name), 'success')

            return redirect(url_for('giswater_config'))
        except JSONDecodeError as e:
            flash(i18n.translate("invalid_json", error=str(e)), 'error')
        except Exception as e:
            flash(
                Markup(
                    i18n.translate("could_not_save", file_name=file_name, error=str(e))
                ),
                'error'
            )

        # return to editor and show errors
        title = i18n.translate("edit_file", file_name=file_name)

        return render_template(
            "%s/editor.html" % self.templates_dir, title=title,
            action=action_url, config_data=config_data, i18n=i18n
        )

    def output_config_path(self):
        """Get output_config_path from config or raise exception if not set."""
        current_handler = self.handler()
        output_config_path = current_handler.config().get('output_config_path')
        if output_config_path is None:
            raise RuntimeError(
                i18n.translate("required_config_not_set")
            )

        return output_config_path

    def load_config_file(self, file_name):
        """Get contents of output config file as JSON string.

        :param str file_name: Config file name
        """
        config_data = None

        # read config file
        config_file_path = ""
        try:
            config_file_path = os.path.join(
                self.output_config_path(), self.handler().tenant, file_name
            )
            self.logger.info("Reading config file %s" % config_file_path)
            with open(config_file_path, encoding='utf-8') as f:
                config_data = f.read()
        except Exception as e:
            self.logger.error(
                "Could not read config file %s:\n%s" % (config_file_path, e)
            )
            raise e

        return config_data

    def save_json_config_file(self, config_data, file_name):
        """Save contents to output config file.

        :param str config_data: Config contents as JSON string
        :param str file_name: Config file name
        """
        config_file_path = ""
        try:
            # validate JSON
            config = json.loads(config_data, object_pairs_hook=OrderedDict)

            # get target path
            config_path = os.path.join(
                self.output_config_path(), self.handler().tenant
            )
            config_file_path = os.path.join(config_path, file_name)

            # save backup of current config file
            # as '<file_name>-YYYYmmdd-HHMMSS.bak'
            timestamp = datetime.datetime.now(datetime.UTC).strftime("%Y%m%d-%H%M%S")
            backup_file_name = "%s-%s.bak" % (file_name, timestamp)
            backup_file_path = os.path.join(config_path, backup_file_name)
            self.logger.info(
                "Saving backup of config file to %s" % backup_file_path
            )
            copyfile(config_file_path, backup_file_path)

            # update config file
            self.logger.info("Updating config file %s" % config_file_path)
            with open(config_file_path, 'wb') as f:
                # NOTE: do not reformat JSON string
                f.write(config_data.encode('utf8'))
        except JSONDecodeError as e:
            raise e
        except Exception as e:
            self.logger.error(
                "Could not save config file %s:\n%s" % (config_file_path, e)
            )
            raise e
"""
Copyright © 2024 by BGEO. All rights reserved.
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""

import os
import re
import datetime

from flask import Flask, render_template, request, redirect, url_for, session
from utils import i18n


app = Flask(__name__)


class GwLogController:
    def __init__(self, app, handler):
        """Constructor

        :param Flask app: Flask application
        :param TenantConfigHandler handler: Tenant config handler
        """
        app.add_url_rule(
            "/giswater_logs", "giswater_logs", self.index, methods=["GET", "POST"]
        )

        self.templates_dir = "plugins/giswater_logs/templates"
        self.logger = app.logger
        self.handler = handler
        self.config = handler().config()
        self.lines_per_page = 20
        self.lines = []  # Initialize empty list of lines
        self.date_selected = datetime.datetime.today().strftime('%Y%m%d')
        # print("CONSTRUCTOR HANDLER: ", self.handler.tenant)

    def refresh(self, date=None):
        # print("----TENANT: ", self.handler.tenant)
        # print("LOG PATH: ",self.config.get('gw_log_path'))
        """Read all lines of the log file into self.lines.

        :param str date: Date in format YYYY-MM-DD to read the corresponding log file. If None, today's date is used.
        """
        if date is None:
            date = datetime.datetime.today().strftime('%Y%m%d')
        else:
            date = datetime.datetime.strptime(date, '%Y-%m-%d').strftime('%Y%m%d')

        log_path = self.handler().config().get('gw_log_path')
        log_file_prefix = self.handler().config().get('gw_log_file_prefix')
        
        log_path = os.path.join(log_path, date, f"{log_file_prefix}_{date}.log")
        if not os.path.isfile(log_path):
            self.lines = []
            return
        else:
            with open(log_path) as file:
                self.lines = file.readlines()
                self.lines.reverse()


    def index(self):
        """Show entry page."""
        log_contents = []
        date = request.args.get('date')

        if request.args.get('page', 1) == 1:
            self.refresh()

        if request.method == 'POST' and 'refresh' in request.form:
            self.refresh()
            self.date_selected = date = datetime.datetime.today().strftime('%Y-%m-%d')
            # return redirect(url_for('giswater_logs'))

        if request.method == 'GET' and 'date' in request.args:
            date = request.args.get('date')
            self.date_selected = request.args.get('date')
            print("DATA: ",self.date_selected)
            self.refresh(date)
            # return redirect(url_for('giswater_logs'))

        #selected_date = session.get('selected_date', '')
        # Calculate page numbers for pagination
        num_lines = len(self.lines)
        print("LINES----------", num_lines)
        num_pages = num_lines // self.lines_per_page + (num_lines % self.lines_per_page > 0)
        print("PAGES----------", num_pages)
        current_page = int(request.args.get('page', 1))

        # Jump to the appropriate line in the file for the current page
        start_line = (current_page - 1) * self.lines_per_page

        # Process the lines in reverse order
        for line in self.lines[start_line:start_line+self.lines_per_page]:
            line = line.strip()
            if not line:
                break

            # Parse each line of the log file and store it in a list of dictionaries
            log = {}
            match = re.search(r'\[(.*?)\] (\w+):([^:]+):([^:]+):([^:]+):([^|||]+)\|\|\|(.+)', line)
            if match:
                log['timestamp'] = match.group(1)
                log['level'] = match.group(2)
                log['tenant'] = match.group(3)
                log['user'] = match.group(4)
                log['service'] = match.group(5)
                log['execution_msg'] = match.group(6)[:80]
                log['execution_msg_full'] = match.group(6).replace("'", "&#39;")
                log['response_msg'] = match.group(7)[:80].replace("'", "&#39;")
                log['response_msg_full'] = match.group(7).replace("'", "&#39;")
                log_contents.append(log)

        return render_template("%s/log.html" % self.templates_dir, title="GW Services Logs", log_contents=log_contents,
                            num_pages=num_pages, current_page=current_page, date_selected=self.date_selected, i18n=i18n)
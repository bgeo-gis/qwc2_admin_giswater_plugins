"""
Copyright © 2024 by BGEO. All rights reserved.
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""

import os
import re
import datetime

from flask import Flask, render_template, request, redirect, url_for
from plugins.giswater_logs.i18n import i18n


app = Flask(__name__)
LOG_LINE_RE = re.compile(
    r'\[(.*?)\] (\w+):([^:]+):([^:]+):([^:]+):([^|||]+)\|\|\|(.+)'
)


class GwLogController:
    ALLOWED_PER_PAGE = (20, 50, 100)
    DEFAULT_PER_PAGE = 20
    LOG_LEVELS = ('INFO', 'WARNING', 'ERROR')

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
        self.lines = []
        self.date_selected = datetime.datetime.today().strftime('%Y-%m-%d')

    def refresh(self, date=None):
        """Read all lines of the log file into self.lines.

        :param str date: Date in format YYYY-MM-DD to read the corresponding log file.
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

        with open(log_path) as file:
            self.lines = file.readlines()
            self.lines.reverse()

    def index(self):
        """Show entry page."""
        if request.method == 'POST' and 'refresh' in request.form:
            return redirect(url_for('giswater_logs'))

        self.date_selected = request.args.get('date') or self.date_selected
        all_logs = self._load_logs(self.date_selected)

        user_filter = (request.args.get('user') or '').strip()
        service_filter = (request.args.get('service') or '').strip()
        hour_filter = (request.args.get('hour') or '').strip()
        level_filter = (request.args.get('level') or '').strip()
        per_page = self._parse_per_page(request.args.get('per_page'))

        available_users, available_services, available_hours, available_levels = (
            self._build_filter_options(all_logs)
        )

        if user_filter and user_filter not in available_users:
            user_filter = ''
        if service_filter and service_filter not in available_services:
            service_filter = ''
        if hour_filter and hour_filter not in available_hours:
            hour_filter = ''
        if level_filter and level_filter not in available_levels:
            level_filter = ''

        base_filtered = self._apply_filters(
            all_logs, user_filter, service_filter, hour_filter, ''
        )
        level_counts = self._build_level_counts(base_filtered)

        filtered_logs = self._apply_filters(
            all_logs, user_filter, service_filter, hour_filter, level_filter
        )

        current_page = int(request.args.get('page', 1))
        pagination = self._build_pagination(
            len(filtered_logs), current_page, per_page
        )
        start_index = (pagination['page'] - 1) * per_page
        log_contents = filtered_logs[start_index:start_index + per_page]

        filter_params = self._build_filter_params(
            self.date_selected,
            user_filter,
            service_filter,
            hour_filter,
            level_filter,
            per_page,
        )

        return render_template(
            "%s/log.html" % self.templates_dir,
            title="Giswater service logs",
            log_contents=log_contents,
            pagination=pagination,
            filter_params=filter_params,
            page_url=self._page_url,
            date_selected=self.date_selected,
            available_users=available_users,
            available_services=available_services,
            available_hours=available_hours,
            available_levels=available_levels,
            user_filter=user_filter,
            service_filter=service_filter,
            hour_filter=hour_filter,
            level_filter=level_filter,
            per_page=per_page,
            level_counts=level_counts,
            total_filtered=len(filtered_logs),
            i18n=i18n,
        )

    def _load_logs(self, date):
        self.refresh(date)
        logs = []
        for line in self.lines:
            log = self._parse_line(line)
            if log:
                logs.append(log)
        return logs

    def _parse_line(self, line):
        line = line.strip()
        if not line:
            return None

        match = LOG_LINE_RE.search(line)
        if not match:
            return None

        timestamp = match.group(1)
        return {
            'timestamp': timestamp,
            'level': match.group(2),
            'tenant': match.group(3),
            'user': match.group(4),
            'service': match.group(5),
            'hour': self._extract_hour(timestamp),
            'execution_msg': match.group(6)[:80],
            'execution_msg_full': match.group(6),
            'response_msg': match.group(7)[:80],
            'response_msg_full': match.group(7),
        }

    def _extract_hour(self, timestamp):
        parts = timestamp.split()
        if len(parts) < 2:
            return ''
        return parts[1].split(':')[0]

    def _parse_per_page(self, value):
        try:
            per_page = int(value)
        except (TypeError, ValueError):
            per_page = self.DEFAULT_PER_PAGE
        if per_page not in self.ALLOWED_PER_PAGE:
            return self.DEFAULT_PER_PAGE
        return per_page

    def _build_filter_options(self, logs):
        users = sorted({log['user'] for log in logs if log.get('user')})
        services = sorted({log['service'] for log in logs if log.get('service')})
        hours = sorted(
            {log['hour'] for log in logs if log.get('hour')},
            key=lambda hour: int(hour)
        )
        levels = [level for level in self.LOG_LEVELS if any(
            log.get('level') == level for log in logs
        )]
        return users, services, hours, levels

    def _build_level_counts(self, logs):
        counts = {level: 0 for level in self.LOG_LEVELS}
        for log in logs:
            level = log.get('level')
            if level in counts:
                counts[level] += 1
        return counts

    def _apply_filters(self, logs, user='', service='', hour='', level=''):
        filtered = logs
        if user:
            filtered = [log for log in filtered if log['user'] == user]
        if service:
            filtered = [log for log in filtered if log['service'] == service]
        if hour:
            filtered = [log for log in filtered if log['hour'] == hour]
        if level:
            filtered = [log for log in filtered if log['level'] == level]
        return filtered

    def _build_filter_params(
        self, date='', user='', service='', hour='', level='',
        per_page=None, page=None
    ):
        if per_page is None:
            per_page = self.DEFAULT_PER_PAGE
        params = {}
        if date:
            params['date'] = date
        if user:
            params['user'] = user
        if service:
            params['service'] = service
        if hour:
            params['hour'] = hour
        if level:
            params['level'] = level
        if per_page != self.DEFAULT_PER_PAGE:
            params['per_page'] = per_page
        if page and page > 1:
            params['page'] = page
        return params

    def _page_url(self, filter_params, page_num):
        params = dict(filter_params)
        if page_num > 1:
            params['page'] = page_num
        else:
            params.pop('page', None)
        return url_for('giswater_logs', **params)

    def _build_pagination(self, total, page, per_page):
        total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
        page = max(1, min(page, total_pages))
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        return {
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'start': start_index + 1 if total else 0,
            'end': min(end_index, total),
        }

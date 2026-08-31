"""
Copyright © 2026 by BGEO. All rights reserved.
The program is free software: you can redistribute it and/or modify it under the terms of the GNU
General Public License as published by the Free Software Foundation, either version 3 of the License,
or (at your option) any later version.
"""
import json
import os
import re

from markupsafe import Markup
from sqlalchemy import text

from qwc_services_core.config_models import ConfigModels
from qwc_services_core.database import DatabaseEngine

from ..i18n import i18n
from ..services.keycloak_client import KeycloakClient, KeycloakClientError


PG_IDENTIFIER_RE = re.compile(r'^[a-zA-Z_][a-zA-Z0-9_]*$')
AUDIT_PROCESS_NAME = "QWC2 Backoffice"
USER_SOURCE_KEYCLOAK = 'keycloak'
USER_SOURCE_QWC2 = 'qwc2'
USER_SOURCE_MODES = (USER_SOURCE_KEYCLOAK, USER_SOURCE_QWC2)
USER_LOG_INSERT = text("""
    INSERT INTO audit.user_log (
        type,
        process_name,
        user_name,
        old_data,
        new_data,
        observ
    )
    VALUES (
        :type,
        :process_name,
        :user_name,
        :old_data,
        :new_data,
        :observ
    )
""")


class GiswaterRolesController():
    """Controller for managing PostgreSQL roles of Giswater users."""

    def __init__(self, app, handler):
        app.add_url_rule(
            "/giswater_roles", "giswater_roles", self.index, methods=["GET"]
        )
        app.add_url_rule(
            "/giswater_roles/partial/tables", "giswater_roles_tables_partial",
            self.tables_partial, methods=["GET"]
        )
        app.add_url_rule(
            "/giswater_roles/partial/<section>", "giswater_roles_partial",
            self.table_partial, methods=["GET"]
        )
        app.add_url_rule(
            "/giswater_roles/<int:user_id>/role", "giswater_roles_set_role",
            self.set_role, methods=["POST"]
        )
        app.add_url_rule(
            "/giswater_roles/roles_bulk", "giswater_roles_set_roles_bulk",
            self.set_roles_bulk, methods=["POST"]
        )
        app.add_url_rule(
            "/giswater_roles/apply_changes", "giswater_roles_apply_changes",
            self.apply_role_changes, methods=["POST"]
        )
        app.add_url_rule(
            "/giswater_roles/create_pg_user", "giswater_roles_create_pg_user",
            self.create_pg_user, methods=["POST"]
        )
        app.add_url_rule(
            "/giswater_roles/delete_pg_user", "giswater_roles_delete_pg_user",
            self.delete_pg_user, methods=["POST"]
        )
        app.add_url_rule(
            "/giswater_roles/delete_selected", "giswater_roles_delete_selected",
            self.delete_users, methods=["POST"]
        )

        self.templates_dir = "plugins/giswater_roles/templates"
        self.logger = app.logger
        self.handler = handler
        self.db_engine = DatabaseEngine()

    def index(self):
        """List QWC users with optional search, role filters and pagination."""
        from flask import flash, render_template, request

        context, error = self._load_index_context(request.args)
        if error:
            flash(
                Markup(i18n.translate("could_not_load_users", error=error)),
                'error'
            )

        return render_template(
            "%s/index.html" % self.templates_dir,
            title=i18n.translate("title"),
            page_url=self._page_url,
            i18n=i18n,
            **context
        )

    def table_partial(self, section):
        """Return table HTML for AJAX pagination."""
        from flask import abort, render_template, request

        if section != 'synced':
            abort(404)

        context, error = self._load_index_context(request.args)
        if error:
            abort(500)

        return render_template(
            self._table_partial_template(),
            page_url=self._page_url,
            i18n=i18n,
            **context
        )

    def tables_partial(self):
        """Return table HTML fragment for filter AJAX requests."""
        from flask import abort, jsonify, render_template, request

        context, error = self._load_index_context(request.args)
        if error:
            abort(500)

        return jsonify(
            synced_html=render_template(
                self._table_partial_template(),
                page_url=self._page_url,
                i18n=i18n,
                **context
            ),
            synced_total=context['synced_pagination']['total'],
        )

    def _table_partial_template(self):
        return "%s/_synced_table.html" % self.templates_dir

    def _load_index_context(self, args):
        search = (args.get('search') or '').strip()
        schema_role_filter = (args.get('schema_role') or '').strip()
        manager_role_filter = (args.get('manager_role') or '').strip()
        giswater_role_filter = (args.get('giswater_role') or '').strip()
        not_in_pg_filter = (args.get('not_in_pg') or '').strip() in ('1', 'true', 'on', 'yes')
        per_page = self._parse_per_page(args.get('per_page'))
        synced_page = self._parse_page(args.get('synced_page'))
        available_roles = []
        available_schema_roles = []
        available_manager_roles = []
        users = []
        synced_pagination = self._empty_pagination(per_page)
        error = None

        try:
            (
                available_roles,
                available_schema_roles,
                available_manager_roles,
                synced_all,
            ) = self._load_shared_user_data()
            if schema_role_filter and schema_role_filter not in available_schema_roles:
                schema_role_filter = ''
            if manager_role_filter and (
                manager_role_filter not in available_manager_roles
            ):
                manager_role_filter = ''
            if giswater_role_filter and giswater_role_filter not in available_roles:
                giswater_role_filter = ''

            synced_filtered = self._filter_users(
                synced_all,
                search,
                schema_role_filter,
                manager_role_filter,
                giswater_role_filter,
                not_in_pg_filter,
            )
            synced_pagination = self._paginate_list(
                synced_filtered, synced_page, per_page
            )
            users = synced_pagination['items']
        except KeycloakClientError as e:
            self.logger.error("Error loading giswater roles index: %s" % e)
            error = str(e)
        except Exception as e:
            self.logger.error("Error loading giswater roles index: %s" % e)
            error = str(e)

        filter_params = self._build_filter_params(
            search,
            schema_role_filter,
            manager_role_filter,
            giswater_role_filter,
            not_in_pg_filter,
            per_page,
            synced_page,
        )

        plugin_cfg = self._plugin_config()
        show_schema_roles = plugin_cfg['show_schema_roles']
        show_manager_roles = plugin_cfg['show_manager_roles']
        show_giswater_roles = plugin_cfg['show_giswater_roles']
        user_source_mode = plugin_cfg['mode']

        return {
            'users': users,
            'synced_pagination': synced_pagination,
            'available_roles': available_roles,
            'available_schema_roles': available_schema_roles,
            'available_manager_roles': available_manager_roles,
            'show_schema_roles': show_schema_roles,
            'show_manager_roles': show_manager_roles,
            'show_giswater_roles': show_giswater_roles,
            'has_role_tiers': (
                show_schema_roles or show_manager_roles or show_giswater_roles
            ),
            'user_source_mode': user_source_mode,
            'show_qwc_sync': user_source_mode == USER_SOURCE_KEYCLOAK,
            'require_audit_comment': plugin_cfg['require_audit_comment'],
            'description': i18n.translate(
                'description_%s' % user_source_mode
            ),
            'users_title': i18n.translate(
                'users_title_%s' % user_source_mode
            ),
            'users_help': i18n.translate(
                'users_help_%s' % user_source_mode
            ),
            'no_users_message': i18n.translate(
                'no_users_%s' % user_source_mode
            ),
            'search': search,
            'schema_role_filter': schema_role_filter,
            'manager_role_filter': manager_role_filter,
            'giswater_role_filter': giswater_role_filter,
            'not_in_pg_filter': not_in_pg_filter,
            'per_page': per_page,
            'filter_params': filter_params,
        }, error

    def _default_page_size(self):
        return 10

    def _allowed_page_sizes(self):
        return [10, 25, 50]

    def _parse_page(self, value):
        try:
            return max(1, int(value))
        except (TypeError, ValueError):
            return 1

    def _parse_per_page(self, value):
        try:
            per_page = int(value)
        except (TypeError, ValueError):
            per_page = self._default_page_size()
        if per_page not in self._allowed_page_sizes():
            return self._default_page_size()
        return per_page

    def _empty_pagination(self, per_page):
        return {
            'items': [],
            'page': 1,
            'per_page': per_page,
            'total': 0,
            'total_pages': 1,
            'has_prev': False,
            'has_next': False,
            'start': 0,
            'end': 0,
        }

    def _paginate_list(self, items, page, per_page):
        total = len(items)
        total_pages = max(1, (total + per_page - 1) // per_page) if total else 1
        page = max(1, min(page, total_pages))
        start_index = (page - 1) * per_page
        end_index = start_index + per_page
        return {
            'items': items[start_index:end_index],
            'page': page,
            'per_page': per_page,
            'total': total,
            'total_pages': total_pages,
            'has_prev': page > 1,
            'has_next': page < total_pages,
            'start': start_index + 1 if total else 0,
            'end': min(end_index, total),
        }

    def _build_filter_params(
        self, search='', schema_role='', manager_role='', giswater_role='',
        not_in_pg=False, per_page=None, synced_page=1
    ):
        if per_page is None:
            per_page = self._default_page_size()
        params = {}
        if search:
            params['search'] = search
        if schema_role:
            params['schema_role'] = schema_role
        if manager_role:
            params['manager_role'] = manager_role
        if giswater_role:
            params['giswater_role'] = giswater_role
        if not_in_pg:
            params['not_in_pg'] = '1'
        if per_page != self._default_page_size():
            params['per_page'] = per_page
        if synced_page > 1:
            params['synced_page'] = synced_page
        return params

    def _filter_params(self):
        from flask import request
        return self._build_filter_params(
            search=(request.args.get('search') or '').strip(),
            schema_role=(request.args.get('schema_role') or '').strip(),
            manager_role=(request.args.get('manager_role') or '').strip(),
            giswater_role=(request.args.get('giswater_role') or '').strip(),
            not_in_pg=(request.args.get('not_in_pg') or '').strip() in (
                '1', 'true', 'on', 'yes'
            ),
            per_page=self._parse_per_page(request.args.get('per_page')),
            synced_page=self._parse_page(request.args.get('synced_page')),
        )

    def _index_url(self, filter_params):
        from flask import url_for
        return url_for('giswater_roles', **filter_params)

    def _redirect_index(self):
        """Redirect to index without filters or pagination."""
        from flask import redirect
        return redirect(self._index_url({}))

    def _page_url(self, filter_params, page_param, page_num):
        params = dict(filter_params)
        if page_num > 1:
            params[page_param] = page_num
        else:
            params.pop(page_param, None)
        return self._index_url(params)

    def set_role(self, user_id):
        """Set the single Giswater PostgreSQL role for a synced user."""
        from flask import flash, redirect, request, url_for
        filter_params = self._filter_params()
        role = (request.form.get('role') or '').strip()

        try:
            user = self._get_synced_qwc_user(user_id)
            if user is None:
                flash(i18n.translate("user_not_synced"), 'error')
                return self._redirect_index()

            available_roles = self._get_available_roles()
            if role and role not in available_roles:
                raise ValueError(i18n.translate("invalid_role", role=role))

            self._set_user_role(
                user.name, role or None, observ=self._read_audit_comment()
            )

            if role:
                flash(
                    i18n.translate("role_updated", username=user.name, role=role),
                    'success'
                )
            else:
                flash(
                    i18n.translate("role_removed", username=user.name),
                    'success'
                )
        except Exception as e:
            self.logger.error("Error updating role for user %s: %s" % (user_id, e))
            flash(
                Markup(i18n.translate("could_not_update_roles", error=str(e))),
                'error'
            )

        return self._redirect_index()

    def set_roles_bulk(self):
        """Apply role tiers to multiple users; create PG users when needed."""
        from flask import flash, redirect, request
        filter_params = self._filter_params()
        schema_roles_value = request.form.get('schema_roles') or ''
        manager_role = (request.form.get('manager_role') or '').strip()
        giswater_role = (request.form.get('role') or '').strip()
        usernames = [
            username.strip()
            for username in request.form.getlist('usernames')
            if username.strip()
        ]

        try:
            if not usernames:
                flash(i18n.translate("select_at_least_one_user"), 'error')
                return self._redirect_index()

            visible_users = self._get_visible_apply_role_users(filter_params)
            invalid = set(usernames) - set(visible_users.keys())
            if invalid:
                raise ValueError(i18n.translate(
                    "bulk_roles_invalid_users",
                    users=", ".join(sorted(invalid))
                ))

            tier_cfg = self._plugin_config()
            available_schema = set(self._get_available_schema_roles())
            available_manager = set(self._get_available_manager_roles())
            available_giswater = set(self._get_available_roles())
            if tier_cfg['show_schema_roles']:
                for role in self._parse_role_list(schema_roles_value):
                    if role not in available_schema:
                        raise ValueError(i18n.translate("invalid_role", role=role))
            if tier_cfg['show_manager_roles'] and manager_role:
                if manager_role not in available_manager:
                    raise ValueError(i18n.translate("invalid_role", role=manager_role))
            if tier_cfg['show_giswater_roles'] and giswater_role:
                if giswater_role not in available_giswater:
                    raise ValueError(i18n.translate("invalid_role", role=giswater_role))

            audit_comment = self._read_audit_comment()

            updated = []
            created = []
            failed = []
            for username in usernames:
                try:
                    action = self._apply_or_create_user_roles(
                        username,
                        visible_users[username],
                        schema_roles_value,
                        manager_role,
                        giswater_role,
                        observ=audit_comment,
                    )
                    if action == 'created':
                        created.append(username)
                    else:
                        updated.append(username)
                except Exception as e:
                    self.logger.error(
                        "Error updating role for user %s: %s" % (username, e)
                    )
                    failed.append((username, str(e)))

            if created:
                flash(
                    i18n.translate(
                        "pending_roles_created_in_pg",
                        count=len(created),
                        users=", ".join(created)
                    ),
                    'success'
                )
            if updated:
                flash(
                    i18n.translate(
                        "bulk_roles_updated",
                        count=len(updated),
                        users=", ".join(updated)
                    ),
                    'success'
                )
            for username, error in failed:
                flash(
                    Markup(i18n.translate(
                        "could_not_update_roles", error="%s: %s" % (username, error)
                    )),
                    'error'
                )
        except Exception as e:
            self.logger.error("Error bulk updating roles: %s" % e)
            flash(
                Markup(i18n.translate("could_not_update_roles", error=str(e))),
                'error'
            )

        return self._redirect_index()

    def apply_role_changes(self):
        """Apply pending per-user role changes from the users table."""
        from flask import flash, redirect, request
        filter_params = self._filter_params()
        usernames_raw = request.form.getlist('usernames')
        roles = request.form.getlist('roles')
        schema_roles = request.form.getlist('schema_roles')
        manager_roles = request.form.getlist('manager_roles')

        try:
            if not usernames_raw:
                flash(i18n.translate("no_pending_changes"), 'error')
                return self._redirect_index()

            expected_len = len(usernames_raw)
            if (
                len(roles) != expected_len
                or len(schema_roles) != expected_len
                or len(manager_roles) != expected_len
            ):
                flash(i18n.translate("no_pending_changes"), 'error')
                return self._redirect_index()

            usernames = [username.strip() for username in usernames_raw]
            if any(not username for username in usernames):
                raise ValueError(i18n.translate("bulk_roles_invalid_users", users=''))

            visible_users = self._get_visible_apply_role_users(filter_params)
            invalid = set(usernames) - set(visible_users.keys())
            if invalid:
                raise ValueError(i18n.translate(
                    "bulk_roles_invalid_users",
                    users=", ".join(sorted(invalid))
                ))

            tier_cfg = self._plugin_config()
            available_giswater = set(self._get_available_roles())
            available_schema = set(self._get_available_schema_roles())
            available_manager = set(self._get_available_manager_roles())
            if tier_cfg['show_giswater_roles']:
                for role in roles:
                    if role and role not in available_giswater:
                        raise ValueError(i18n.translate("invalid_role", role=role))
            if tier_cfg['show_schema_roles']:
                for schema_roles_value in schema_roles:
                    for role in self._parse_role_list(schema_roles_value):
                        if role not in available_schema:
                            raise ValueError(i18n.translate("invalid_role", role=role))
            if tier_cfg['show_manager_roles']:
                for role in manager_roles:
                    if role and role not in available_manager:
                        raise ValueError(i18n.translate("invalid_role", role=role))

            audit_comment = self._read_audit_comment()

            updated = []
            created = []
            failed = []
            for username, schema_roles_value, manager_role, giswater_role in zip(
                usernames, schema_roles, manager_roles, roles
            ):
                try:
                    action = self._apply_or_create_user_roles(
                        username,
                        visible_users[username],
                        schema_roles_value,
                        manager_role,
                        giswater_role,
                        observ=audit_comment,
                    )
                    if action == 'created':
                        created.append(username)
                    else:
                        updated.append(username)
                except Exception as e:
                    self.logger.error(
                        "Error updating role for user %s: %s" % (username, e)
                    )
                    failed.append((username, str(e)))

            if created:
                flash(
                    i18n.translate(
                        "pending_roles_created_in_pg",
                        count=len(created),
                        users=", ".join(created)
                    ),
                    'success'
                )
            if updated:
                flash(
                    i18n.translate(
                        "pending_roles_updated",
                        count=len(updated),
                        users=", ".join(updated)
                    ),
                    'success'
                )
            for username, error in failed:
                flash(
                    Markup(i18n.translate(
                        "could_not_update_roles", error="%s: %s" % (username, error)
                    )),
                    'error'
                )
        except Exception as e:
            self.logger.error("Error applying pending role changes: %s" % e)
            flash(
                Markup(i18n.translate("could_not_update_roles", error=str(e))),
                'error'
            )

        return self._redirect_index()

    def create_pg_user(self):
        """Create a PostgreSQL login role for a directory user and assign roles."""
        from flask import flash, redirect, request

        username = (request.form.get('username') or '').strip()
        schema_role = (request.form.get('schema_role') or '').strip()
        manager_role = (request.form.get('manager_role') or '').strip()
        giswater_role = (request.form.get('role') or '').strip()
        schema_roles = self._parse_role_list(schema_role)

        try:
            if not username:
                raise ValueError(i18n.translate("username_required"))

            self._ensure_directory_user(username)

            if self._pg_role_exists(username):
                raise ValueError(i18n.translate(
                    "pg_user_already_exists", username=username
                ))

            tier_cfg = self._plugin_config()
            available_schema = set(self._get_available_schema_roles())
            available_manager = set(self._get_available_manager_roles())
            available_giswater = set(self._get_available_roles())
            if tier_cfg['show_schema_roles']:
                for role in schema_roles:
                    if role not in available_schema:
                        raise ValueError(i18n.translate("invalid_role", role=role))
            if tier_cfg['show_manager_roles'] and manager_role:
                if manager_role not in available_manager:
                    raise ValueError(i18n.translate("invalid_role", role=manager_role))
            if tier_cfg['show_giswater_roles'] and giswater_role:
                if giswater_role not in available_giswater:
                    raise ValueError(i18n.translate("invalid_role", role=giswater_role))

            audit_comment = self._read_audit_comment()

            roles_to_grant = []
            if tier_cfg['show_schema_roles']:
                roles_to_grant.extend(schema_roles)
            if tier_cfg['show_manager_roles'] and manager_role:
                roles_to_grant.append(manager_role)
            if tier_cfg['show_giswater_roles'] and giswater_role:
                roles_to_grant.append(giswater_role)
            self._create_pg_login_user(
                username, roles_to_grant, observ=audit_comment
            )
            if roles_to_grant:
                flash(
                    i18n.translate(
                        "pg_user_created_with_roles",
                        username=username,
                        roles=", ".join(roles_to_grant)
                    ),
                    'success'
                )
            else:
                flash(
                    i18n.translate("pg_user_created", username=username),
                    'success'
                )
        except Exception as e:
            self.logger.error("Error creating PG user %s: %s" % (username, e))
            flash(
                Markup(i18n.translate(
                    "could_not_create_pg_user",
                    username=username,
                    error=str(e)
                )),
                'error'
            )

        return self._redirect_index()

    def delete_pg_user(self):
        """Drop a PostgreSQL login role for a directory user."""
        from flask import flash, request

        username = (request.form.get('username') or '').strip()

        try:
            if not username:
                raise ValueError(i18n.translate("username_required"))

            self._ensure_directory_user(username)

            pg_username = self._find_pg_username(username)
            if pg_username is None:
                raise ValueError(i18n.translate(
                    "pg_role_not_found_plain", username=username
                ))

            self._drop_pg_login_user(
                pg_username, observ=self._read_audit_comment()
            )
            flash(
                i18n.translate("pg_user_deleted", username=pg_username),
                'success'
            )
        except Exception as e:
            self.logger.error("Error deleting PG user %s: %s" % (username, e))
            flash(
                Markup(i18n.translate(
                    "could_not_delete_pg_user",
                    username=username,
                    error=str(e)
                )),
                'error'
            )

        return self._redirect_index()

    def delete_users(self):
        """Remove selected synced users from the QWC config database."""
        from flask import flash, redirect, request
        filter_params = self._filter_params()
        user_ids = []
        for user_id in request.form.getlist('user_ids'):
            try:
                user_ids.append(int(user_id))
            except (TypeError, ValueError):
                continue

        try:
            if not user_ids:
                flash(i18n.translate("select_at_least_one_user"), 'error')
                return self._redirect_index()

            visible_users = self._get_visible_qwc_users(filter_params)
            invalid_ids = set(user_ids) - set(visible_users.keys())
            if invalid_ids:
                raise ValueError(i18n.translate(
                    "delete_users_invalid",
                    users=", ".join(str(uid) for uid in sorted(invalid_ids))
                ))

            deleted = []
            failed = []
            for user_id in user_ids:
                username = visible_users[user_id]['name']
                try:
                    self._delete_qwc_user(user_id)
                    deleted.append(username)
                except Exception as e:
                    self.logger.error(
                        "Error deleting QWC user %s: %s" % (username, e)
                    )
                    failed.append((username, str(e)))

            if deleted:
                flash(
                    i18n.translate(
                        "users_deleted",
                        count=len(deleted),
                        users=", ".join(deleted)
                    ),
                    'success'
                )
            for username, error in failed:
                flash(
                    Markup(i18n.translate(
                        "could_not_delete_user",
                        username=username,
                        error=error
                    )),
                    'error'
                )
        except Exception as e:
            self.logger.error("Error deleting QWC users: %s" % e)
            flash(
                Markup(i18n.translate("could_not_delete_users", error=str(e))),
                'error'
            )

        return self._redirect_index()

    def _get_visible_users(self, filter_params):
        return self._filter_users(
            self._load_users_with_roles(),
            filter_params.get('search', ''),
            filter_params.get('schema_role', ''),
            filter_params.get('manager_role', ''),
            filter_params.get('giswater_role', ''),
            filter_params.get('not_in_pg') == '1',
        )

    def _get_visible_role_users(self, filter_params):
        return {
            user['name']: user
            for user in self._get_visible_users(filter_params)
            if user.get('can_manage_roles')
        }

    def _get_visible_apply_role_users(self, filter_params):
        """Users whose pending role changes can be applied (update or create in PG)."""
        return {
            user['name']: user
            for user in self._get_visible_users(filter_params)
            if user.get('can_manage_roles') or user.get('can_create_in_pg')
        }

    def _apply_or_create_user_roles(
        self, username, user, schema_roles_value, manager_role, giswater_role,
        observ=None
    ):
        """Apply role changes to an existing PG user or create the login role first."""
        schema_roles = self._parse_role_list(schema_roles_value)

        if user.get('can_manage_roles'):
            pg_username = self._role_username(user)
            tier_cfg = self._plugin_config()
            if tier_cfg['show_schema_roles']:
                self._set_user_schema_roles(
                    pg_username, schema_roles, observ=observ
                )
            if tier_cfg['show_manager_roles']:
                self._set_user_tier_role(
                    pg_username, manager_role or None, 'manager', observ=observ
                )
            if tier_cfg['show_giswater_roles']:
                self._set_user_tier_role(
                    pg_username, giswater_role or None, 'giswater', observ=observ
                )
            return 'updated'

        if user.get('can_create_in_pg'):
            roles_to_grant = []
            tier_cfg = self._plugin_config()
            if tier_cfg['show_schema_roles']:
                roles_to_grant.extend(schema_roles)
            if tier_cfg['show_manager_roles'] and manager_role:
                roles_to_grant.append(manager_role)
            if tier_cfg['show_giswater_roles'] and giswater_role:
                roles_to_grant.append(giswater_role)
            self._create_pg_login_user(
                username, roles_to_grant, observ=observ
            )
            return 'created'

        raise ValueError(i18n.translate(
            "bulk_roles_invalid_users", users=username
        ))

    def _get_visible_qwc_users(self, filter_params):
        return {
            user['id']: user
            for user in self._get_visible_users(filter_params)
            if user.get('id')
        }

    def _username_key(self, username):
        return (username or '').strip().lower()

    def _build_lookup_maps(self, qwc_users, pg_login_roles, pg_roles_by_user):
        qwc_by_key = {}
        for user in qwc_users:
            qwc_by_key[self._username_key(user.name)] = user

        pg_login_by_key = {
            self._username_key(name): name for name in pg_login_roles
        }

        pg_roles_by_key = {}
        for username, roles in pg_roles_by_user.items():
            pg_roles_by_key[self._username_key(username)] = (username, roles)

        return qwc_by_key, pg_login_by_key, pg_roles_by_key

    def _resolve_user_sync(self, username, qwc_by_key, pg_login_by_key, pg_roles_by_key):
        key = self._username_key(username)
        qwc_user = qwc_by_key.get(key)
        pg_username = pg_login_by_key.get(key)
        has_pg = pg_username is not None
        has_qwc = qwc_user is not None
        assigned_roles = []
        schema_roles = []
        current_manager_role = ''
        current_giswater_role = ''
        if has_pg:
            _, assigned_roles = pg_roles_by_key.get(key, (pg_username, []))
            schema_roles, manager_roles, giswater_roles = (
                self._split_roles_by_tier(assigned_roles)
            )
            current_manager_role = (
                manager_roles[0] if manager_roles else ''
            )
            current_giswater_role = giswater_roles[0] if giswater_roles else ''
        return {
            'id': qwc_user.id if qwc_user is not None else None,
            'name': username,
            'pg_username': pg_username or '',
            'has_qwc': has_qwc,
            'has_pg': has_pg,
            'can_manage_roles': has_pg,
            'can_create_in_pg': (
                not has_pg and bool(PG_IDENTIFIER_RE.match(username))
            ),
            'can_delete_from_pg': has_pg,
            'assigned_roles': assigned_roles,
            'current_schema_roles': schema_roles,
            'current_manager_role': current_manager_role,
            'current_role': current_giswater_role,
        }

    def _role_username(self, user):
        return user.get('pg_username') or user['name']

    def _plugin_config(self):
        """Get plugin-specific config options."""
        config = self.handler().config()
        schema_roles, show_schema_roles = self._tier_roles_from_config(
            config, 'giswater_schema_roles'
        )
        manager_roles, show_manager_roles = self._tier_roles_from_config(
            config, 'giswater_manager_roles'
        )
        giswater_roles, show_giswater_roles = self._tier_roles_from_config(
            config, 'giswater_roles'
        )
        return {
            'mode': self._parse_user_source_mode(config),
            'schema_roles': schema_roles,
            'manager_roles': manager_roles,
            'giswater_tier_roles': giswater_roles,
            'show_schema_roles': show_schema_roles,
            'show_manager_roles': show_manager_roles,
            'show_giswater_roles': show_giswater_roles,
            'require_audit_comment': self._parse_bool_config(
                config.get('giswater_roles_require_comment'), False
            ),
            'keycloak_token_url': (
                config.get('giswater_keycloak_token_url') or ''
            ).strip(),
            'keycloak_client_id': (
                config.get('giswater_keycloak_client_id') or ''
            ).strip(),
            'keycloak_client_secret': (
                config.get('giswater_keycloak_client_secret') or ''
            ).strip(),
            'keycloak_users_url': (
                config.get('giswater_keycloak_users_url') or ''
            ).strip(),
        }

    def _parse_user_source_mode(self, config):
        """Return configured user directory mode (keycloak or qwc2)."""
        raw_mode = config.get('giswater_roles_mode')
        if raw_mode is None:
            return USER_SOURCE_KEYCLOAK
        mode = str(raw_mode).strip().lower()
        if mode in ('qwc', 'qwc2'):
            return USER_SOURCE_QWC2
        if mode == USER_SOURCE_KEYCLOAK:
            return USER_SOURCE_KEYCLOAK
        self.logger.warning(
            "Invalid giswater_roles_mode '%s', falling back to keycloak",
            raw_mode
        )
        return USER_SOURCE_KEYCLOAK

    def _parse_bool_config(self, value, default=False):
        """Parse a boolean-like config value."""
        if value is None:
            return default
        if isinstance(value, bool):
            return value
        if isinstance(value, (int, float)):
            return bool(value)
        text_value = str(value).strip().lower()
        if text_value in ('1', 'true', 'yes', 'on'):
            return True
        if text_value in ('0', 'false', 'no', 'off', ''):
            return False
        return default

    def _read_audit_comment(self, required=None):
        """Read audit comment from the current request; enforce when required."""
        from flask import request

        if required is None:
            required = self._plugin_config()['require_audit_comment']
        comment = (request.form.get('audit_comment') or '').strip()
        if required and not comment:
            raise ValueError(i18n.translate('audit_comment_required'))
        return comment or None

    def _uses_keycloak_users(self):
        return self._plugin_config()['mode'] == USER_SOURCE_KEYCLOAK

    def _load_directory_users(self):
        """Load users from the configured directory (Keycloak or QWC)."""
        if self._uses_keycloak_users():
            return self._load_keycloak_users()
        return self._load_qwc_directory_users()

    def _load_qwc_directory_users(self):
        from flask import g

        cache_key = '_giswater_roles_qwc_directory_users'
        cached = getattr(g, cache_key, None)
        if cached is not None:
            return cached

        users = []
        for user in self._load_qwc_users():
            name = (user.name or '').strip()
            if not name:
                continue
            users.append({
                'name': name,
                'email': (getattr(user, 'email', None) or '').strip(),
                'enabled': True,
            })
        users.sort(key=lambda item: item['name'].lower())
        setattr(g, cache_key, users)
        return users

    def _directory_user_keys(self):
        from flask import g

        cache_key = '_giswater_roles_directory_user_keys'
        cached = getattr(g, cache_key, None)
        if cached is not None:
            return cached

        keys = {
            self._username_key(user['name'])
            for user in self._load_directory_users()
        }
        setattr(g, cache_key, keys)
        return keys

    def _ensure_directory_user(self, username):
        if self._username_key(username) not in self._directory_user_keys():
            mode = self._plugin_config()['mode']
            raise ValueError(i18n.translate(
                'invalid_directory_user_%s' % mode,
                username=username
            ))

    def _tier_roles_from_config(self, config, key):
        """Return configured role names and whether the tier is enabled in config."""
        raw_value = config.get(key)
        if raw_value is None:
            return [], False
        roles = self._parse_config_role_list(raw_value)
        if not roles:
            return [], False
        return roles, True

    def _parse_config_role_list(self, value):
        """Parse a role list from admin config; never falls back to defaults."""
        if value is None:
            return []
        if isinstance(value, str):
            items = [
                item.strip()
                for item in value.split(',')
                if item and item.strip()
            ]
        elif isinstance(value, (list, tuple, set)):
            items = [
                str(item).strip()
                for item in value
                if item is not None and str(item).strip()
            ]
        else:
            return []
        return items

    def _pg_roles_that_exist(self, role_names):
        """Return the subset of role names that exist in PostgreSQL."""
        role_names = sorted({role for role in role_names if role})
        if not role_names:
            return set()
        with self._with_giswater_connection() as conn:
            rows = conn.execute(
                text("SELECT rolname FROM pg_roles WHERE rolname = ANY(:roles)"),
                {"roles": role_names}
            ).fetchall()
        return {row[0] for row in rows}

    def _ensure_roles_exist_in_db(self, role_names):
        """Raise if any role to grant does not exist in PostgreSQL."""
        role_names = [role for role in role_names if role]
        if not role_names:
            return
        missing = sorted(set(role_names) - self._pg_roles_that_exist(role_names))
        if not missing:
            return
        if len(missing) == 1:
            raise ValueError(i18n.translate("role_not_in_db", role=missing[0]))
        raise ValueError(i18n.translate(
            "roles_not_in_db", roles=", ".join(missing)
        ))

    def _keycloak_client(self):
        plugin_config = self._plugin_config()
        return KeycloakClient(
            token_url=plugin_config['keycloak_token_url'],
            client_id=plugin_config['keycloak_client_id'],
            client_secret=plugin_config['keycloak_client_secret'],
            users_url=plugin_config['keycloak_users_url'] or None,
            logger=self.logger,
        )

    def _load_keycloak_users(self):
        from flask import g

        cache_key = '_giswater_roles_keycloak_users'
        cached = getattr(g, cache_key, None)
        if cached is not None:
            return cached

        users = self._keycloak_client().list_users()
        setattr(g, cache_key, users)
        return users

    def _output_config_path(self):
        output_config_path = self.handler().config().get('output_config_path')
        if output_config_path is None:
            raise RuntimeError(i18n.translate("required_config_not_set"))
        return output_config_path

    def _load_giswater_config(self):
        from flask import g

        cache_key = '_giswater_roles_giswater_config'
        if hasattr(g, cache_key):
            return getattr(g, cache_key)

        config_file_path = os.path.join(
            self._output_config_path(), self.handler().tenant, 'giswaterConfig.json'
        )
        self.logger.info("Reading giswater config from %s" % config_file_path)
        with open(config_file_path, encoding='utf-8') as f:
            config = json.load(f)
        setattr(g, cache_key, config)
        return config

    def _giswater_db_url(self, for_write=False):
        giswater_config = self._load_giswater_config()
        config = giswater_config.get('config', {})
        if for_write:
            db_url_key = 'db_url_write'
            db_url = config.get(db_url_key) or config.get('db_url_read')
        else:
            db_url_key = 'db_url_read'
            db_url = config.get(db_url_key)

        if not db_url:
            raise RuntimeError(
                i18n.translate("giswater_db_url_not_found", key=db_url_key)
            )
        return db_url

    def _qwc_config_models(self):
        db_url = self.handler().config().get('db_url')
        if not db_url:
            raise RuntimeError(i18n.translate("qwc_db_url_not_set"))
        return ConfigModels(self.db_engine, conn_str=db_url)

    def _load_qwc_users(self):
        config_models = self._qwc_config_models()
        with config_models.session() as session:
            User = config_models.user_model
            return session.query(User).order_by(User.name).all()

    def _load_shared_user_data(self):
        """Load directory users enriched with QWC/PG sync status."""
        from flask import g

        cache_key = '_giswater_roles_shared_user_data'
        cached = getattr(g, cache_key, None)
        if cached is not None:
            return cached

        available_giswater_roles = self._get_available_roles()
        available_schema_roles = self._get_available_schema_roles()
        available_manager_roles = self._get_available_manager_roles()
        all_grantable_roles = set(
            available_giswater_roles
            + available_schema_roles
            + available_manager_roles
        )
        pg_roles_by_user = self._get_all_user_role_memberships(all_grantable_roles)
        pg_login_roles = self._get_pg_login_roles()
        qwc_users = self._load_qwc_users()
        qwc_by_key, pg_login_by_key, pg_roles_by_key = self._build_lookup_maps(
            qwc_users, pg_login_roles, pg_roles_by_user
        )

        directory_users = self._load_directory_users()
        main_users = []
        for directory_user in directory_users:
            username = directory_user['name']
            user_data = self._resolve_user_sync(
                username, qwc_by_key, pg_login_by_key, pg_roles_by_key
            )
            main_users.append(user_data)

        result = (
            available_giswater_roles,
            available_schema_roles,
            available_manager_roles,
            main_users,
        )
        setattr(g, cache_key, result)
        return result

    def _load_users_with_roles(self):
        """Load directory users with QWC/PG sync status."""
        _, _, _, main_users = self._load_shared_user_data()
        return main_users

    def _get_pg_login_roles(self):
        """Return PostgreSQL roles that match directory usernames."""
        directory_keys = self._directory_user_keys()
        if not directory_keys:
            return set()

        with self._with_giswater_connection() as conn:
            rows = conn.execute(
                text("SELECT rolname FROM pg_roles")
            ).fetchall()
        return {
            row[0] for row in rows
            if self._username_key(row[0]) in directory_keys
        }

    def _get_all_user_role_memberships(self, available_roles):
        """Return {username: [role, ...]} for all users with grantable roles."""
        if not available_roles:
            return {}

        roles_list = sorted(set(available_roles))
        with self._with_giswater_connection() as conn:
            rows = conn.execute(
                text("""
                    SELECT u.rolname AS username, r.rolname AS role
                    FROM pg_auth_members m
                    JOIN pg_roles r ON m.roleid = r.oid
                    JOIN pg_roles u ON m.member = u.oid
                    WHERE NOT r.rolcanlogin
                      AND r.rolname = ANY(:roles)
                    ORDER BY u.rolname, r.rolname
                """),
                {"roles": roles_list}
            ).fetchall()

        memberships = {}
        directory_keys = self._directory_user_keys()
        for username, role in rows:
            if self._username_key(username) not in directory_keys:
                continue
            memberships.setdefault(username, []).append(role)
        return memberships

    def _filter_users(
        self, users, search, schema_role='', manager_role='',
        giswater_role='', not_in_pg=False
    ):
        """Apply text search and role filters to the user list."""
        if search:
            search_lower = search.lower()
            users = [
                user for user in users
                if search_lower in user['name'].lower()
            ]

        if not_in_pg:
            users = [
                user for user in users
                if not user.get('has_pg')
            ]

        if schema_role:
            users = [
                user for user in users
                if schema_role in user.get('current_schema_roles', [])
            ]

        if manager_role:
            users = [
                user for user in users
                if user.get('current_manager_role') == manager_role
            ]

        if giswater_role:
            users = [
                user for user in users
                if user.get('current_role') == giswater_role
            ]

        return users

    def _get_qwc_user_by_name(self, username):
        config_models = self._qwc_config_models()
        with config_models.session() as session:
            User = config_models.user_model
            return session.query(User).filter_by(name=username).first()

    def _delete_qwc_user(self, user_id):
        config_models = self._qwc_config_models()
        with config_models.session() as session:
            with session.begin():
                User = config_models.user_model
                user = session.query(User).filter_by(id=user_id).first()
                if user is None:
                    raise ValueError(i18n.translate("user_not_found"))

                session.execute(
                    text(
                        "DELETE FROM qwc_config.users_roles "
                        "WHERE user_id = :user_id"
                    ),
                    {"user_id": user.id}
                )
                session.execute(
                    text(
                        "DELETE FROM qwc_config.groups_users "
                        "WHERE user_id = :user_id"
                    ),
                    {"user_id": user.id}
                )
                session.execute(
                    text(
                        "DELETE FROM qwc_config.user_infos "
                        "WHERE user_id = :user_id"
                    ),
                    {"user_id": user.id}
                )
                session.delete(user)

        return user_id

    def _get_qwc_user(self, user_id):
        config_models = self._qwc_config_models()
        with config_models.session() as session:
            User = config_models.user_model
            return session.query(User).filter_by(id=user_id).first()

    def _get_synced_qwc_user(self, user_id):
        """Return QWC user only if it also exists in the Giswater data DB."""
        user = self._get_qwc_user(user_id)
        if user is None:
            return None
        if not self._pg_role_exists(user.name):
            return None
        return user

    def _validate_pg_identifier(self, name):
        if not PG_IDENTIFIER_RE.match(name):
            raise ValueError(i18n.translate("invalid_pg_identifier", name=name))
        return name

    def _quote_pg_identifier(self, name):
        self._validate_pg_identifier(name)
        return '"%s"' % name.replace('"', '""')

    def _with_giswater_connection(self, for_write=False):
        db_url = self._giswater_db_url(for_write=for_write)
        return self.db_engine.db_engine(db_url).connect()

    def _pg_role_exists(self, username):
        self._validate_pg_identifier(username)
        with self._with_giswater_connection() as conn:
            result = conn.execute(
                text(
                    "SELECT 1 FROM pg_roles "
                    "WHERE rolname = :username"
                ),
                {"username": username}
            ).fetchone()
            return result is not None

    def _get_assigned_roles_for_tier(self, username, tier):
        """Return configured tier roles currently assigned to a login role."""
        self._validate_pg_identifier(username)
        tier_roles = sorted(self._tier_available_roles(tier))
        if not tier_roles:
            return []
        with self._with_giswater_connection() as conn:
            rows = conn.execute(
                text("""
                    SELECT r.rolname
                    FROM pg_auth_members m
                    JOIN pg_roles r ON m.roleid = r.oid
                    JOIN pg_roles u ON m.member = u.oid
                    WHERE u.rolname = :username
                      AND NOT r.rolcanlogin
                      AND r.rolname = ANY(:roles)
                    ORDER BY r.rolname
                """),
                {"username": username, "roles": tier_roles}
            ).fetchall()
        return [row[0] for row in rows]

    def _get_all_grantable_assigned_roles(self, username):
        """Return all configured grantable roles assigned to a login role."""
        self._validate_pg_identifier(username)
        assigned = []
        for tier in ('schema', 'manager', 'giswater'):
            assigned.extend(self._get_assigned_roles_for_tier(username, tier))
        return assigned

    def _split_roles_by_tier(self, assigned_roles):
        schema_roles = []
        manager_roles = []
        giswater_roles = []
        for role in assigned_roles:
            tier = self._role_tier(role)
            if tier == 'schema':
                schema_roles.append(role)
            elif tier == 'manager':
                manager_roles.append(role)
            elif tier == 'giswater':
                giswater_roles.append(role)
        return schema_roles, manager_roles, giswater_roles

    def _role_tier(self, role_name):
        if role_name in self._tier_available_roles('schema'):
            return 'schema'
        if role_name in self._tier_available_roles('manager'):
            return 'manager'
        if role_name in self._tier_available_roles('giswater'):
            return 'giswater'
        return None

    def _get_available_schema_roles(self):
        return list(self._plugin_config()['schema_roles'])

    def _get_available_manager_roles(self):
        return list(self._plugin_config()['manager_roles'])

    def _get_available_roles(self):
        return list(self._plugin_config()['giswater_tier_roles'])

    def _tier_available_roles(self, tier):
        if tier == 'schema':
            return set(self._get_available_schema_roles())
        if tier == 'manager':
            return set(self._get_available_manager_roles())
        return set(self._get_available_roles())

    def _parse_role_list(self, value):
        if not value:
            return []
        if isinstance(value, (list, tuple, set)):
            items = value
        else:
            items = str(value).split(',')
        return [
            item.strip() for item in items
            if item and str(item).strip()
        ]

    def _set_user_schema_roles(self, username, roles, observ=None):
        """Assign multiple schema roles, revoking any other schema roles."""
        available_roles = self._tier_available_roles('schema')
        desired = set(roles or []) & available_roles
        current = (
            set(self._get_assigned_roles_for_tier(username, 'schema'))
            & available_roles
        )
        roles_to_grant = desired - current
        roles_to_revoke = current - desired
        self._update_role_memberships(
            username, roles_to_grant, roles_to_revoke, observ=observ
        )

    def _set_user_tier_role(self, username, role, tier, observ=None):
        """Assign a single role within one tier, revoking others in that tier."""
        available_roles = self._tier_available_roles(tier)
        current_roles = (
            set(self._get_assigned_roles_for_tier(username, tier))
            & available_roles
        )

        if role:
            roles_to_grant = {role} - current_roles
            roles_to_revoke = current_roles - {role}
        else:
            roles_to_grant = set()
            roles_to_revoke = current_roles

        self._update_role_memberships(
            username, roles_to_grant, roles_to_revoke, observ=observ
        )

    def _set_user_role(self, username, role, observ=None):
        """Assign a single Giswater role, revoking any other grantable roles."""
        self._set_user_tier_role(username, role, 'giswater', observ=observ)

    def _update_role_memberships(
        self, username, roles_to_grant, roles_to_revoke, observ=None
    ):
        self._validate_pg_identifier(username)
        quoted_user = self._quote_pg_identifier(username)

        if roles_to_grant:
            self._ensure_roles_exist_in_db(roles_to_grant)

        with self._with_giswater_connection(for_write=True) as conn:
            with conn.begin():
                for role in sorted(roles_to_revoke):
                    quoted_role = self._quote_pg_identifier(role)
                    conn.execute(text("REVOKE %s FROM %s" % (quoted_role, quoted_user)))
                    self._insert_user_log(
                        conn, "revoke", username, old_data=role, observ=observ
                    )

                for role in sorted(roles_to_grant):
                    quoted_role = self._quote_pg_identifier(role)
                    conn.execute(text("GRANT %s TO %s" % (quoted_role, quoted_user)))
                    self._insert_user_log(
                        conn, "grant", username, new_data=role, observ=observ
                    )

    def _insert_user_log(
        self, conn, log_type, user_name, old_data=None, new_data=None, observ=None
    ):
        """Write an entry to audit.user_log (same schema as QWC2 Login)."""
        conn.execute(
            USER_LOG_INSERT,
            {
                "type": log_type,
                "process_name": AUDIT_PROCESS_NAME,
                "user_name": user_name,
                "old_data": old_data,
                "new_data": new_data,
                "observ": observ,
            },
        )

    def _create_pg_login_user(self, username, roles_to_grant=None, observ=None):
        """Create a PostgreSQL group role for a user and optionally grant tier roles."""
        self._validate_pg_identifier(username)
        if self._pg_role_exists(username):
            raise ValueError(i18n.translate(
                "pg_user_already_exists", username=username
            ))

        roles_to_grant = list(roles_to_grant or [])
        available_roles = (
            set(self._get_available_schema_roles())
            | set(self._get_available_manager_roles())
            | set(self._get_available_roles())
        )
        for role in roles_to_grant:
            if role not in available_roles:
                raise ValueError(i18n.translate("invalid_role", role=role))

        self._ensure_roles_exist_in_db(roles_to_grant)

        quoted_user = self._quote_pg_identifier(username)

        with self._with_giswater_connection(for_write=True) as conn:
            with conn.begin():
                conn.execute(text("CREATE ROLE %s" % quoted_user))
                self._insert_user_log(
                    conn, "create", username, observ=observ
                )
                for role in sorted(set(roles_to_grant)):
                    quoted_role = self._quote_pg_identifier(role)
                    conn.execute(
                        text("GRANT %s TO %s" % (quoted_role, quoted_user))
                    )
                    self._insert_user_log(
                        conn, "grant", username, new_data=role, observ=observ
                    )

    def _find_pg_username(self, username):
        key = self._username_key(username)
        for pg_name in self._get_pg_login_roles():
            if self._username_key(pg_name) == key:
                return pg_name
        return None

    def _drop_pg_login_user(self, username, observ=None):
        """Revoke privileges and drop a PostgreSQL login role."""
        self._validate_pg_identifier(username)
        if not self._pg_role_exists(username):
            raise ValueError(i18n.translate(
                "pg_role_not_found_plain", username=username
            ))

        quoted_user = self._quote_pg_identifier(username)

        with self._with_giswater_connection(for_write=True) as conn:
            with conn.begin():
                for role in sorted(self._get_all_grantable_assigned_roles(username)):
                    quoted_role = self._quote_pg_identifier(role)
                    conn.execute(
                        text("REVOKE %s FROM %s" % (quoted_role, quoted_user))
                    )

                db_name = conn.execute(text("SELECT current_database()")).scalar()
                quoted_db = '"%s"' % db_name.replace('"', '""')
                conn.execute(
                    text(
                        "REVOKE ALL PRIVILEGES ON DATABASE %s FROM %s"
                        % (quoted_db, quoted_user)
                    )
                )
                conn.execute(
                    text(
                        "REVOKE CONNECT ON DATABASE %s FROM %s"
                        % (quoted_db, quoted_user)
                    )
                )
                self._insert_user_log(
                    conn, "delete", username, observ=observ
                )
                conn.execute(text("DROP ROLE %s" % quoted_user))

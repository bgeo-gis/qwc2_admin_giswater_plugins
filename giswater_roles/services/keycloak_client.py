"""
Keycloak Admin API client using client credentials grant.
"""
import json
import re
import urllib.error
import urllib.parse
import urllib.request


REALM_TOKEN_URL_RE = re.compile(
    r'^(https?://[^/]+)/realms/([^/]+)/protocol/openid-connect/token/?$',
    re.IGNORECASE
)


class KeycloakClientError(Exception):
    """Raised when Keycloak authentication or API calls fail."""


class KeycloakClient:
    """Fetch users from Keycloak using client credentials."""

    def __init__(self, token_url, client_id, client_secret, users_url=None, logger=None):
        self.token_url = (token_url or '').strip()
        self.client_id = (client_id or '').strip()
        self.client_secret = (client_secret or '').strip()
        self.users_url = (users_url or '').strip() or self._derive_users_url()
        self.logger = logger

    def _derive_users_url(self):
        match = REALM_TOKEN_URL_RE.match(self.token_url)
        if not match:
            raise KeycloakClientError(
                "Cannot derive Keycloak users URL from token URL. "
                "Set giswater_keycloak_users_url explicitly."
            )
        return '%s/admin/realms/%s/users' % (match.group(1), match.group(2))

    def _log(self, message):
        if self.logger is not None:
            self.logger.info(message)

    def _request_json(self, url, method='GET', data=None, headers=None):
        request_headers = dict(headers or {})
        if data is not None and 'Content-Type' not in request_headers:
            request_headers['Content-Type'] = 'application/x-www-form-urlencoded'
        req = urllib.request.Request(
            url,
            data=data,
            headers=request_headers,
            method=method
        )
        try:
            with urllib.request.urlopen(req, timeout=30) as response:
                body = response.read().decode('utf-8')
                if not body:
                    return None
                return json.loads(body)
        except urllib.error.HTTPError as exc:
            detail = exc.read().decode('utf-8', errors='replace')
            raise KeycloakClientError(
                'Keycloak HTTP %s: %s' % (exc.code, detail or exc.reason)
            ) from exc
        except urllib.error.URLError as exc:
            raise KeycloakClientError('Keycloak request failed: %s' % exc.reason) from exc

    def get_access_token(self):
        if not self.token_url or not self.client_id or not self.client_secret:
            raise KeycloakClientError(
                'Keycloak token URL, client_id and client_secret are required'
            )

        payload = urllib.parse.urlencode({
            'grant_type': 'client_credentials',
            'client_id': self.client_id,
            'client_secret': self.client_secret,
        }).encode('utf-8')
        self._log('Requesting Keycloak access token from %s' % self.token_url)
        response = self._request_json(self.token_url, method='POST', data=payload)
        if not response or not response.get('access_token'):
            raise KeycloakClientError('Keycloak token response did not include access_token')
        return response['access_token']

    def list_users(self):
        access_token = self.get_access_token()
        users = []
        first = 0
        page_size = 100

        while True:
            query = urllib.parse.urlencode({'first': first, 'max': page_size})
            url = '%s?%s' % (self.users_url, query)
            self._log('Fetching Keycloak users from %s' % url)
            batch = self._request_json(
                url,
                headers={'Authorization': 'Bearer %s' % access_token}
            )
            if not batch:
                break
            users.extend(batch)
            if len(batch) < page_size:
                break
            first += page_size

        normalized = []
        for user in users:
            username = (user.get('username') or '').strip()
            if not username:
                continue
            normalized.append({
                'name': username,
                'email': (user.get('email') or '').strip(),
                'enabled': user.get('enabled', True),
            })

        normalized.sort(key=lambda item: item['name'].lower())
        return normalized

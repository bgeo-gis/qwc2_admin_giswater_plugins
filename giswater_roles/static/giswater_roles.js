(function($) {
  'use strict';

  var PENDING_STORAGE_KEY = 'giswater_roles_pending_changes';

  function getConfig() {
    var el = document.getElementById('giswater-roles-config');
    if (!el) {
      return {};
    }
    return JSON.parse(el.textContent);
  }

  function loadPendingStore() {
    try {
      return JSON.parse(sessionStorage.getItem(PENDING_STORAGE_KEY) || '{}');
    } catch (e) {
      return {};
    }
  }

  function savePendingStore(store) {
    sessionStorage.setItem(PENDING_STORAGE_KEY, JSON.stringify(store));
  }

  function clearPendingStore() {
    sessionStorage.removeItem(PENDING_STORAGE_KEY);
  }

  function initTooltips($root) {
    if (!$.fn.tooltip) {
      return;
    }
    ($root || $(document)).find('[data-toggle="tooltip"]').each(function() {
      var $el = $(this);
      try {
        if ($el.data('bs.tooltip')) {
          $el.tooltip('destroy');
        }
      } catch (e) {
        /* ignore stale tooltip instances */
      }
      $el.tooltip({ container: 'body' });
    });
  }

  function showGlobalOverlay(message) {
    $('#gw-global-overlay .gw-overlay-message').text(message);
    $('#gw-global-overlay').removeAttr('hidden').addClass('is-visible');
    $('body').addClass('gw-overlay-active');
  }

  function showSectionOverlay(message) {
    $('#synced-section-overlay .gw-section-overlay-text').text(message);
    $('#synced-section-overlay').prop('hidden', false).addClass('is-visible');
  }

  function hideSectionOverlay() {
    $('#synced-section-overlay').removeClass('is-visible').prop('hidden', true);
  }

  function showConfirm(options) {
    var deferred = $.Deferred();
    var $modal = $('#gw-confirm-modal');
    $('#gw-confirm-title').text(options.title || '');
    $('#gw-confirm-body').empty();
    if (options.bodyHtml) {
      $('#gw-confirm-body').html(options.bodyHtml);
    } else {
      $('#gw-confirm-body').text(options.body || '');
    }
    $('#gw-confirm-ok')
      .toggleClass('btn-danger', !!options.danger)
      .toggleClass('btn-primary', !options.danger);
    $modal.removeAttr('hidden').addClass('is-open');
    $('body').addClass('gw-modal-open');

    function closeModal(result) {
      $modal.removeClass('is-open').attr('hidden', 'hidden');
      $('body').removeClass('gw-modal-open');
      $('#gw-confirm-ok').off('click.gwConfirm');
      $('#gw-confirm-cancel').off('click.gwConfirm');
      $modal.find('.gw-modal-backdrop').off('click.gwConfirm');
      deferred.resolve(result);
    }

    $('#gw-confirm-ok').on('click.gwConfirm', function() {
      closeModal(true);
    });
    $('#gw-confirm-cancel').on('click.gwConfirm', function() {
      closeModal(false);
    });
    $modal.find('.gw-modal-backdrop').on('click.gwConfirm', function() {
      closeModal(false);
    });

    return deferred.promise();
  }

  function submitFormNative(form) {
    HTMLFormElement.prototype.submit.call(form);
  }

  $(function() {
    var config = getConfig();
    var searchInput = $('#search');
    var filterForm = $('#filter-form');
    var searchTimeout = null;
    var filterRequestSeq = 0;
    var activeFilterRequest = null;
    var managerGiswaterSelectSelector =
      '.user-manager-role-select, .user-role-select';

    function managerGiswaterSelects($root, username) {
      var $selects = ($root || $('#synced-section-content'))
        .find(managerGiswaterSelectSelector);
      if (username) {
        $selects = $selects.filter('[data-username="' + username + '"]');
      }
      return $selects;
    }

    function readNoRoleLabel($el) {
      return String($el.attr('data-no-role') || $el.data('noRole') || '');
    }

    function roleLabel(value, noRoleLabel) {
      return value || noRoleLabel;
    }

    function tierEnabled(tier) {
      if (tier === 'schema') {
        return !!config.showSchemaRoles;
      }
      if (tier === 'manager') {
        return !!config.showManagerRoles;
      }
      if (tier === 'giswater') {
        return !!config.showGiswaterRoles;
      }
      return false;
    }

    function readUrlPageParams() {
      var params = new URLSearchParams(window.location.search);
      return {
        synced_page: parseInt(params.get('synced_page') || '1', 10)
      };
    }

    function buildQueryParams(syncedPage) {
      var params = new URLSearchParams();
      var search = $.trim(searchInput.val());
      var schemaRole = $('#schema_role').val();
      var managerRole = $('#manager_role').val();
      var giswaterRole = $('#giswater_role').val();
      var notInPg = $('#not_in_pg').is(':checked');
      var perPage = $('#per_page').val();
      var pages = readUrlPageParams();

      if (syncedPage !== null && syncedPage !== undefined) {
        pages.synced_page = syncedPage;
      }

      if (search) {
        params.set('search', search);
      }
      if (tierEnabled('schema') && schemaRole) {
        params.set('schema_role', schemaRole);
      }
      if (tierEnabled('manager') && managerRole) {
        params.set('manager_role', managerRole);
      }
      if (tierEnabled('giswater') && giswaterRole) {
        params.set('giswater_role', giswaterRole);
      }
      if (notInPg) {
        params.set('not_in_pg', '1');
      }
      if (perPage && perPage !== '10') {
        params.set('per_page', perPage);
      }
      if (pages.synced_page > 1) {
        params.set('synced_page', pages.synced_page);
      }

      return params;
    }

    function updateBrowserUrl() {
      var params = buildQueryParams(null);
      var query = params.toString();
      var url = window.location.pathname + (query ? '?' + query : '');
      history.replaceState(null, '', url);
    }

    function updateFormActions() {
      var query = buildQueryParams(null).toString();
      var suffix = query ? '?' + query : '';
      var urls = config.urls || {};
      $('#apply-pending-roles-form').attr('action', (urls.applyChanges || '') + suffix);
      $('#bulk-role-form').attr('action', (urls.bulkRoles || '') + suffix);
    }

    function getSectionTotal() {
      var $partial = $('#synced-section-content .gw-table-partial');
      if (!$partial.length) {
        return 0;
      }
      return parseInt($partial.attr('data-total') || '0', 10);
    }

    function updateSectionTotals() {
      $('.gw-section-synced .gw-count-badge').text(getSectionTotal());
    }

    function emptyRoleState() {
      return { schema: [], manager: '', giswater: '' };
    }

    function normalizeSchemaRoles(value) {
      if (Array.isArray(value)) {
        return value.map(function(role) {
          return String(role).trim();
        }).filter(Boolean).sort();
      }
      if (!value) {
        return [];
      }
      return String(value).split(',').map(function(role) {
        return role.trim();
      }).filter(Boolean).sort();
    }

    function schemaRolesEqual(a, b) {
      var left = normalizeSchemaRoles(a);
      var right = normalizeSchemaRoles(b);
      return left.length === right.length &&
        left.every(function(role, index) {
          return role === right[index];
        });
    }

    function readSchemaRolesFromContainer($container) {
      var roles = [];
      $container.find('.gw-schema-role-checkbox:checked').each(function() {
        roles.push(String($(this).val()));
      });
      return roles.sort();
    }

    function formatSchemaRolesLabel(roles, noRoleLabel) {
      var normalized = normalizeSchemaRoles(roles);
      if (!normalized.length) {
        return noRoleLabel;
      }
      if (normalized.length === 1) {
        return normalized[0];
      }
      if (normalized.length === 2) {
        return normalized.join(', ');
      }
      return (config.schemaRolesSelectedLabel || '{count} roles')
        .replace('{count}', normalized.length);
    }

    function refreshSchemaMultiSelectLabel($container) {
      var noRoleLabel = String($container.data('noRole') || '');
      var roles = readSchemaRolesFromContainer($container);
      var label = formatSchemaRolesLabel(roles, noRoleLabel);
      $container.find('.gw-multi-select-label').text(label);
      $container.attr('title', roles.length ? roles.join(', ') : noRoleLabel);
    }

    function initSchemaMultiSelects($root) {
      ($root || $('#synced-section-content')).find('.gw-schema-multi-select')
        .not('.gw-bulk-schema-multi-select')
        .each(function() {
          refreshSchemaMultiSelectLabel($(this));
        });
    }

    function positionSchemaMultiSelectPanel($container) {
      var $toggle = $container.find('.gw-multi-select-toggle');
      var $panel = $container.find('.gw-multi-select-panel');
      if (!$toggle.length || !$panel.length) {
        return;
      }
      var rect = $toggle[0].getBoundingClientRect();
      $panel.css({
        top: Math.round(rect.bottom + 2) + 'px',
        left: Math.round(rect.left) + 'px',
        width: Math.round(rect.width) + 'px',
        minWidth: Math.round(rect.width) + 'px'
      });
    }

    function closeAllSchemaMultiSelects() {
      $('.gw-schema-multi-select.open').removeClass('open');
    }

    function openSchemaMultiSelect($container) {
      closeAllSchemaMultiSelects();
      $container.addClass('open');
      positionSchemaMultiSelectPanel($container);
    }

    function readRoleStateFromSelects(username) {
      var state = emptyRoleState();
      var $schema = $('#synced-section-content .gw-schema-multi-select[data-username="' +
        username + '"]');
      if ($schema.length) {
        state.schema = readSchemaRolesFromContainer($schema);
      }
      managerGiswaterSelects(null, username).each(function() {
        var tier = String($(this).data('tier'));
        if (tier === 'manager' || tier === 'giswater') {
          state[tier] = String($(this).val());
        }
      });
      return state;
    }

    function readOriginalRoleState(username) {
      var state = emptyRoleState();
      var $schema = $('#synced-section-content .gw-schema-multi-select[data-username="' +
        username + '"]');
      if ($schema.length) {
        state.schema = normalizeSchemaRoles($schema.data('original'));
      }
      managerGiswaterSelects(null, username).each(function() {
        var tier = String($(this).data('tier'));
        if (tier === 'manager' || tier === 'giswater') {
          state[tier] = String($(this).data('original') || '');
        }
      });
      return state;
    }

    function roleStatesEqual(a, b) {
      if (tierEnabled('schema') && !schemaRolesEqual(a.schema, b.schema)) {
        return false;
      }
      if (tierEnabled('manager') && a.manager !== b.manager) {
        return false;
      }
      if (tierEnabled('giswater') && a.giswater !== b.giswater) {
        return false;
      }
      return true;
    }

    function restorePendingToVisibleSelects() {
      var store = loadPendingStore();
      Object.keys(store).forEach(function(username) {
        var item = store[username];
        var roles = item.roles || emptyRoleState();
        var $schema = $('#synced-section-content .gw-schema-multi-select[data-username="' +
          username + '"]');
        if ($schema.length) {
          var schemaRoles = normalizeSchemaRoles(roles.schema);
          $schema.find('.gw-schema-role-checkbox').each(function() {
            var role = String($(this).val());
            $(this).prop('checked', schemaRoles.indexOf(role) >= 0);
          });
          refreshSchemaMultiSelectLabel($schema);
        }
        managerGiswaterSelects(null, username).each(function() {
          var tier = String($(this).data('tier'));
          if (tier === 'manager' || tier === 'giswater') {
            $(this).val(roles[tier]);
          }
        });
      });
    }

    function userNeedsPgCreate(username) {
      var $row = $('#synced-section-content .gw-schema-multi-select[data-username="' +
        username + '"]').closest('tr');
      if ($row.length) {
        return $row.hasClass('gw-row-pending-pg');
      }
      var store = loadPendingStore();
      return !!(store[username] && store[username].needsPgCreate);
    }

    function persistRoleChange(username) {
      var original = readOriginalRoleState(username);
      var current = readRoleStateFromSelects(username);
      var store = loadPendingStore();

      if (roleStatesEqual(original, current)) {
        delete store[username];
      } else {
        store[username] = {
          username: username,
          original: original,
          roles: current,
          needsPgCreate: userNeedsPgCreate(username)
        };
      }
      savePendingStore(store);
    }

    function formatRoleChangeSegment(label, fromRole, toRole, noRoleLabel) {
      if (Array.isArray(fromRole) || Array.isArray(toRole)) {
        var fromLabel = Array.isArray(fromRole)
          ? formatSchemaRolesLabel(fromRole, noRoleLabel)
          : roleLabel(fromRole, noRoleLabel);
        var toLabel = Array.isArray(toRole)
          ? formatSchemaRolesLabel(toRole, noRoleLabel)
          : roleLabel(toRole, noRoleLabel);
        if (fromLabel === toLabel) {
          return '';
        }
        return label + ': ' + fromLabel + ' → ' + toLabel;
      }
      if (fromRole === toRole) {
        return '';
      }
      return label + ': ' +
        roleLabel(fromRole, noRoleLabel) + ' → ' +
        roleLabel(toRole, noRoleLabel);
    }

    function getAllPendingRoleChanges() {
      var store = loadPendingStore();
      var form = $('#apply-pending-roles-form');
      var noRoleLabel = readNoRoleLabel(form);
      var changeLineTemplate = form.data('change-line');
      var changes = [];

      Object.keys(store).forEach(function(username) {
        var item = store[username];
        var original = item.original || emptyRoleState();
        var roles = item.roles || emptyRoleState();
        var segments = [];
        if (tierEnabled('schema')) {
          segments.push(formatRoleChangeSegment(
            config.schemaRoleLabel || 'Schema',
            original.schema,
            roles.schema,
            noRoleLabel
          ));
        }
        if (tierEnabled('manager')) {
          segments.push(formatRoleChangeSegment(
            config.managerRoleLabel || 'Manager',
            original.manager,
            roles.manager,
            noRoleLabel
          ));
        }
        if (tierEnabled('giswater')) {
          segments.push(formatRoleChangeSegment(
            config.giswaterRoleLabel || 'Giswater',
            original.giswater,
            roles.giswater,
            noRoleLabel
          ));
        }
        segments = segments.filter(function(segment) {
          return !!segment;
        });

        changes.push({
          username: item.username,
          schemaRole: normalizeSchemaRoles(roles.schema).join(','),
          managerRole: roles.manager,
          giswaterRole: roles.giswater,
          needsPgCreate: item.needsPgCreate !== undefined
            ? !!item.needsPgCreate
            : userNeedsPgCreate(item.username),
          line: changeLineTemplate
            .replace('{username}', item.username)
            .replace('{changes}', segments.join('; '))
            .replace('{from_role}', roleLabel(original.giswater, noRoleLabel))
            .replace('{to_role}', roleLabel(roles.giswater, noRoleLabel))
        });
      });
      return changes;
    }

    function restoreOriginalRoleStateForUser(username) {
      var $schema = $('#synced-section-content .gw-schema-multi-select[data-username="' +
        username + '"]');
      if ($schema.length) {
        var schemaRoles = normalizeSchemaRoles($schema.data('original'));
        $schema.find('.gw-schema-role-checkbox').each(function() {
          var role = String($(this).val());
          $(this).prop('checked', schemaRoles.indexOf(role) >= 0);
        });
        refreshSchemaMultiSelectLabel($schema);
      }
      managerGiswaterSelects(null, username).each(function() {
        var tier = String($(this).data('tier'));
        if (tier === 'manager' || tier === 'giswater') {
          $(this).val(String($(this).data('original') || ''));
        }
      });
    }

    function cancelAllPendingRoleChanges() {
      $('#synced-section-content .gw-schema-multi-select').each(function() {
        restoreOriginalRoleStateForUser(String($(this).data('username')));
      });
      clearPendingStore();
      closeAllSchemaMultiSelects();
      updatePendingRolesUi();
    }

    function confirmCancelPendingRoleChanges() {
      if (getAllPendingRoleChanges().length === 0) {
        return;
      }
      showConfirm({
        title: config.confirmTitle,
        body: config.cancelPendingConfirm
      }).then(function(ok) {
        if (ok) {
          cancelAllPendingRoleChanges();
        }
      });
    }

    function updatePendingRolesUi() {
      var scrollX = window.pageXOffset;
      var scrollY = window.pageYOffset;
      var activeEl = document.activeElement;
      var keepFocus = activeEl && (
        $(activeEl).closest(
          '.gw-multi-select-panel, .gw-multi-select-toggle, ' + managerGiswaterSelectSelector
        ).length > 0
      );
      var changes = getAllPendingRoleChanges();
      var store = loadPendingStore();

      managerGiswaterSelects().each(function() {
        var username = String($(this).data('username'));
        var original = String($(this).data('original') || '');
        var current = String($(this).val());
        var changed = !!store[username] || current !== original;
        $(this).toggleClass('role-changed', changed);
      });

      $('#synced-section-content .gw-schema-multi-select').each(function() {
        var $container = $(this);
        var username = String($container.data('username'));
        var changed = !!store[username] || !schemaRolesEqual(
          readSchemaRolesFromContainer($container),
          normalizeSchemaRoles($container.data('original'))
        );
        $container.toggleClass('role-changed', changed);
      });

      if (changes.length > 0) {
        $('#apply-pending-roles-form').addClass('has-pending');
        $('#pending-roles-count').text(changes.length);
        $('.gw-pending-banner-slot').addClass('is-visible');
        $('#pending-banner-text').text(
          (config.pendingBannerText || '').replace('{count}', changes.length)
        );
      } else {
        $('#apply-pending-roles-form').removeClass('has-pending');
        $('.gw-pending-banner-slot').removeClass('is-visible');
      }

      $('.gw-schema-multi-select.open').each(function() {
        positionSchemaMultiSelectPanel($(this));
      });

      window.scrollTo(scrollX, scrollY);

      if (keepFocus && activeEl && $.contains(document.documentElement, activeEl)) {
        try {
          activeEl.focus({ preventScroll: true });
        } catch (e) {
          activeEl.focus();
        }
      }
    }

    function afterSectionUpdate() {
      closeAllSchemaMultiSelects();
      initTooltips($('#synced-section-content'));
      updateSectionTotals();
      updateFormActions();
      restorePendingToVisibleSelects();
      initSchemaMultiSelects($('#synced-section-content'));
      updateSyncedSelectionToolbar();
      refreshBulkSchemaMultiSelectLabel();
      updatePendingRolesUi();
    }

    function fetchSectionHtml(params) {
      var url = config.partialSyncedUrl;
      var query = params.toString();
      return $.get(url + (query ? '?' + query : ''));
    }

    function loadTableSection(page) {
      var params = buildQueryParams(page);
      var $container = $('#synced-section-content');

      showSectionOverlay(config.loadingPage);
      return fetchSectionHtml(params)
        .done(function(html) {
          $container.html(html);
          updateBrowserUrl();
          afterSectionUpdate();
        })
        .fail(function() {
          alert(config.loadTableError);
        })
        .always(function() {
          hideSectionOverlay();
        });
    }

    function refreshSection() {
      var pages = readUrlPageParams();
      loadTableSection(pages.synced_page);
    }

    function finishFilterRequest(seq) {
      if (seq !== filterRequestSeq) {
        return;
      }
      hideSectionOverlay();
    }

    function applyFilterResponse(seq, syncedHtml) {
      if (seq !== filterRequestSeq) {
        return;
      }
      hideSectionOverlay();
      $('#synced-section-content').html(syncedHtml);
      updateBrowserUrl();
      try {
        afterSectionUpdate();
      } catch (e) {
        /* keep filtered table visible even if post-render UI fails */
      }
    }

    function applyFilters() {
      var seq = ++filterRequestSeq;
      var params = buildQueryParams(1);
      var query = params.toString();
      var querySuffix = query ? '?' + query : '';

      if (activeFilterRequest) {
        activeFilterRequest.abort();
        activeFilterRequest = null;
      }

      showSectionOverlay(config.loadingFilters);

      if (config.partialTablesUrl) {
        activeFilterRequest = $.getJSON(config.partialTablesUrl + querySuffix);
        activeFilterRequest
          .done(function(data) {
            applyFilterResponse(seq, data.synced_html);
          })
          .fail(function(_jqXHR, textStatus) {
            if (textStatus === 'abort' || seq !== filterRequestSeq) {
              return;
            }
            alert(config.loadTableError);
          })
          .always(function() {
            if (activeFilterRequest && seq === filterRequestSeq) {
              activeFilterRequest = null;
            }
            finishFilterRequest(seq);
          });
        return;
      }

      activeFilterRequest = fetchSectionHtml(params);
      activeFilterRequest
        .done(function(syncedHtml) {
          applyFilterResponse(seq, syncedHtml);
        })
        .fail(function(_jqXHR, textStatus) {
          if (textStatus === 'abort' || seq !== filterRequestSeq) {
            return;
          }
          alert(config.loadTableError);
        })
        .always(function() {
          if (activeFilterRequest && seq === filterRequestSeq) {
            activeFilterRequest = null;
          }
          finishFilterRequest(seq);
        });
    }

    function refreshBulkSchemaMultiSelectLabel() {
      if (!tierEnabled('schema')) {
        return;
      }
      var $container = $('#bulk-role-form .gw-bulk-schema-multi-select');
      if (!$container.length) {
        return;
      }
      var noRoleLabel = readNoRoleLabel($('#bulk-role-form'));
      var roles = [];
      $container.find('.gw-bulk-schema-role-checkbox:checked').each(function() {
        roles.push(String($(this).val()));
      });
      roles.sort();
      $container.find('.gw-multi-select-label').text(
        formatSchemaRolesLabel(roles, noRoleLabel)
      );
      $('#bulk-schema-roles').val(roles.join(','));
    }

    function formatBulkRolesConfirmBody(form, count) {
      var noRoleLabel = readNoRoleLabel($(form));
      var schemaRoles = tierEnabled('schema')
        ? normalizeSchemaRoles($('#bulk-schema-roles').val() || '')
        : [];
      var managerRole = tierEnabled('manager')
        ? String($('#bulk-manager-role-select').val() || '')
        : '';
      var giswaterRole = tierEnabled('giswater')
        ? String($('#bulk-giswater-role-select').val() || '')
        : '';
      var createUsers = [];
      roleEligibleCheckboxes().filter(':checked').each(function() {
        var username = String($(this).data('username') || $(this).val() || '');
        if (username && userNeedsPgCreate(username)) {
          createUsers.push(username);
        }
      });
      createUsers.sort();
      var parts = [
        '<p>' + $(form).data('confirm-header').replace('{count}', count) + '</p>'
      ];
      if (createUsers.length > 0) {
        parts.push(
          '<p class="gw-confirm-note">' +
          $('<div>').text(config.pendingRolesCreatePgIntro).html() +
          '</p>'
        );
        parts.push(
          '<ul class="gw-confirm-list">' +
          createUsers.map(function(username) {
            return '<li><strong>[' + (config.createPgBadgeLabel || 'PG') + ']</strong> ' +
              $('<span>').text(username).html() + '</li>';
          }).join('') +
          '</ul>'
        );
      }
      var roleLines = [];
      if (tierEnabled('schema')) {
        roleLines.push(
          '<li>' + (config.schemaRoleLabel || 'Schema') + ': ' +
            formatSchemaRolesLabel(schemaRoles, noRoleLabel) + '</li>'
        );
      }
      if (tierEnabled('manager')) {
        roleLines.push(
          '<li>' + (config.managerRoleLabel || 'Manager') + ': ' +
            roleLabel(managerRole, noRoleLabel) + '</li>'
        );
      }
      if (tierEnabled('giswater')) {
        roleLines.push(
          '<li>' + (config.giswaterRoleLabel || 'Giswater') + ': ' +
            roleLabel(giswaterRole, noRoleLabel) + '</li>'
        );
      }
      if (roleLines.length > 0) {
        parts.push(
          '<ul class="gw-confirm-list">',
          roleLines.join(''),
          '</ul>'
        );
      }
      return parts.join('');
    }

    function roleEligibleCheckboxes() {
      return $('#synced-section-content .user-checkbox').filter(function() {
        return !$(this).data('noRoles');
      });
    }

    function resetBulkRoleForm() {
      var $form = $('#bulk-role-form');
      if (!$form.length) {
        return;
      }
      $form.find('.gw-bulk-schema-role-checkbox').prop('checked', false);
      $('#bulk-manager-role-select, #bulk-giswater-role-select').val('');
      refreshBulkSchemaMultiSelectLabel();
    }

    function updateSyncedSelectionToolbar() {
      var roleChecked = roleEligibleCheckboxes().filter(':checked');
      var $bulkForm = $('#bulk-role-form');

      if ($bulkForm.length) {
        if (roleChecked.length > 0) {
          $bulkForm.addClass('is-visible');
          $('#bulk-role-count').text(roleChecked.length);
        } else {
          $bulkForm.removeClass('is-visible');
          resetBulkRoleForm();
        }
      }

      var total = $('#synced-section-content .user-checkbox').length;
      var checked = $('#synced-section-content .user-checkbox:checked').length;
      $('#select-all-synced').prop('checked', total > 0 && checked === total);
    }

    filterForm.on('submit', function(e) {
      e.preventDefault();
      applyFilters();
    });

    searchInput.on('input', function() {
      clearTimeout(searchTimeout);
      searchTimeout = setTimeout(applyFilters, 500);
    });

    $('#schema_role, #manager_role, #giswater_role').on('change', applyFilters);
    $('#not_in_pg').on('change', applyFilters);
    $('#per_page').on('change', applyFilters);

    $('#clear-filters').on('click', function(e) {
      e.preventDefault();
      searchInput.val('');
      $('#schema_role, #manager_role, #giswater_role').val('');
      $('#not_in_pg').prop('checked', false);
      $('#per_page').val('10');
      applyFilters();
    });

    $(document).on('click', '.gw-page-link', function(e) {
      e.preventDefault();
      var page = parseInt($(this).data('page'), 10);
      if (!page) {
        return;
      }
      loadTableSection(page);
    });

    $(document).on('click', '.gw-refresh-section', function() {
      refreshSection();
    });

    $(document).on('submit', '#bulk-role-form', function(e) {
      e.preventDefault();
      var form = this;
      var checked = roleEligibleCheckboxes().filter(':checked');
      if (checked.length === 0) {
        return;
      }
      refreshBulkSchemaMultiSelectLabel();
      showConfirm({
        title: config.confirmTitle,
        bodyHtml: formatBulkRolesConfirmBody(form, checked.length)
      }).then(function(ok) {
        if (!ok) {
          return;
        }
        $('#bulk-role-usernames').empty();
        checked.each(function() {
          $('#bulk-role-usernames').append(
            $('<input type="hidden" name="usernames">').val($(this).val())
          );
        });
        showGlobalOverlay(config.applyingRoles);
        submitFormNative(form);
      });
    });

    $(document).on('change', '.gw-bulk-schema-role-checkbox', function() {
      refreshBulkSchemaMultiSelectLabel();
    });

    $(document).on('submit', '.create-pg-form', function(e) {
      e.preventDefault();
      var form = this;
      var $form = $(form);
      var username = $form.find('input[name="username"]').val();
      var $row = $form.closest('tr');
      var noRoleLabel = readNoRoleLabel($form);
      var roles = { schema: [], manager: '', giswater: '' };
      var $schemaMulti = $row.find('.gw-schema-multi-select');
      if ($schemaMulti.length) {
        roles.schema = readSchemaRolesFromContainer($schemaMulti);
      }

      $row.find('select.create-pg-tier-select').each(function() {
        var tier = String($(this).data('tier'));
        if (tier === 'manager' || tier === 'giswater') {
          roles[tier] = String($(this).val());
        }
      });

      var rolesSummary = [];
      if (tierEnabled('schema')) {
        rolesSummary.push(
          (config.schemaRoleLabel || 'Schema') + ': ' +
            formatSchemaRolesLabel(roles.schema, noRoleLabel)
        );
      }
      if (tierEnabled('manager')) {
        rolesSummary.push(
          (config.managerRoleLabel || 'Manager') + ': ' +
            roleLabel(roles.manager, noRoleLabel)
        );
      }
      if (tierEnabled('giswater')) {
        rolesSummary.push(
          (config.giswaterRoleLabel || 'Giswater') + ': ' +
            roleLabel(roles.giswater, noRoleLabel)
        );
      }
      rolesSummary = rolesSummary.join('; ');

      showConfirm({
        title: config.confirmTitle,
        body: $form.data('confirm')
          .replace('{username}', username)
          .replace('{roles}', rolesSummary)
      }).then(function(ok) {
        if (!ok) {
          return;
        }
        $form.find(
          'input[name="schema_role"], input[name="manager_role"], input[name="role"]'
        ).remove();
        var hiddenFields = [];
        if (tierEnabled('schema')) {
          hiddenFields.push(
            $('<input type="hidden" name="schema_role">').val(roles.schema.join(','))
          );
        }
        if (tierEnabled('manager')) {
          hiddenFields.push(
            $('<input type="hidden" name="manager_role">').val(roles.manager)
          );
        }
        if (tierEnabled('giswater')) {
          hiddenFields.push(
            $('<input type="hidden" name="role">').val(roles.giswater)
          );
        }
        $form.append(hiddenFields);
        showGlobalOverlay(config.creatingPgUser);
        submitFormNative(form);
      });
    });

    $(document).on('submit', '.delete-pg-form', function(e) {
      e.preventDefault();
      var form = this;
      var username = $(form).find('input[name="username"]').val();
      var body = $(form).data('confirm').replace('{username}', username);
      if ($(form).data('hasQwc') === '1' || $(form).data('hasQwc') === 1) {
        body += ' ' + $(form).data('qwcWarning');
      }
      showConfirm({
        title: config.confirmTitle,
        danger: true,
        body: body
      }).then(function(ok) {
        if (!ok) {
          return;
        }
        showGlobalOverlay(config.deletingPgUser);
        submitFormNative(form);
      });
    });

    $(document).on('change', '.user-checkbox', updateSyncedSelectionToolbar);
    $(document).on('change', '#select-all-synced', function() {
      $('#synced-section-content .user-checkbox')
        .prop('checked', $(this).is(':checked'));
      updateSyncedSelectionToolbar();
    });

    $(document).on('change', '.gw-schema-role-checkbox', function() {
      var $container = $(this).closest('.gw-schema-multi-select');
      refreshSchemaMultiSelectLabel($container);
      persistRoleChange(String($container.data('username')));
      updatePendingRolesUi();
    });

    $(document).on('click', '.gw-multi-select-toggle', function(e) {
      e.preventDefault();
      e.stopPropagation();
      var $container = $(this).closest('.gw-schema-multi-select');
      if ($container.hasClass('open')) {
        $container.removeClass('open');
      } else {
        openSchemaMultiSelect($container);
      }
    });

    $(document).on('click', '.gw-multi-select-panel', function(e) {
      e.stopPropagation();
    });

    $(document).on('click', function() {
      closeAllSchemaMultiSelects();
    });

    $(window).on('scroll resize', closeAllSchemaMultiSelects);
    $(document).on('scroll', '.gw-table-card, .gw-data-table, .table-responsive', closeAllSchemaMultiSelects);

    $(document).on('change', managerGiswaterSelectSelector, function() {
      persistRoleChange(String($(this).data('username')));
      updatePendingRolesUi();
    });

    $('#apply-pending-roles-form').on('submit', function(e) {
      e.preventDefault();
      var form = this;
      var changes = getAllPendingRoleChanges();
      if (changes.length === 0) {
        return;
      }
      var createChanges = changes.filter(function(change) {
        return change.needsPgCreate;
      });
      var bodyParts = [];
      if (createChanges.length) {
        bodyParts.push(
          '<p class="gw-confirm-note">' +
          $('<div>').text(config.pendingRolesCreatePgIntro).html() +
          '</p>'
        );
      }
      bodyParts.push(
        '<ul class="gw-confirm-list">' +
        changes.map(function(change) {
          var prefix = change.needsPgCreate
            ? '<strong>[' + (config.createPgBadgeLabel || 'PG') + ']</strong> '
            : '';
          return '<li>' + prefix + change.line + '</li>';
        }).join('') +
        '</ul>'
      );
      showConfirm({
        title: $(form).data('confirm-header'),
        bodyHtml: bodyParts.join('')
      }).then(function(ok) {
        if (!ok) {
          return;
        }
        $('#pending-role-changes').empty();
        changes.forEach(function(change) {
          $('#pending-role-changes').append(
            $('<input type="hidden" name="usernames">').val(change.username),
            $('<input type="hidden" name="schema_roles">').val(change.schemaRole),
            $('<input type="hidden" name="manager_roles">').val(change.managerRole),
            $('<input type="hidden" name="roles">').val(change.giswaterRole)
          );
        });
        clearPendingStore();
        showGlobalOverlay(config.applyingRoles);
        submitFormNative(form);
      });
    });

    $('#pending-banner-apply').on('click', function() {
      $('#apply-pending-roles-form').trigger('submit');
    });

    $('#cancel-pending-roles, #pending-banner-cancel').on('click', function(e) {
      e.preventDefault();
      confirmCancelPendingRoleChanges();
    });

    updateFormActions();
    restorePendingToVisibleSelects();
    initSchemaMultiSelects($(document));
    refreshBulkSchemaMultiSelectLabel();
    initTooltips($(document));
    updatePendingRolesUi();
    updateSyncedSelectionToolbar();
  });
})(jQuery);

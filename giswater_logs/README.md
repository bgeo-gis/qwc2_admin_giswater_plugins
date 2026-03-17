Giswater Logs Plugin
====================

This plugin adds a viewer for the giswater logs to the Admin GUI.


Usage
=====

Enable this plugin by setting the following options in the `config` block of the `adminGui` section of the `tenantConfig.json`:

```json
"plugins": ["giswater_logs"],
"gw_log_path": "<path to the input configs>"
"gw_log_file_prefix": "<name of the gw services folder>"
```

The Admin GUI requires read access to the `gw_log_path`.

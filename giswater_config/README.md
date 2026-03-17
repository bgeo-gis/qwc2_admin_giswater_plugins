Giswater Config Plugin
====================

This plugin adds a viewer for editing the giswater service config file to the Admin GUI.


Usage
=====

Enable this plugin by setting the following options in the `config` block of the `adminGui` section of the `tenantConfig.json`:

```json
"plugins": ["giswater_config"]
```

The Admin GUI requires write access to the `output_config_path`.

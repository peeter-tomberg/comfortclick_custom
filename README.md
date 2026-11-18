# Notice

This is a custom component that works only with a specific comfort click integration.
You will most probably need to fork this for your own use case.

# Why

Wanted to control comfort click from home assistant.

# Whats in this

Integrated a wide range of different entities:

* Platform.CLIMATE
* Platform.LOCK
* Platform.FAN
* Platform.SENSOR
* Platform.SELECT

## Configuration

They are all configurable from `comfortclick_custom.yaml` that should be created in the root folder.

### HTTPS certificate verification

Certificate verification is off by default to preserve compatibility with local
controllers whose certificates are self-signed or invalid. This applies to new
entries and existing entries without a saved preference. Explicitly saved settings
are preserved, so an entry with verification enabled keeps it enabled.

To enable verification, use a controller URL whose hostname matches its trusted
certificate, then open **Settings → Devices & services → ComfortClick → Configure**
and enable **Verify SSL certificate**. This setting is also available during initial
setup. Options can be saved while the controller is unavailable; Home Assistant
reloads the entry after the change. No entities need to be deleted.

With verification off, Home Assistant cannot authenticate the controller's
certificate, exposing credentials and commands to interception. Enable verification
when the controller has a trusted certificate. If enabled verification fails, the
integration reports the error without automatically disabling verification.

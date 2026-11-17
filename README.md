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

HTTPS certificates are verified by default, including for existing entries after
upgrading. Use a controller URL whose hostname matches its trusted certificate.

If your local controller uses a self-signed certificate and stops connecting after
this update, open **Settings → Devices & services → ComfortClick → Configure** and
disable **Verify SSL certificate** for that entry. This setting is also available
during initial setup. Options can be saved while the controller is unavailable;
Home Assistant reloads the entry after the change. No entities need to be deleted.

Disabling verification prevents Home Assistant from authenticating the controller
and exposes credentials and commands to interception. Use this exception only for
a trusted local controller, and re-enable it after installing a trusted certificate.
There is no automatic fallback to an unverified connection.

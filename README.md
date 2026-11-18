# Notice

This is a custom component that works only with a specific comfort click integration.
You will most probably need to fork this for your own use case.

# Why

Wanted to control comfort click from home assistant.

# Whats in this

Integrated a wide range of different entities:

* Platform.CLIMATE
* Platform.EVENT
* Platform.LOCK
* Platform.FAN
* Platform.SENSOR
* Platform.SELECT

## Configuration

Open **Settings → Devices & services → ComfortClick → Configure** to manage
the apartment's devices. Saving one form reloads the integration; reopen Configure
to manage another.

| Section | Available configuration |
| --- | --- |
| Ventilation | One Away/Home/Guests mode selector, one Warm/Cold air selector, and one air-temperature sensor |
| Building doors | Three fixed doors: Main, Cellar, and Garage |
| Utility meters | Five fixed totals: day electricity, night electricity, cold water, hot water, and heating |
| Air conditioners | Add, edit, or remove multiple thermostats and assign each to a Home Assistant room |
| Fans | Add, edit, or remove multiple fans and assign each to a Home Assistant room |
| Doorbell | Information about the one event entity created automatically per integration entry |
| Connection | Controller URL, username, password, and HTTPS certificate verification |

Doors and meters have fixed slots. Select a slot to edit its controller path;
their names and meter types are not editable. Leave a path blank to stop exposing
that slot's entity. The slot remains available for configuration later.
Ventilation has one configuration: its three forms update the same system.

Path fields are searchable lists of device paths already received from the
controller. You can also enter a path manually, including while the controller is
offline. Paths are preserved exactly, including trailing spaces: a controller
path ending in `"Setpoint "` is different from one ending in `"Setpoint"`.
Opening or editing mapping forms does not send device commands or open extra
controller connections. Temperature limits and steps use Celsius.

In **Connection**, leave Password blank to retain the saved password. The saved
password is never displayed. Changes to the controller URL, username, or password
are checked by logging in before they replace the working connection. Failed
validation leaves the saved settings unchanged. Changing only certificate
verification remains possible while the controller is offline.

- **Fans:** map the lock (true means off), fan level, heating-active state, current
  temperature, and target temperature.
- **Air conditioners:** map heating-active state and both temperatures, optionally
  a fan level. Leave the fan path blank for a heating-only thermostat. Configure
  minimum/maximum temperatures and the setpoint step per device.
- **Utility meters:** map cumulative water, electricity, or heating totals. Defaults are
  m³ for water, kWh for electricity, and MWh for heating. An optional unit choice
  must match the raw controller reading; it does not rescale that value. These
  mappings are not instantaneous power or flow sensors.

The **Room** field on fan and air-conditioner forms uses existing Home Assistant
areas. Existing entity room assignments are suggested when importing a mapping.
Clearing the field removes the entity's room assignment when the integration reloads.

All configuration is stored in Home Assistant. Existing installations import
their remaining `comfortclick_custom.yaml` mappings once when upgrading. Categories
already saved through the UI take precedence, including explicitly empty ones.
After successful migration, the YAML file is no longer read and can be archived
or removed. New installations do not need a YAML file.

Migration preserves existing identities and exact controller paths. If legacy
configuration is malformed or its doors/meters cannot be matched to the fixed
catalog, migration stops without changing the stored configuration. Correct the
legacy file and retry the integration before removing it.

Editing an existing mapping preserves its entity identity, references, and
recorded history. Change a meter's path only to another path for the same physical
meter; the fixed catalog does not provide extra meters.

Removing a fan or air conditioner requires confirmation and stops providing that
entity. Clearing a fixed door or meter path also stops providing its entity. The old entity
registry entry may remain unavailable, and its history is retained rather than
purged. It can be removed separately in Home Assistant. New UI mappings belong to
the selected integration entry. A new installation can configure all mappings
through these forms without a YAML file.

The doorbell event entity is created automatically for each ComfortClick
integration entry. See [mapping architecture](docs/mapping-configuration.md) for
the configuration and runtime boundaries.

### Doorbell rings

The **ComfortClick Doorbell** event entity shows when the last ring was received.
Add it to a dashboard like any other entity. Its event type is `ring`; attributes
include the sound, the controller's `timestamp` when provided, and an
`event_sequence` counter for the current entity lifetime. Before the first ring,
the state is unknown. The last event is restored after a Home Assistant restart.

The integration recognizes the observed ComfortClick action
`PlaySound` / `DoorBell2.mp3` in `GetClientData.ActionData`. Other sounds and action
types are ignored. No YAML changes or additional credentials are needed. After
installing this update, restart Home Assistant to load the new event platform.

For automations, use the **`comfortclick_custom_doorbell`** event. This fires once
per new ring while the entity is enabled, including separate rings delivered in
the same poll. Restoring the last entity state or reconnecting alone does not
fire it. Repeated deliveries with the same controller timestamp and sound are
suppressed using a bounded cache of the last 128 rings for the active integration
instance. Rings without a timestamp cannot be deduplicated.

```yaml
alias: Notify when the doorbell rings
trigger:
  - platform: event
    event_type: comfortclick_custom_doorbell
    event_data:
      entity_id: event.comfortclick_doorbell
action:
  - service: persistent_notification.create
    data:
      title: Doorbell
      message: Someone rang the doorbell.
mode: queued
```

Replace `event.comfortclick_doorbell` with the entity ID shown in your installation.
The event also includes `config_entry_id`, `event_type: ring`, `sound`,
`event_sequence`, and `timestamp` when supplied by the controller. Each integration
entry has its own entity, so automations can select the correct connection.

The captured action has no device path or door identifier, so the integration
cannot distinguish different doors that use the same sound. Only new actions
received after the entity starts listening produce events; cached batches are not
replayed when an entity is enabled again, and missed rings while disconnected
cannot be reconstructed.

### HTTPS certificate verification

Certificate verification is off by default to preserve compatibility with local
controllers whose certificates are self-signed or invalid. This applies to new
entries and existing entries without a saved preference. Explicitly saved settings
are preserved, so an entry with verification enabled keeps it enabled.

To enable verification, use a controller URL whose hostname matches its trusted
certificate, then open **Settings → Devices & services → ComfortClick → Configure**
→ **Connection** and enable **Verify SSL certificate**. This setting is also
available during initial setup. A change to certificate verification alone can be
saved while the controller is unavailable; Home Assistant reloads the entry after
the change. No entities need to be deleted.

With verification off, Home Assistant cannot authenticate the controller's
certificate, exposing credentials and commands to interception. Enable verification
when the controller has a trusted certificate. If enabled verification fails, the
integration reports the error without automatically disabling verification.

"""Configure ComfortClick entity mappings using Home Assistant forms."""

from __future__ import annotations

import math
from collections import Counter
from collections.abc import Mapping
from copy import deepcopy
from functools import partial
from hashlib import sha256
from typing import Any
from uuid import uuid4

import voluptuous as vol
from homeassistant import config_entries
from homeassistant.const import CONF_HOST, CONF_PASSWORD, CONF_USERNAME, CONF_VERIFY_SSL
from homeassistant.helpers import area_registry as ar
from homeassistant.helpers import entity_registry as er
from homeassistant.helpers import selector

from .connection import connection_errors, normalize_host, validate_input
from .const import DOMAIN
from .fixed_mappings import DOOR_SLOTS, METER_SLOTS, VENT_FIELDS, import_fixed_mappings

FAN_PATHS = (
    "lock_id",
    "fan_id",
    "heating_id",
    "current_temperature_id",
    "target_temperature_id",
)
THERMOSTAT_PATHS = (
    "heating_id",
    "current_temperature_id",
    "target_temperature_id",
    "fan_id",
)
PRIMARY_PATH = {"fans": "fan_id", "thermostats": "heating_id"}
SECTION_FORM = {"fans": "fan", "thermostats": "thermostat"}
METER_UNITS = {
    "water": ("m³", "L"),
    "electricity": ("Wh", "kWh", "MWh"),
    "heating": ("Wh", "kWh", "MWh"),
}


def _canonical_path(path: str) -> str:
    """Match the API's path comparison without changing stored entity identity."""
    return path.replace("\\\\", "\\")


def _legacy_identity(section: str, mapping: Mapping[str, Any]) -> str:
    """Keep the exact identity used by existing YAML entities."""
    path = mapping.get(PRIMARY_PATH[section], "")
    return f"room-1-{path}" if section == "thermostats" else path


def _import_mappings(source: Any, section: str) -> list[dict[str, Any]]:
    """Validate the list shape and keep legacy identities in an isolated draft."""
    if not isinstance(source, Mapping):
        raise TypeError
    mappings = source.get(section, [])
    if not isinstance(mappings, list) or any(
        not isinstance(item, dict) for item in mappings
    ):
        raise TypeError
    mappings = deepcopy(mappings)
    for mapping in mappings:
        mapping.setdefault("unique_id", _legacy_identity(section, mapping))
    return mappings


def _validate_temperatures(
    user_input: dict[str, Any], result: dict[str, Any], errors: dict[str, str]
) -> None:
    """Validate native Celsius limits without truncating fractional values."""
    for key, default in (
        ("min_temp", 18),
        ("max_temp", 24),
        ("target_temperature_step", 0.5),
    ):
        value = user_input.get(key, default)
        try:
            number = float(value)
        except (TypeError, ValueError):
            errors[key] = "invalid_number"
            continue
        if (
            isinstance(value, bool)
            or not math.isfinite(number)
            or (key == "target_temperature_step" and number <= 0)
        ):
            errors[key] = "invalid_number"
        else:
            result[key] = number
    if (
        "min_temp" in result
        and "max_temp" in result
        and result["min_temp"] >= result["max_temp"]
    ):
        errors["max_temp"] = "invalid_range"


def _validate_mapping(
    section: str,
    user_input: dict[str, Any],
    mappings: list[dict[str, Any]],
    index: int | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate a form without changing the current mappings or controller."""
    errors: dict[str, str] = {}
    result: dict[str, Any] = {}
    fields = FAN_PATHS if section == "fans" else THERMOSTAT_PATHS
    for key in ("name", *fields):
        value = user_input.get(key)
        optional = section == "thermostats" and key == "fan_id"
        if optional and (value is None or value == "" or str(value).isspace()):
            result[key] = None
        elif not isinstance(value, str) or not value.strip():
            errors[key] = "required"
        else:
            result[key] = value.strip() if key == "name" else value

    # The primary reading path identifies a mapping. Also reject two controls
    # writing to the same fan lock or temperature setpoint within one category.
    identity_fields = [PRIMARY_PATH[section]]
    if section == "fans":
        identity_fields.append("lock_id")
    elif section == "thermostats":
        identity_fields.append("target_temperature_id")
    for field in identity_fields:
        value = result.get(field)
        if value and any(
            position != index
            and isinstance(other.get(field), str)
            and _canonical_path(other[field]) == _canonical_path(value)
            for position, other in enumerate(mappings)
        ):
            errors[field] = "duplicate_path"

    if section == "thermostats":
        _validate_temperatures(user_input, result, errors)
    return result, errors


class OptionsFlow(config_entries.OptionsFlow):
    """Manage repeated mappings and connection settings independently."""

    def __init__(self, config_entry: config_entries.ConfigEntry) -> None:
        """Keep compatibility with HA versions with a read-only config_entry."""
        self._entry = config_entry
        self._section = "fans"
        self._mappings: list[dict[str, Any]] = []
        self._index: int | None = None
        self._original_section: Any = None
        self._connection_original: dict[str, Any] | None = None
        self._mapping_actions: set[str] = set()
        self._vent: dict[str, Any] = {}

    async def async_step_init(self, _user_input: dict | None = None) -> Any:
        """Choose the kind of configuration to manage."""
        return self._root_menu()

    def _root_menu(self, *, saved: bool = False) -> Any:
        """Return to configuration after discarding only unsaved draft state."""
        self._clear_mapping_actions()
        self._section = ""
        self._mappings = []
        self._index = None
        self._original_section = None
        self._connection_original = None
        self._vent = {}
        return self.async_show_menu(
            step_id="init",
            menu_options=[
                "ventilation",
                "locks",
                "utilities",
                "thermostats",
                "fans",
                "doorbell",
                "connection",
                "done",
            ],
            description_placeholders={"saved": "true"} if saved else None,
        )

    async def async_step_done(self, _user_input: dict | None = None) -> Any:
        """Close the flow without rewriting settings already saved."""
        return self.async_create_entry(title="", data=None)

    async def async_step_connection(self, user_input: dict | None = None) -> Any:
        """Validate changed credentials before atomically saving the connection."""
        if self._connection_original is None:
            self._connection_original = self._current_connection()
        if user_input is None:
            return self._connection_form(self._connection_original)
        if self._current_connection() != self._connection_original:
            return self.async_abort(reason="connection_changed")
        candidate = {**self._connection_original, **user_input}
        candidate[CONF_PASSWORD] = (
            user_input.get(CONF_PASSWORD) or self._connection_original[CONF_PASSWORD]
        )
        try:
            candidate[CONF_HOST] = normalize_host(candidate[CONF_HOST])
            credentials_changed = (
                candidate[CONF_HOST]
                != self._connection_original[CONF_HOST].strip().rstrip("/")
            ) or any(
                candidate[key] != self._connection_original[key]
                for key in (CONF_USERNAME, CONF_PASSWORD)
            )
            if credentials_changed:
                await validate_input(self.hass, candidate)
        except Exception as error:  # noqa: BLE001 - Return a credential-safe error.
            # Re-render from saved values so neither a password nor a rejected
            # URL containing embedded credentials is reflected in the form.
            return self._connection_form(
                self._connection_original, connection_errors(error)
            )
        if self._current_connection() != self._connection_original:
            return self.async_abort(reason="connection_changed")
        if (
            not credentials_changed
            and candidate[CONF_VERIFY_SSL] == self._connection_original[CONF_VERIFY_SSL]
        ):
            return self._root_menu(saved=True)
        options = {**self._entry.options, CONF_VERIFY_SSL: candidate[CONF_VERIFY_SSL]}
        data = {**self._entry.data, **candidate}
        was_loaded = self._entry.state is config_entries.ConfigEntryState.LOADED
        had_listener = bool(self._entry.update_listeners)
        self.hass.config_entries.async_update_entry(
            self._entry, data=data, options=options
        )
        if not was_loaded and not had_listener:
            self.hass.config_entries.async_schedule_reload(self._entry.entry_id)
        # Both dictionaries were saved together above. Let the existing update
        # listener reload once and keep this flow open for the next operation.
        return self._root_menu(saved=True)

    def _current_connection(self) -> dict[str, Any]:
        """Read only connection fields for concurrent-edit detection."""
        return {
            CONF_HOST: self._entry.data.get(CONF_HOST, ""),
            CONF_USERNAME: self._entry.data.get(CONF_USERNAME, ""),
            CONF_PASSWORD: self._entry.data.get(CONF_PASSWORD, ""),
            CONF_VERIFY_SSL: self._entry.options.get(
                CONF_VERIFY_SSL, self._entry.data.get(CONF_VERIFY_SSL, False)
            ),
        }

    def _connection_form(
        self, values: dict[str, Any], errors: dict[str, str] | None = None
    ) -> Any:
        """Show public settings and an empty masked replacement-password field."""
        return self.async_show_form(
            step_id="connection",
            data_schema=vol.Schema(
                {
                    vol.Required(CONF_HOST, default=values[CONF_HOST]): str,
                    vol.Required(CONF_USERNAME, default=values[CONF_USERNAME]): str,
                    vol.Optional(CONF_PASSWORD): selector.TextSelector(
                        selector.TextSelectorConfig(
                            type=selector.TextSelectorType.PASSWORD
                        )
                    ),
                    vol.Required(
                        CONF_VERIFY_SSL, default=values[CONF_VERIFY_SSL]
                    ): bool,
                }
            ),
            errors=errors or {},
        )

    async def _open_section(self, section: str) -> Any:
        """Import a category into a draft; merely opening it never persists it."""
        self._section = section
        self._index = None
        self._original_section = deepcopy(self._entry.options.get(section))
        try:
            self._mappings = _import_mappings(self._entry.options, section)
        except (ValueError, TypeError):
            return self.async_show_form(
                step_id=section,
                data_schema=vol.Schema({}),
                errors={"base": "cannot_load_mappings"},
            )
        return await self.async_step_mapping()

    async def async_step_fans(self, _user_input: dict | None = None) -> Any:
        """Manage fan mappings."""
        return await self._open_section("fans")

    async def async_step_thermostats(self, _user_input: dict | None = None) -> Any:
        """Manage air conditioner mappings."""
        return await self._open_section("thermostats")

    async def async_step_utilities(self, _user_input: dict | None = None) -> Any:
        """Show the five fixed utility meters."""
        return await self._open_fixed("utilities")

    async def async_step_locks(self, _user_input: dict | None = None) -> Any:
        """Show the three fixed building doors."""
        return await self._open_fixed("locks")

    async def _open_fixed(self, section: str) -> Any:
        """Load fixed slots without persisting anything just by opening them."""
        self._section = section
        self._index = None
        self._original_section = deepcopy(self._entry.options.get(section))
        try:
            self._mappings = import_fixed_mappings(
                self._entry.options, section, self._entry.entry_id
            )
        except (ValueError, TypeError):
            return self.async_show_form(
                step_id=section,
                data_schema=vol.Schema({}),
                errors={"base": "cannot_load_fixed_mappings"},
            )
        slots = METER_SLOTS if section == "utilities" else DOOR_SLOTS
        prefix = "meter" if section == "utilities" else "door"
        return self.async_show_menu(
            step_id=section,
            menu_options=[*(f"{prefix}_{slot}" for slot in slots), "init"],
        )

    def _fixed_slot(self, slot: str) -> Any:
        """Edit one predefined slot without allowing additions or removals."""
        self._index = next(
            index for index, item in enumerate(self._mappings) if item["slot"] == slot
        )
        return self._fixed_form()

    async def async_step_meter_electricity_day(
        self, _user_input: dict | None = None
    ) -> Any:
        """Edit the day electricity meter."""
        return self._fixed_slot("electricity_day")

    async def async_step_meter_electricity_night(
        self, _user_input: dict | None = None
    ) -> Any:
        """Edit the night electricity meter."""
        return self._fixed_slot("electricity_night")

    async def async_step_meter_water_cold(self, _user_input: dict | None = None) -> Any:
        """Edit the cold water meter."""
        return self._fixed_slot("water_cold")

    async def async_step_meter_water_hot(self, _user_input: dict | None = None) -> Any:
        """Edit the hot water meter."""
        return self._fixed_slot("water_hot")

    async def async_step_meter_heating(self, _user_input: dict | None = None) -> Any:
        """Edit the heating meter."""
        return self._fixed_slot("heating")

    async def async_step_door_main(self, _user_input: dict | None = None) -> Any:
        """Edit the building main door."""
        return self._fixed_slot("main")

    async def async_step_door_cellar(self, _user_input: dict | None = None) -> Any:
        """Edit the building cellar door."""
        return self._fixed_slot("cellar")

    async def async_step_door_garage(self, _user_input: dict | None = None) -> Any:
        """Edit the building garage door."""
        return self._fixed_slot("garage")

    def _fixed_form(
        self, values: dict | None = None, errors: dict | None = None
    ) -> Any:
        """Keep the slot's name, type and identity separate from editable paths."""
        mapping = self._mappings[self._index]
        values = mapping if values is None else values
        path_key = "id" if self._section == "utilities" else "door_id"
        name_key = "name" if self._section == "utilities" else "door_name"
        default_name = (
            METER_SLOTS[mapping["slot"]][0]
            if self._section == "utilities"
            else DOOR_SLOTS[mapping["slot"]]
        )
        schema = {
            vol.Optional(
                path_key, description={"suggested_value": values.get(path_key, "")}
            ): self._path_selector(values.get(path_key))
        }
        if self._section == "utilities":
            schema[vol.Required("unit", default=values.get("unit", "default"))] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["default", *METER_UNITS[mapping["type"]]],
                        translation_key="meter_unit",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            )
        return self.async_show_form(
            step_id="utility" if self._section == "utilities" else "door",
            description_placeholders={"name": mapping.get(name_key) or default_name},
            data_schema=vol.Schema(schema),
            errors=errors or {},
        )

    def _submit_fixed(self, user_input: dict | None) -> Any:
        """Save exactly one slot and retain all remaining slots and history."""
        if user_input is None:
            return self._fixed_form()
        mapping = deepcopy(self._mappings[self._index])
        path_key = "id" if self._section == "utilities" else "door_id"
        path = user_input.get(path_key) or ""
        errors = {}
        if not isinstance(path, str):
            errors[path_key] = "required"
        elif path and any(
            index != self._index
            and item.get(path_key)
            and _canonical_path(item[path_key]) == _canonical_path(path)
            for index, item in enumerate(self._mappings)
        ):
            errors[path_key] = "duplicate_path"
        else:
            mapping[path_key] = path if path.strip() else ""
        if self._section == "utilities":
            unit = user_input.get("unit", "default")
            if unit == "default":
                mapping.pop("unit", None)
            elif unit in METER_UNITS[mapping["type"]]:
                mapping["unit"] = unit
            else:
                errors["unit"] = "invalid_unit"
        if errors:
            return self._fixed_form(user_input, errors)
        mappings = deepcopy(self._mappings)
        mappings[self._index] = mapping
        return self._save_mappings(mappings)

    async def async_step_door(self, user_input: dict | None = None) -> Any:
        """Save a building door path without sending an unlock command."""
        return self._submit_fixed(user_input)

    async def async_step_ventilation(self, _user_input: dict | None = None) -> Any:
        """Show the three single ventilation controls."""
        self._section = "vent"
        self._original_section = deepcopy(self._entry.options.get("vent"))
        try:
            self._vent = deepcopy(self._entry.options.get("vent", {}))
            if not isinstance(self._vent, dict):
                return self.async_show_form(
                    step_id="ventilation",
                    data_schema=vol.Schema({}),
                    errors={"base": "cannot_load_mappings"},
                )
        except (ValueError, TypeError):
            return self.async_show_form(
                step_id="ventilation",
                data_schema=vol.Schema({}),
                errors={"base": "cannot_load_mappings"},
            )
        return self.async_show_menu(
            step_id="ventilation",
            menu_options=[*VENT_FIELDS, "init"],
        )

    def _vent_form(self, step: str, user_input: dict | None) -> Any:
        """Edit one ventilation control, preserving the other controls."""
        errors = {}
        if user_input is not None:
            updated = deepcopy(self._vent)
            for field in VENT_FIELDS[step]:
                path = user_input.get(field) or ""
                if not isinstance(path, str):
                    errors[field] = "required"
                else:
                    updated[field] = path if path.strip() else ""
            if not errors:
                if self._entry.options.get("vent") != self._original_section:
                    return self.async_abort(reason="mappings_changed")
                return self._save_options({"vent": updated})
        values = self._vent if user_input is None else user_input
        return self.async_show_form(
            step_id=step,
            data_schema=vol.Schema(
                {
                    vol.Optional(
                        field, description={"suggested_value": values.get(field) or ""}
                    ): self._path_selector(values.get(field))
                    for field in VENT_FIELDS[step]
                }
            ),
            errors=errors,
        )

    async def async_step_vent_mode(self, user_input: dict | None = None) -> Any:
        """Configure one Home/Away/Guests selector."""
        return self._vent_form("vent_mode", user_input)

    async def async_step_vent_air_mode(self, user_input: dict | None = None) -> Any:
        """Configure one warm/cold air selector."""
        return self._vent_form("vent_air_mode", user_input)

    async def async_step_vent_temperature(self, user_input: dict | None = None) -> Any:
        """Configure the readings behind one ventilation temperature sensor."""
        return self._vent_form("vent_temperature", user_input)

    async def async_step_doorbell(self, user_input: dict | None = None) -> Any:
        """Explain the one automatically created ring event."""
        if user_input is not None:
            return await self.async_step_init()
        return self.async_show_form(step_id="doorbell", data_schema=vol.Schema({}))

    async def async_step_mapping(self, _user_input: dict | None = None) -> Any:
        """Show each room device as a directly clickable named row."""
        if self._section not in ("fans", "thermostats"):
            return self.async_abort(reason="fixed_slots")
        operations = self._mapping_menu_options(remove=False)
        if operations is None:
            return self.async_abort(reason="mappings_changed")
        device = "fan" if self._section == "fans" else "air conditioner"
        operations["add_mapping"] = f"Add {device}"
        if self._mappings:
            operations["remove_mapping"] = f"Remove {device}"
        operations["init"] = "Back"
        return self.async_show_menu(
            step_id="mapping",
            menu_options=operations,
            description_placeholders={
                "category": "Fans" if self._section == "fans" else "Air conditioners"
            },
        )

    def _clear_mapping_actions(self) -> None:
        """Remove only this flow's dynamically registered menu handlers."""
        for step_id in self._mapping_actions:
            delattr(self, f"async_step_{step_id}")
        self._mapping_actions.clear()

    def _mapping_area_id(self, mapping: Mapping[str, Any]) -> str | None:
        """Use configured room or the current entity's legacy room assignment."""
        area_id = mapping.get("area_id")
        registry = self.hass.data.get(er.DATA_REGISTRY)
        if area_id is None and registry:
            entity_id = registry.async_get_entity_id(
                "fan" if self._section == "fans" else "climate",
                DOMAIN,
                mapping["unique_id"],
            )
            if entity_id and (entity := registry.async_get(entity_id)):
                area_id = entity.area_id
        return area_id

    def _mapping_label(self, mapping: Mapping[str, Any]) -> str:
        """Name a room device without exposing its controller path in the list."""
        name = mapping.get("name") or (
            "Fan" if self._section == "fans" else "Air conditioner"
        )
        area_id = self._mapping_area_id(mapping)
        areas = self.hass.data.get(ar.DATA_REGISTRY)
        if area_id and areas and (area := areas.async_get_area(area_id)):
            return f"{name} — {area.name}"
        return name

    def _mapping_menu_options(self, *, remove: bool) -> dict[str, str] | None:
        """Bind opaque, stable menu actions to immutable mapping identities."""
        self._clear_mapping_actions()
        identities = [mapping["unique_id"] for mapping in self._mappings]
        if any(not isinstance(identity, str) for identity in identities) or len(
            set(identities)
        ) != len(identities):
            return None
        labels = [self._mapping_label(mapping) for mapping in self._mappings]
        counts = Counter(labels)
        occurrences: Counter[str] = Counter()
        options = {}
        for identity, label in zip(identities, labels, strict=True):
            digest = sha256(f"{self._section}\0{identity}".encode()).hexdigest()
            step_id = f"{'remove' if remove else 'edit'}_{digest}"
            setattr(
                self,
                f"async_step_{step_id}",
                partial(
                    self._select_mapping_identity,
                    self._section,
                    identity,
                    remove=remove,
                ),
            )
            self._mapping_actions.add(step_id)
            occurrences[label] += 1
            options[step_id] = (
                f"{label} ({occurrences[label]})" if counts[label] > 1 else label
            )
        return options

    async def _select_mapping_identity(
        self,
        section: str,
        identity: str,
        _user_input: dict | None = None,
        *,
        remove: bool,
    ) -> Any:
        """Resolve a clicked identity against current options and reject stale rows."""
        if (
            section != self._section
            or self._entry.options.get(section) != self._original_section
        ):
            return self.async_abort(reason="mappings_changed")
        try:
            mappings = _import_mappings(self._entry.options, section)
        except (TypeError, ValueError):
            return self.async_abort(reason="mappings_changed")
        matches = [
            index
            for index, mapping in enumerate(mappings)
            if mapping["unique_id"] == identity
        ]
        if len(matches) != 1:
            return self.async_abort(reason="mappings_changed")
        self._mappings = mappings
        self._index = matches[0]
        if remove:
            return await self.async_step_confirm_remove()
        return self._mapping_form()

    async def async_step_add_mapping(self, _user_input: dict | None = None) -> Any:
        """Start a new independent mapping."""
        if self._section not in ("fans", "thermostats"):
            return self.async_abort(reason="fixed_slots")
        self._index = None
        return self._mapping_form()

    async def async_step_remove_mapping(self, _user_input: dict | None = None) -> Any:
        """Select a mapping to stop providing."""
        if self._section not in ("fans", "thermostats"):
            return self.async_abort(reason="fixed_slots")
        operations = self._mapping_menu_options(remove=True)
        if operations is None:
            return self.async_abort(reason="mappings_changed")
        operations["mapping"] = "Back"
        return self.async_show_menu(step_id="remove_mapping", menu_options=operations)

    async def async_step_confirm_remove(self, user_input: dict | None = None) -> Any:
        """Confirm removal without deleting registry entries or history."""
        if self._section not in ("fans", "thermostats"):
            return self.async_abort(reason="fixed_slots")
        if self._index is None:
            return await self.async_step_mapping()
        if user_input is not None:
            if user_input.get("confirm") is True:
                mappings = deepcopy(self._mappings)
                mappings.pop(self._index)
                return self._save_mappings(mappings)
            return await self.async_step_mapping()
        return self.async_show_form(
            step_id="confirm_remove",
            description_placeholders={
                "name": self._mappings[self._index].get("name") or "—"
            },
            data_schema=vol.Schema({vol.Required("confirm", default=False): bool}),
        )

    def _path_selector(self, current: Any) -> selector.SelectSelector:
        """Offer cached paths and permit offline/manual configuration."""
        runtime = self.hass.data.get(DOMAIN, {}).get(self._entry.entry_id)
        paths = set(runtime.coordinator.api.get_device_paths()) if runtime else set()
        if isinstance(current, str) and current:
            paths.add(current)
        return selector.SelectSelector(
            selector.SelectSelectorConfig(
                options=sorted(paths),
                custom_value=True,
                mode=selector.SelectSelectorMode.DROPDOWN,
            )
        )

    def _mapping_form(
        self, values: dict | None = None, errors: dict | None = None
    ) -> Any:
        """Render fields for one fan, air conditioner, or meter."""
        if values is None:
            values = self._mappings[self._index] if self._index is not None else {}
        schema: dict[Any, Any] = {
            vol.Required(
                "name", description={"suggested_value": values.get("name", "")}
            ): str
        }
        area_id = values.get("area_id")
        if area_id is None and self._index is not None:
            area_id = self._mapping_area_id(self._mappings[self._index])
        schema[vol.Optional("area_id", description={"suggested_value": area_id})] = (
            selector.AreaSelector()
        )
        fields = FAN_PATHS if self._section == "fans" else THERMOSTAT_PATHS
        for field in fields:
            marker = (
                vol.Optional
                if self._section == "thermostats" and field == "fan_id"
                else vol.Required
            )
            schema[
                marker(field, description={"suggested_value": values.get(field) or ""})
            ] = self._path_selector(values.get(field))
        if self._section == "thermostats":
            for field, default in (
                ("min_temp", 18),
                ("max_temp", 24),
                ("target_temperature_step", 0.5),
            ):
                schema[vol.Required(field, default=values.get(field, default))] = (
                    selector.NumberSelector(
                        selector.NumberSelectorConfig(
                            mode=selector.NumberSelectorMode.BOX,
                            step="any",
                            unit_of_measurement="°C",
                        )
                    )
                )
        return self.async_show_form(
            step_id=SECTION_FORM[self._section],
            data_schema=vol.Schema(schema),
            errors=errors or {},
        )

    def _submit_mapping(self, user_input: dict | None) -> Any:
        """Commit only a valid mapping; keep identity on all edits."""
        if self._section not in ("fans", "thermostats"):
            return self.async_abort(reason="fixed_slots")
        if user_input is None:
            return self._mapping_form()
        mapping, errors = _validate_mapping(
            self._section, user_input, self._mappings, self._index
        )
        if errors:
            return self._mapping_form(user_input, errors)
        mapping["area_id"] = user_input.get("area_id") or ""
        mappings = deepcopy(self._mappings)
        if self._index is None:
            mapping["unique_id"] = f"{self._entry.entry_id}-{uuid4().hex}"
            mappings.append(mapping)
        else:
            mapping["unique_id"] = mappings[self._index]["unique_id"]
            mappings[self._index] = mapping
        return self._save_mappings(mappings)

    async def async_step_fan(self, user_input: dict | None = None) -> Any:
        """Validate and save a fan."""
        return self._submit_mapping(user_input)

    async def async_step_thermostat(self, user_input: dict | None = None) -> Any:
        """Validate and save an air conditioner."""
        return self._submit_mapping(user_input)

    async def async_step_utility(self, user_input: dict | None = None) -> Any:
        """Validate and save a utility meter."""
        return self._submit_fixed(user_input)

    def _save_mappings(self, mappings: list[dict[str, Any]]) -> Any:
        """Avoid overwriting another options flow editing this same category."""
        if self._entry.options.get(self._section) != self._original_section:
            return self.async_abort(reason="mappings_changed")
        return self._save_options({self._section: mappings})

    def _save_options(self, changes: dict[str, Any]) -> Any:
        """Merge unrelated options and reload even after a failed setup."""
        options = {**self._entry.options, **changes}
        if options == self._entry.options:
            return self._root_menu(saved=True)
        was_loaded = self._entry.state is config_entries.ConfigEntryState.LOADED
        had_listener = bool(self._entry.update_listeners)
        self.hass.config_entries.async_update_entry(self._entry, options=options)
        if not was_loaded and not had_listener:
            self.hass.config_entries.async_schedule_reload(self._entry.entry_id)
        return self._root_menu(saved=True)

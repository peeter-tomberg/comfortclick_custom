"""Configure ComfortClick entity mappings using Home Assistant forms."""

from __future__ import annotations

import math
from collections.abc import Mapping
from copy import deepcopy
from typing import Any
from uuid import uuid4

import voluptuous as vol
import yaml
from homeassistant import config_entries
from homeassistant.const import CONF_VERIFY_SSL
from homeassistant.helpers import selector

from .const import DOMAIN
from .util.read_yaml import read_yaml

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
PRIMARY_PATH = {"fans": "fan_id", "thermostats": "heating_id", "utilities": "id"}
SECTION_FORM = {"fans": "fan", "thermostats": "thermostat", "utilities": "utility"}
METER_UNITS = {
    "water": ("m³", "L"),
    "electricity": ("Wh", "kWh", "MWh"),
    "heating": ("Wh", "kWh", "MWh"),
}


def _canonical_path(path: str) -> str:
    """Match the API's path comparison without changing stored entity identity."""
    return path.replace("\\\\", "\\").strip()


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


def _validate_meter(
    user_input: dict[str, Any], result: dict[str, Any], errors: dict[str, str]
) -> None:
    """Validate compatible reading units for cumulative utility meters."""
    meter_type = user_input.get("type")
    if meter_type not in METER_UNITS:
        errors["type"] = "invalid_type"
    else:
        result["type"] = meter_type
    unit = user_input.get("unit", "default")
    if unit != "default":
        if unit not in METER_UNITS.get(meter_type, ()):
            errors["unit"] = "invalid_unit"
        else:
            result["unit"] = unit


def _validate_mapping(
    section: str,
    user_input: dict[str, Any],
    mappings: list[dict[str, Any]],
    index: int | None,
) -> tuple[dict[str, Any], dict[str, str]]:
    """Validate a form without changing the current mappings or controller."""
    errors: dict[str, str] = {}
    result: dict[str, Any] = {}
    fields = (
        FAN_PATHS
        if section == "fans"
        else THERMOSTAT_PATHS
        if section == "thermostats"
        else ("id",)
    )
    for key in ("name", *fields):
        value = user_input.get(key)
        optional = section == "thermostats" and key == "fan_id"
        if optional and (value is None or value == "" or str(value).isspace()):
            result[key] = None
        elif not isinstance(value, str) or not value.strip():
            errors[key] = "required"
        else:
            result[key] = value.strip()

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
    elif section == "utilities":
        _validate_meter(user_input, result, errors)
        if (
            index is not None
            and "type" in result
            and mappings[index].get("type") in METER_UNITS
            and (mappings[index]["type"] == "water") != (result["type"] == "water")
        ):
            errors["type"] = "incompatible_meter_type"
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

    async def async_step_init(self, _user_input: dict | None = None) -> Any:
        """Choose the kind of configuration to manage."""
        return self.async_show_menu(
            step_id="init",
            menu_options=["fans", "thermostats", "utilities", "connection"],
        )

    async def async_step_connection(self, user_input: dict | None = None) -> Any:
        """Save TLS preferences even when the controller is unavailable."""
        if user_input is not None:
            return self._save_options({CONF_VERIFY_SSL: user_input[CONF_VERIFY_SSL]})
        verify_ssl = self._entry.options.get(
            CONF_VERIFY_SSL, self._entry.data.get(CONF_VERIFY_SSL, False)
        )
        return self.async_show_form(
            step_id="connection",
            data_schema=vol.Schema(
                {vol.Required(CONF_VERIFY_SSL, default=verify_ssl): bool}
            ),
        )

    async def _open_section(self, section: str) -> Any:
        """Import a category into a draft; merely opening it never persists it."""
        self._section = section
        self._index = None
        self._original_section = deepcopy(self._entry.options.get(section))
        try:
            source = (
                self._entry.options
                if section in self._entry.options
                else await read_yaml()
            )
            self._mappings = _import_mappings(source, section)
        except (OSError, ValueError, TypeError, yaml.YAMLError):
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
        """Manage utility meter mappings."""
        return await self._open_section("utilities")

    async def async_step_mapping(self, _user_input: dict | None = None) -> Any:
        """List configured names and available operations."""
        operations = ["add_mapping"]
        if self._mappings:
            operations.extend(("edit_mapping", "remove_mapping"))
        operations.append("init")
        return self.async_show_menu(
            step_id="mapping",
            menu_options=operations,
            description_placeholders={
                "configured": "\n".join(
                    f"- {item.get('name') or item.get(PRIMARY_PATH[self._section])}"
                    for item in self._mappings
                )
                or "—"
            },
        )

    async def async_step_add_mapping(self, _user_input: dict | None = None) -> Any:
        """Start a new independent mapping."""
        self._index = None
        return self._mapping_form()

    async def _select_mapping(self, step: str, user_input: dict | None) -> Any:
        """Select a record by position, allowing equal display names."""
        errors = {}
        if user_input is not None:
            try:
                index = int(user_input["mapping"])
            except (KeyError, TypeError, ValueError):
                errors["mapping"] = "required"
            else:
                if 0 <= index < len(self._mappings):
                    self._index = index
                    if step == "remove_mapping":
                        return await self.async_step_confirm_remove()
                    return self._mapping_form()
                errors["mapping"] = "required"
        return self.async_show_form(
            step_id=step,
            data_schema=vol.Schema(
                {
                    vol.Required("mapping"): selector.SelectSelector(
                        selector.SelectSelectorConfig(
                            options=[
                                {
                                    "value": str(index),
                                    "label": (
                                        f"{item.get('name') or '—'} — "
                                        f"{item.get(PRIMARY_PATH[self._section], '')}"
                                    ),
                                }
                                for index, item in enumerate(self._mappings)
                            ],
                            mode=selector.SelectSelectorMode.DROPDOWN,
                        )
                    )
                }
            ),
            errors=errors,
        )

    async def async_step_edit_mapping(self, user_input: dict | None = None) -> Any:
        """Select a mapping to edit."""
        return await self._select_mapping("edit_mapping", user_input)

    async def async_step_remove_mapping(self, user_input: dict | None = None) -> Any:
        """Select a mapping to stop providing."""
        return await self._select_mapping("remove_mapping", user_input)

    async def async_step_confirm_remove(self, user_input: dict | None = None) -> Any:
        """Confirm removal without deleting registry entries or history."""
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
        fields = (
            FAN_PATHS
            if self._section == "fans"
            else THERMOSTAT_PATHS
            if self._section == "thermostats"
            else ("id",)
        )
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
        elif self._section == "utilities":
            schema[vol.Required("type", default=values.get("type", "electricity"))] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=list(METER_UNITS),
                        translation_key="meter_type",
                        mode=selector.SelectSelectorMode.DROPDOWN,
                    )
                )
            )
            schema[vol.Required("unit", default=values.get("unit", "default"))] = (
                selector.SelectSelector(
                    selector.SelectSelectorConfig(
                        options=["default", "m³", "L", "Wh", "kWh", "MWh"],
                        translation_key="meter_unit",
                        mode=selector.SelectSelectorMode.DROPDOWN,
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
        if user_input is None:
            return self._mapping_form()
        mapping, errors = _validate_mapping(
            self._section, user_input, self._mappings, self._index
        )
        if errors:
            return self._mapping_form(user_input, errors)
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
        return self._submit_mapping(user_input)

    def _save_mappings(self, mappings: list[dict[str, Any]]) -> Any:
        """Avoid overwriting another options flow editing this same category."""
        if self._entry.options.get(self._section) != self._original_section:
            return self.async_abort(reason="mappings_changed")
        return self._save_options({self._section: mappings})

    def _save_options(self, changes: dict[str, Any]) -> Any:
        """Merge unrelated options and reload even after a failed setup."""
        options = {**self._entry.options, **changes}
        if self._entry.state is not config_entries.ConfigEntryState.LOADED:
            self.hass.config_entries.async_update_entry(self._entry, options=options)
            self.hass.config_entries.async_schedule_reload(self._entry.entry_id)
        return self.async_create_entry(title="", data=options)

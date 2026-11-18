"""Version two imports legacy mappings once without overwriting stored options."""

from __future__ import annotations

from copy import deepcopy
from types import MappingProxyType
from typing import TYPE_CHECKING
from unittest.mock import AsyncMock, MagicMock

import pytest
import yaml
from homeassistant import loader
from homeassistant.config_entries import (
    SOURCE_USER,
    ConfigEntries,
    ConfigEntry,
    ConfigEntryState,
)
from homeassistant.core import HomeAssistant

from custom_components import comfortclick_custom as integration
from custom_components.comfortclick_custom import migration
from custom_components.comfortclick_custom.const import DOMAIN
from custom_components.comfortclick_custom.coordinator import ComfortClickCoordinator
from custom_components.comfortclick_custom.fixed_mappings import import_fixed_mappings
from custom_components.comfortclick_custom.util import (
    load_fans_config,
    load_lock_config,
    load_thermostats_config,
    load_utilities_config,
    load_vent_config,
    read_yaml,
)

if TYPE_CHECKING:
    from pathlib import Path
    from typing import Any


@pytest.fixture
def entry() -> MagicMock:
    item = MagicMock(spec=ConfigEntry)
    item.version = 1
    item.options = {"verify_ssl": True, "unrelated": {"preserve": "yes"}}
    item.data = {
        "host": "http://controller.test",
        "username": "user",
        "password": "private-value",
    }
    return item


@pytest.fixture
def hass() -> MagicMock:
    instance = MagicMock(spec=HomeAssistant)
    instance.config_entries = MagicMock()
    return instance


@pytest.fixture
def legacy() -> dict[str, Any]:
    return {
        "fans": [
            {
                "name": "Fan",
                "fan_id": r" Room\\Fan ",
                "area_id": "bedroom",
                "extra": "unchanged",
            }
        ],
        "thermostats": [
            {
                "name": "AC",
                "heating_id": r" Room\\Heating ",
                "area_id": "",
                "target_temperature_step": 0.25,
            }
        ],
        "locks": [
            {"door_name": "Garage door", "door_id": "garage"},
            {
                "door_name": "Cellar door",
                "door_id": "cellar",
                "unique_id": "saved-cellar-id",
            },
            {"door_name": "Main door", "door_id": r" Main\\Door "},
        ],
        "utilities": [
            {"name": "Heating total", "id": "heat", "type": "heating", "unit": "kWh"},
            {"name": "Hot water", "id": "hot", "type": "water"},
            {"name": "Cold water", "id": "cold", "type": "water"},
            {"name": "Night electricity", "id": "night", "type": "electricity"},
            {"name": "Day electricity", "id": r" Day\\Meter ", "type": "electricity"},
        ],
        "vent": {
            "home_mode": r" Vent\\Home ",
            "away_mode": "away",
            "guest_mode": "guest",
        },
    }


async def test_import_preserves_raw_rows_ids_areas_order_and_credentials(
    hass: MagicMock,
    entry: MagicMock,
    legacy: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    original = deepcopy(legacy)
    saved_data = deepcopy(entry.data)
    read = AsyncMock(return_value=legacy)
    monkeypatch.setattr(migration, "read_yaml", read)

    assert await integration.async_migrate_entry(hass, entry)

    hass.config_entries.async_update_entry.assert_called_once()
    update = hass.config_entries.async_update_entry.call_args
    assert update.args == (entry,)
    assert update.kwargs["version"] == 2
    assert set(update.kwargs) == {"options", "version"}
    options = update.kwargs["options"]
    assert options["verify_ssl"] is True
    assert options["unrelated"] == {"preserve": "yes"}
    for section, (field, prefix) in migration.IDENTITY_FIELDS.items():
        expected = deepcopy(original[section])
        for row in expected:
            row.setdefault("unique_id", prefix + row[field])
        assert options[section] == expected
    assert options["vent"] == original["vent"]
    assert legacy == original
    assert entry.data == saved_data
    read.assert_awaited_once_with()

    # Home Assistant applies this atomic version update before the next load.
    entry.version = 2
    entry.options = options
    read.side_effect = AssertionError("Version two must never consult the old file")
    assert await integration.async_migrate_entry(hass, entry)
    assert read.await_count == 1
    assert hass.config_entries.async_update_entry.call_count == 1


async def test_existing_options_take_precedence_including_explicit_empty_sections(
    hass: MagicMock,
    entry: MagicMock,
    legacy: dict[str, Any],
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    entry.options.update(
        fans=[],
        locks=[],
        vent={},
        utilities=[{"id": "kept", "unique_id": "immutable", "type": "water"}],
    )
    existing = deepcopy(entry.options)
    monkeypatch.setattr(migration, "read_yaml", AsyncMock(return_value=legacy))
    assert await integration.async_migrate_entry(hass, entry)
    options = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    for key, value in existing.items():
        assert options[key] == value
    assert (
        options["thermostats"][0]["unique_id"]
        == "room-1-" + legacy["thermostats"][0]["heating_id"]
    )


async def test_complete_saved_options_migrate_without_opening_legacy_file(
    hass: MagicMock, entry: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry.options.update(migration.empty_mapping_options())
    read = AsyncMock(side_effect=PermissionError)
    monkeypatch.setattr(migration, "read_yaml", read)
    assert await integration.async_migrate_entry(hass, entry)
    read.assert_not_awaited()
    assert (
        hass.config_entries.async_update_entry.call_args.kwargs["options"]
        == entry.options
    )


async def test_blank_legacy_slots_receive_distinct_ids_when_first_configured(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    source = {
        "locks": [
            {"door_name": "Main door", "door_id": ""},
            {"door_name": "Cellar door", "door_id": "   "},
        ],
        "utilities": [{"name": "Cold water", "id": " ", "type": "water"}],
    }
    monkeypatch.setattr(migration, "read_yaml", AsyncMock(return_value=source))
    migrated = await migration.async_import_mapping_options({})
    assert all("unique_id" not in row for row in migrated["locks"])
    assert "unique_id" not in migrated["utilities"][0]
    assert migrated["locks"][1]["door_id"] == "   "

    doors = import_fixed_mappings(migrated, "locks", "entry-one")
    meters = import_fixed_mappings(migrated, "utilities", "entry-one")
    doors[0]["door_id"] = "new-main"
    doors[1]["door_id"] = "new-cellar"
    assert doors[0]["unique_id"] == "entry-one-locks-main"
    assert doors[1]["unique_id"] == "entry-one-locks-cellar"
    assert len({row["unique_id"] for row in meters}) == 5
    assert all(row["unique_id"].startswith("entry-one-utilities-") for row in meters)


async def test_missing_legacy_file_initializes_all_empty_categories(
    hass: MagicMock, entry: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    monkeypatch.setattr(
        read_yaml.aiofiles, "open", MagicMock(side_effect=FileNotFoundError)
    )
    assert await integration.async_migrate_entry(hass, entry)
    options = hass.config_entries.async_update_entry.call_args.kwargs["options"]
    assert options == {**entry.options, **migration.empty_mapping_options()}


@pytest.mark.parametrize(
    "invalid",
    [
        {"fans": {}},
        {"fans": [None]},
        {"fans": [{"name": "Missing identity path"}]},
        {"vent": []},
        {"locks": [{"door_name": "Unrecognized door", "door_id": "private-value"}]},
        {
            "locks": [
                {"door_name": "Main door", "door_id": "one"},
                {"door_name": "Main door", "door_id": "two"},
            ]
        },
        {
            "utilities": [
                {"name": "Unknown meter", "type": "water", "id": "private-value"}
            ]
        },
    ],
)
async def test_invalid_or_ambiguous_legacy_migration_is_atomic(
    hass: MagicMock,
    entry: MagicMock,
    invalid: dict,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    before = deepcopy(entry.options)
    monkeypatch.setattr(migration, "read_yaml", AsyncMock(return_value=invalid))
    assert await integration.async_migrate_entry(hass, entry) is False
    hass.config_entries.async_update_entry.assert_not_called()
    assert entry.version == 1
    assert entry.options == before
    assert "private-value" not in caplog.text
    assert "then retry" in caplog.text


@pytest.mark.parametrize(
    "error", [PermissionError("private-value"), yaml.YAMLError("private-value")]
)
async def test_unreadable_or_malformed_legacy_file_does_not_update_entry(
    hass: MagicMock,
    entry: MagicMock,
    error: Exception,
    monkeypatch: pytest.MonkeyPatch,
    caplog: pytest.LogCaptureFixture,
) -> None:
    monkeypatch.setattr(migration, "read_yaml", AsyncMock(side_effect=error))
    assert await integration.async_migrate_entry(hass, entry) is False
    hass.config_entries.async_update_entry.assert_not_called()
    assert entry.version == 1
    assert "private-value" not in caplog.text


async def test_runtime_loaders_never_read_yaml_even_when_options_are_missing(
    monkeypatch: pytest.MonkeyPatch,
) -> None:
    opened = MagicMock(side_effect=AssertionError("Runtime must not read YAML"))
    monkeypatch.setattr(read_yaml.aiofiles, "open", opened)
    for options in (None, {}, migration.empty_mapping_options()):
        assert await load_fans_config.load_fans_config(options) == []
        assert await load_thermostats_config.load_thermostats_config(options) == []
        assert await load_lock_config.load_lock_config(options) == []
        assert await load_utilities_config.load_utilities_config(options) == []
        assert await load_vent_config.load_vent_config(options) is None
    opened.assert_not_called()


def test_empty_factory_does_not_share_mutable_defaults() -> None:
    first = migration.empty_mapping_options()
    second = migration.empty_mapping_options()
    first["fans"].append({"name": "Example"})
    first["vent"]["home_mode"] = "example"
    assert second == {
        "fans": [],
        "thermostats": [],
        "locks": [],
        "utilities": [],
        "vent": {},
    }


async def test_newer_config_version_is_not_downgraded(
    hass: MagicMock, entry: MagicMock, monkeypatch: pytest.MonkeyPatch
) -> None:
    entry.version = 3
    read = AsyncMock(side_effect=AssertionError("Unsupported entry must not migrate"))
    monkeypatch.setattr(migration, "read_yaml", read)
    assert await integration.async_migrate_entry(hass, entry) is False
    read.assert_not_awaited()
    hass.config_entries.async_update_entry.assert_not_called()


async def test_native_setup_migrates_before_runtime_and_reload_ignores_yaml(
    tmp_path: Path, monkeypatch: pytest.MonkeyPatch
) -> None:
    instance = HomeAssistant(str(tmp_path))
    instance.config_entries = ConfigEntries(instance, {})
    loader.async_setup(instance)
    instance.config.components.add(DOMAIN)
    saved_data = {
        "host": "https://controller.test",
        "username": "user",
        "password": "private-value",
    }
    config_entry = ConfigEntry(
        data=saved_data,
        discovery_keys=MappingProxyType({}),
        domain=DOMAIN,
        minor_version=1,
        options={"verify_ssl": True, "utilities": []},
        source=SOURCE_USER,
        title="Controller",
        unique_id="migration-test",
        version=1,
    )
    source = {"locks": [{"door_name": "Main door", "door_id": " Door\\Main "}]}
    read = AsyncMock(return_value=source)
    monkeypatch.setattr(migration, "read_yaml", read)
    coordinator = MagicMock(spec=ComfortClickCoordinator)
    monkeypatch.setattr(
        integration, "ComfortClickCoordinator", lambda *_args, **_kwargs: coordinator
    )
    snapshots = []

    async def forward(entry: ConfigEntry, _platforms: list) -> None:
        assert entry.version == 2
        mappings = await load_lock_config.load_lock_config(entry.options)
        assert len(mappings) == 1
        assert mappings[0].door_id == " Door\\Main "
        assert mappings[0].unique_id == " Door\\Main "
        snapshots.append(deepcopy(dict(entry.options)))

    monkeypatch.setattr(instance.config_entries, "async_forward_entry_setups", forward)
    monkeypatch.setattr(
        instance.config_entries, "async_unload_platforms", AsyncMock(return_value=True)
    )
    try:
        # async_add invokes the actual ConfigEntries.async_setup lifecycle.
        await instance.config_entries.async_add(config_entry)
        assert config_entry.state is ConfigEntryState.LOADED
        assert config_entry.version == 2
        assert config_entry.data == saved_data
        assert set(migration.empty_mapping_options()) <= config_entry.options.keys()
        assert config_entry.options["utilities"] == []
        read.assert_awaited_once_with()
        assert len(snapshots) == 1

        read.side_effect = AssertionError("Reload must never consult the old file")
        assert await instance.config_entries.async_reload(config_entry.entry_id)
        assert config_entry.state is ConfigEntryState.LOADED
        assert snapshots == [snapshots[0], snapshots[0]]
        read.assert_awaited_once_with()
        assert coordinator.async_config_entry_first_refresh.await_count == 2
        assert await instance.config_entries.async_unload(config_entry.entry_id)
        assert coordinator.async_shutdown.await_count == 2
    finally:
        await instance.async_stop(force=True)

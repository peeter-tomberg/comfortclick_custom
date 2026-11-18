"""Register the administrator configuration page and its two public assets."""

from __future__ import annotations

import asyncio
from dataclasses import dataclass, field
from pathlib import Path
from typing import TYPE_CHECKING

from homeassistant.components.http import StaticPathConfig
from homeassistant.components.panel_custom import async_register_panel

from .const import DOMAIN

if TYPE_CHECKING:
    from homeassistant.core import HomeAssistant

PANEL_URL = "comfortclick-config"
ASSET_URL = f"/{DOMAIN}"
DATA_PANEL = f"{DOMAIN}_configuration_panel"


@dataclass
class PanelRegistration:
    """Keep concurrent setup and integration reloads from registering twice."""

    lock: asyncio.Lock = field(default_factory=asyncio.Lock)
    assets_registered: bool = False
    panel_registered: bool = False


async def async_register_configuration_panel(hass: HomeAssistant) -> None:
    """Expose no integration files besides the editor and public labels."""
    state = hass.data.setdefault(DATA_PANEL, PanelRegistration())
    async with state.lock:
        if state.panel_registered:
            return
        if not state.assets_registered:
            source = Path(__file__).parent
            await hass.http.async_register_static_paths(
                [
                    StaticPathConfig(
                        f"{ASSET_URL}/configuration.js",
                        str(source / "frontend" / "configuration.js"),
                        cache_headers=False,
                    ),
                    StaticPathConfig(
                        f"{ASSET_URL}/strings.json",
                        str(source / "strings.json"),
                        cache_headers=False,
                    ),
                ]
            )
            state.assets_registered = True
        await async_register_panel(
            hass,
            frontend_url_path=PANEL_URL,
            webcomponent_name="comfortclick-configuration",
            sidebar_title="ComfortClick",
            sidebar_icon="mdi:tune-variant",
            module_url=f"{ASSET_URL}/configuration.js",
            config={"strings_url": f"{ASSET_URL}/strings.json"},
            require_admin=True,
        )
        state.panel_registered = True

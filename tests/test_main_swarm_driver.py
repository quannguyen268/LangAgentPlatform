import pytest
from unittest.mock import MagicMock, AsyncMock
from src.main import _run_swarm_driver_once


@pytest.mark.asyncio
async def test_run_swarm_driver_once_calls_tick():
    driver = MagicMock()
    driver.tick = AsyncMock()
    await _run_swarm_driver_once(driver)
    driver.tick.assert_awaited_once()


@pytest.mark.asyncio
async def test_run_swarm_driver_once_swallows_errors():
    driver = MagicMock()
    driver.tick = AsyncMock(side_effect=RuntimeError("boom"))
    # Must NOT raise — a driver error must not kill the loop.
    await _run_swarm_driver_once(driver)

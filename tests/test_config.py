"""The three mandatory storage settings must be present and non blank."""

from __future__ import annotations

import os

import pytest

from app.config import (
    ENV_ACCESS_KEY_ID,
    ENV_BUCKET,
    ENV_ENDPOINT,
    ENV_SECRET_KEY,
    Settings,
    load_settings,
)
from app.errors import ConfigurationError

BASE_ENV = {
    ENV_ENDPOINT: "http://127.0.0.1:9000",
    ENV_BUCKET: "contract-bucket",
    ENV_SECRET_KEY: "super-secret",
}


@pytest.mark.parametrize(
    "missing",
    [ENV_ENDPOINT, ENV_BUCKET, ENV_SECRET_KEY],
)
def test_missing_mandatory_setting_fails_at_startup(missing):
    """A missing endpoint / bucket / secret key stops the application."""
    env = {key: value for key, value in BASE_ENV.items() if key != missing}
    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env)
    assert missing in str(excinfo.value)


@pytest.mark.parametrize(
    "blank",
    [ENV_ENDPOINT, ENV_BUCKET, ENV_SECRET_KEY],
)
def test_blank_mandatory_setting_fails_at_startup(blank):
    """An EMPTY STRING is rejected exactly like a missing variable."""
    env = dict(BASE_ENV)
    env[blank] = "   "
    with pytest.raises(ConfigurationError) as excinfo:
        load_settings(env)
    assert blank in str(excinfo.value)
    assert "blank" in str(excinfo.value)


def test_valid_configuration_is_accepted():
    """A complete configuration loads."""
    settings = load_settings(BASE_ENV)
    assert settings.endpoint == "http://127.0.0.1:9000"
    assert settings.bucket == "contract-bucket"
    assert settings.secret_key == "super-secret"
    assert settings.max_file_size == 20 * 1024 * 1024
    assert settings.presign_ttl_seconds == 300


def test_startup_raises_when_environment_is_empty(monkeypatch):
    """Building the application without any configuration fails."""
    for name in (ENV_ENDPOINT, ENV_BUCKET, ENV_SECRET_KEY, ENV_ACCESS_KEY_ID):
        monkeypatch.delenv(name, raising=False)
    with pytest.raises(ConfigurationError):
        Settings.from_env({})

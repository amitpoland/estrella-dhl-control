"""settings_factory.py — the single test-side authority for building settings.

Why this file exists
--------------------
``app.core.config.Settings`` owns the application settings contract. Before this
module, 226 test files substituted that contract with their own object: a local
``class S``, a ``SimpleNamespace``, or a bare ``MagicMock``. Each copy declared
only the handful of fields its own service happened to read, and nothing checked
any copy against the real model.

That is contract drift, and it fails in the worst possible way — late, and
somewhere else. When ``302848fa`` added the Lesson E environment-isolation guard
to ``email_sender`` and it began reading ``settings.environment``, the local stub
in ``test_email_sender.py`` did not fail at construction. It failed seven tests
later with ``AttributeError: 'S' object has no attribute 'environment'``, thrown
from inside production code, before any assertion ran.

A ``MagicMock`` hides the same defect even more thoroughly: it manufactures any
attribute on demand, so a missing field never raises at all. The guard above
would have silently compared a ``Mock`` against ``"prod"``, taken the wrong
branch, and reported a green test. An unrestricted mock cannot be the authority
for a contract.

What this factory guarantees
----------------------------
1. It returns a **real, fully validated** ``Settings`` instance, so every field
   is the production field with the production type and the production default.
2. It never reads ``.env`` (``_env_file=None``), so no production secret can
   reach a test process.
3. It pins the fields that govern outbound email so a stray ``SMTP_USER`` in a
   developer's environment cannot flip a test onto the real send path.
4. It rejects unknown override names loudly. ``Settings`` is configured with
   ``extra="ignore"``, so ``Settings(no_such_field=1)`` silently swallows the
   typo; this factory raises ``UnknownSettingError`` instead.
5. It defaults to a **non-production** environment. Tests that intentionally
   exercise the permitted SMTP send path must opt in with
   ``environment="prod"`` at the call site, which keeps that decision visible
   in the test that makes it rather than hidden in a shared helper.

Note on ``environment``
-----------------------
The obvious default would be ``environment="test"``, but the production contract
is ``Literal["dev", "prod"]`` (``app/core/config.py``) and rejects anything else
with a ``ValidationError``. Tests consume the real contract rather than widening
it, so the safe non-production default here is ``"dev"`` — which is also the
production default and is exactly what the environment guard treats as
"refuse to send".
"""
from __future__ import annotations

from pathlib import Path
from typing import Any

from app.core.config import Settings

__all__ = ["make_test_settings", "UnknownSettingError"]


class UnknownSettingError(AttributeError):
    """A test asked to override a field the real Settings contract does not have.

    Raised instead of letting ``extra="ignore"`` swallow the name, which would
    leave the test asserting against a default it did not choose.
    """


def make_test_settings(tmp_path: Path, **overrides: Any) -> Settings:
    """Build a real ``Settings`` for tests, isolated from host and production.

    Args:
        tmp_path: pytest ``tmp_path``; becomes ``storage_root`` so nothing is
            written outside the test sandbox.
        **overrides: any real ``Settings`` field. Unknown names raise
            ``UnknownSettingError``.

    Returns:
        A validated ``Settings`` instance.

    Raises:
        UnknownSettingError: an override names a field that does not exist.
        pydantic.ValidationError: an override value violates the real contract.
    """
    unknown = sorted(set(overrides) - set(Settings.model_fields))
    if unknown:
        raise UnknownSettingError(
            f"unknown Settings field(s): {', '.join(unknown)}. "
            "Tests consume app.core.config.Settings; they do not extend it. "
            "If the field is new, add it to Settings first."
        )

    values: dict[str, Any] = {
        # Non-production by default — see the module docstring. Send-path tests
        # opt into "prod" explicitly.
        "environment":   "dev",
        "storage_root":  Path(tmp_path),
        # Pinned so a host/CI environment variable can never make
        # _smtp_configured() true behind a test's back.
        "smtp_user":     None,
        "smtp_password": None,
    }
    values.update(overrides)

    # _env_file=None: never read the production .env, on any host.
    return Settings(_env_file=None, **values)

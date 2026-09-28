"""The credential catalogue writes ``.env`` without eating what is already there.

This file is an editing surface for a user's own secrets, reached over HTTP from
a web page. The properties worth pinning are about damage, not features: an
unrelated key must survive, a comment must survive, a cleared field must
actually unset rather than leave ``KEY=`` behind for ``os.getenv`` to return as
empty-but-present, and a secret must never round-trip its plaintext.
"""

import pytest

from asv.core import credentials as creds

pytestmark = pytest.mark.unit


def _env(tmp_path, body: str):
    path = tmp_path / ".env"
    path.write_text(body, encoding="utf-8")
    return path


def test_updates_in_place_and_preserves_everything_else(tmp_path):
    path = _env(tmp_path, "\n".join([
        "# my notes",
        "GEMINI_API_KEY=old-key",
        "",
        "SOME_UNRELATED_VAR=keep-me",
    ]) + "\n")

    creds.write_env_values({"GEMINI_API_KEY": "new-key"}, path)

    values = creds.read_env_file(path)
    assert values["GEMINI_API_KEY"] == "new-key"
    assert values["SOME_UNRELATED_VAR"] == "keep-me"
    assert "# my notes" in path.read_text(encoding="utf-8")


def test_new_keys_are_appended(tmp_path):
    path = _env(tmp_path, "GEMINI_API_KEY=k\n")

    creds.write_env_values({"UNPAYWALL_EMAIL": "a@b.edu", "CORE_API_KEY": "c"}, path)

    values = creds.read_env_file(path)
    assert values["UNPAYWALL_EMAIL"] == "a@b.edu"
    assert values["CORE_API_KEY"] == "c"
    assert values["GEMINI_API_KEY"] == "k"


def test_clearing_a_field_removes_the_line(tmp_path):
    """``KEY=`` would read back as present-but-empty and silently disable the
    feature the user was trying to re-enable."""
    path = _env(tmp_path, "GEMINI_API_KEY=k\nCORE_API_KEY=c\n")

    creds.write_env_values({"CORE_API_KEY": ""}, path)

    assert "CORE_API_KEY" not in creds.read_env_file(path)
    assert creds.read_env_file(path)["GEMINI_API_KEY"] == "k"


def test_values_with_spaces_and_hashes_survive_a_round_trip(tmp_path):
    path = _env(tmp_path, "")
    tricky = '{"www.nature.com": {"sid": "a b#c"}}'

    creds.write_env_values({"INSTITUTIONAL_COOKIES": tricky}, path)

    assert creds.read_env_file(path)["INSTITUTIONAL_COOKIES"] == tricky


def test_writing_is_idempotent(tmp_path):
    path = _env(tmp_path, "GEMINI_API_KEY=k\n")

    creds.write_env_values({"UNPAYWALL_EMAIL": "a@b.edu"}, path)
    first = path.read_text(encoding="utf-8")
    creds.write_env_values({"UNPAYWALL_EMAIL": "a@b.edu"}, path)

    assert path.read_text(encoding="utf-8") == first


def test_mask_never_reveals_a_usable_secret():
    assert creds.mask("") == ""
    assert "secret" not in creds.mask("supersecretvalue")
    assert creds.mask("supersecretvalue").endswith("alue")
    # Short values reveal nothing at all rather than most of themselves.
    assert creds.mask("abc123") == "••••••"


def test_every_spec_has_a_group_the_ui_knows_how_to_render():
    for spec in creds.CREDENTIAL_SPECS:
        assert spec.group in creds.GROUP_ORDER
        assert spec.help, f"{spec.name} needs help text"


def test_auth_headers_are_keyed_on_host_not_on_resolver(monkeypatch):
    monkeypatch.setenv("WILEY_TDM_TOKEN", "tok")
    monkeypatch.setenv("ELSEVIER_API_KEY", "els")

    wiley = creds.auth_headers_for("https://api.wiley.com/onlinelibrary/tdm/v1/articles/10.1/2")
    assert wiley == {"Wiley-TDM-Client-Token": "tok"}

    els = creds.auth_headers_for("https://api.elsevier.com/content/article/doi/10.1/2")
    assert els["X-ELS-APIKey"] == "els"

    # An unrelated publisher must not receive either token.
    assert creds.auth_headers_for("https://www.nature.com/articles/x") == {}


def test_no_token_means_no_header(monkeypatch):
    monkeypatch.delenv("WILEY_TDM_TOKEN", raising=False)
    assert creds.auth_headers_for("https://api.wiley.com/x") == {}


def test_repeated_appends_do_not_stack_headers(tmp_path):
    path = _env(tmp_path, "GEMINI_API_KEY=k\n")

    creds.write_env_values({"EZPROXY_HOST": "proxy.example.edu"}, path)
    creds.write_env_values({"UNPAYWALL_EMAIL": "a@b.edu"}, path)

    body = path.read_text(encoding="utf-8")
    assert body.count("# Added via the ASV config page") == 1
    values = creds.read_env_file(path)
    assert values["EZPROXY_HOST"] == "proxy.example.edu"
    assert values["UNPAYWALL_EMAIL"] == "a@b.edu"

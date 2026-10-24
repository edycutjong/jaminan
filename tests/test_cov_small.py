"""Offline coverage for config, gate, tariff, rules helpers and the PayPal transport (respx, no network)."""
import io

import httpx
import numpy as np
import pytest
import respx
from PIL import Image

from jaminan import config, gate, paypal, rules, tariff

BASE = "https://api-m.sandbox.paypal.com"


# --- config -----------------------------------------------------------------------------------
def test_local_env_skips_blank_comment_and_malformed_lines_and_never_overrides(tmp_path, monkeypatch):
    f = tmp_path / "x.env"
    f.write_text('\n# comment\nnot-a-pair\nJAM_A="quoted"\nJAM_B=\'single\'\nJAM_SET=file\n')
    monkeypatch.setattr(config, "LOCAL_ENV_FILES", {"x": str(f), "gone": str(tmp_path / "missing.env")})
    monkeypatch.setenv("JAM_SET", "kept")
    for k in ("JAM_A", "JAM_B"):
        monkeypatch.delenv(k, raising=False)
    config.load_local_env()
    import os
    assert os.environ["JAM_A"] == "quoted" and os.environ["JAM_B"] == "single" and os.environ["JAM_SET"] == "kept"
    for k in ("JAM_A", "JAM_B"):
        os.environ.pop(k, None)


def test_settings_refuse_a_non_sandbox_paypal_base(monkeypatch):
    monkeypatch.setenv("PAYPAL_API_BASE", "https://api-m.paypal.com")
    with pytest.raises(RuntimeError, match="sandbox only"):
        config.settings()
    monkeypatch.setenv("PAYPAL_API_BASE", "https://api-m.sandbox.paypal.com/")
    assert config.settings().paypal_base == "https://api-m.sandbox.paypal.com"


# --- gate -------------------------------------------------------------------------------------
def test_an_extreme_aspect_ratio_is_not_a_scooter_photo():
    buf = io.BytesIO()
    Image.fromarray(np.zeros((10, 1000, 3), dtype=np.uint8)).save(buf, "PNG")
    with pytest.raises(gate.NotAnImage, match="not a readable image"):
        gate.normalize(buf.getvalue())


# --- tariff -----------------------------------------------------------------------------------
def test_an_unknown_damage_class_in_a_tariff_file_is_refused(tmp_path, monkeypatch):
    (tmp_path / "tariff_v9.meta.json").write_text((tariff.FIXTURES / "tariff_v1.meta.json").read_text())
    (tmp_path / "fine_ceiling_v9.csv").write_text((tariff.FIXTURES / "fine_ceiling_v1.csv").read_text())
    (tmp_path / "tariff_v9.csv").write_text("part,damage_class,price_cents\nmirror_housing,melted,100\n")
    monkeypatch.setattr(tariff, "FIXTURES", tmp_path)
    with pytest.raises(ValueError, match="unknown damage class melted"):
        tariff.load("tv9")


# --- rules ------------------------------------------------------------------------------------
@pytest.mark.parametrize("ts,expected_none", [(None, True), ("", True), ("not-a-date", True),
                                               ("2026-10-24T10:00:00", True)])
def test_aware_refuses_missing_garbled_and_offsetless_timestamps(ts, expected_none):
    assert (rules._aware(ts) is None) is expected_none


def test_aware_parses_z_and_offset_timestamps():
    assert rules._aware("2026-10-24T10:00:00Z").utcoffset().total_seconds() == 0
    assert rules._aware("2026-10-24T10:00:00+07:00").utcoffset().total_seconds() == 7 * 3600


# --- paypal transport -------------------------------------------------------------------------
def test_cents_rounds_strings_and_floats():
    assert paypal.cents("12.34") == 1234 and paypal.cents(0.29) == 29


def test_the_client_refuses_a_live_base_url():
    with pytest.raises(RuntimeError, match="non-sandbox"):
        paypal.PayPal("https://api-m.paypal.com", "id", "secret")


@respx.mock
def test_token_is_fetched_with_basic_auth_then_cached():
    route = respx.post(f"{BASE}/v1/oauth2/token").mock(
        return_value=httpx.Response(200, json={"access_token": "tok", "expires_in": 3000}))
    p = paypal.PayPal(BASE, "cid", "sec")
    assert p.token() == "tok" and p.token() == "tok"
    assert route.call_count == 1
    assert route.calls[0].request.headers["Authorization"].startswith("Basic ")


@respx.mock
def test_transport_error_surfaces_as_599_and_non_json_body_is_kept_raw(monkeypatch):
    monkeypatch.setattr(paypal.time, "sleep", lambda s: None)
    respx.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "t"}))
    respx.get(f"{BASE}/v2/invoicing/invoices/INV-1").mock(side_effect=httpx.ConnectError("down"))
    p = paypal.PayPal(BASE, "cid", "sec")
    r = p.get_invoice("INV-1")
    assert r.status == 599 and r.body["name"] == "TRANSPORT_ERROR"
    respx.get(f"{BASE}/v1/notifications/webhooks").mock(return_value=httpx.Response(200, content=b"--multipart--"))
    raw = p.list_webhooks()
    assert raw.body == {"raw": "--multipart--"}


@respx.mock
def test_vault_get_invoice_and_webhook_endpoints_hit_their_documented_paths():
    respx.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "t"}))
    got = respx.get(f"{BASE}/v3/vault/payment-tokens/PT1").mock(return_value=httpx.Response(200, json={"id": "PT1"}))
    inv = respx.get(f"{BASE}/v2/invoicing/invoices/I1").mock(return_value=httpx.Response(200, json={"id": "I1"}))
    wh = respx.post(f"{BASE}/v1/notifications/webhooks").mock(return_value=httpx.Response(201, json={"id": "W1"}))
    p = paypal.PayPal(BASE, "cid", "sec")
    assert p.get_payment_token("PT1").body["id"] == "PT1" and got.called
    assert p.get_invoice("I1").body["id"] == "I1" and inv.called
    assert p.create_webhook("https://x.example/hook", ["PAYMENT.CAPTURE.COMPLETED"]).ok
    assert b"PAYMENT.CAPTURE.COMPLETED" in wh.calls[0].request.content


@respx.mock
def test_an_invoice_without_a_payer_email_has_no_recipients():
    respx.post(f"{BASE}/v1/oauth2/token").mock(return_value=httpx.Response(200, json={"access_token": "t"}))
    route = respx.post(f"{BASE}/v2/invoicing/invoices").mock(return_value=httpx.Response(201, json={"id": "I"}))
    paypal.PayPal(BASE, "cid", "sec").create_invoice("R-1", "JAM-1", None, [], "note")
    assert b"primary_recipients" not in route.calls[0].request.content


def test_from_settings_builds_a_client_from_the_settings_object():
    s = config.Settings(paypal_client_id="cid", paypal_client_secret="sec")
    seen = []
    p = paypal.from_settings(s, on_call=seen.append)
    assert p.client_id == "cid" and p.on_call == seen.append


def test_a_source_over_the_pixel_cap_is_refused_from_the_header(monkeypatch):
    buf = io.BytesIO()
    Image.fromarray(np.zeros((40, 40, 3), dtype=np.uint8)).save(buf, "PNG")
    monkeypatch.setattr(gate, "MAX_SOURCE_PIXELS", 1000)
    with pytest.raises(gate.NotAnImage, match="not a readable image"):
        gate.normalize(buf.getvalue())

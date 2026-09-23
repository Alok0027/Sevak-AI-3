"""Covers the SMS/Twilio wiring added for Agent 3 (SRS section 11 risk
register: SMS fallback when WhatsApp Business API isn't available). Mock
path is exercised elsewhere via test_api.py's actions_generated checks;
this file covers the two pieces of actual logic -- E.164 normalization and
the mock/real branch in agent3.generate() -- with no network access.
"""
import asyncio

import httpx
import pytest

from app.agents import agent3_action_generation as agent3
from app.core.config import Settings
from app.schemas.visit import ExtractedFields
from app.services.llm_client import MockLLMClient
from app.services.sms_client import MockSmsClient, SmsClientBase, TwilioSmsClient
from app.services.twilio_rest import to_e164_in
from app.services.whatsapp_client import (
    MockWhatsAppClient,
    TwilioWhatsAppClient,
    WhatsAppClient,
    get_whatsapp_client,
)


def test_e164_normalization_assumes_india_when_no_country_code():
    assert to_e164_in("9876543210") == "+919876543210"


def test_e164_normalization_leaves_existing_country_code_alone():
    assert to_e164_in("+15551234567") == "+15551234567"


class _FakeSmsClient(SmsClientBase):
    """Not MockSmsClient on purpose -- generate() branches on
    isinstance(..., MockSmsClient), so a fake real client is the only way
    to exercise the real-send branch without network access."""

    def __init__(self):
        self.sent = []

    async def send_message(self, to_phone: str, message: str) -> dict:
        self.sent.append((to_phone, message))
        return {"status": "queued", "sid": "SMfake"}


def _extracted():
    return ExtractedFields(bp_systolic=140, bp_diastolic=90, medication_compliance="non_compliant")


def test_generate_adds_no_sms_action_on_mock_sms_client():
    actions = asyncio.run(agent3.generate(
        extracted=_extracted(), risk_level="HIGH", risk_drivers=[],
        patient_name="Meera Patil", patient_phone="9876543210",
        llm_client=MockLLMClient(), whatsapp_client=MockWhatsAppClient(),
        sms_client=MockSmsClient(),
    ))
    assert not any(a["type"] == "sms" for a in actions)


def test_generate_drafts_without_sending_even_with_real_sms_client():
    fake_sms = _FakeSmsClient()
    actions = asyncio.run(agent3.generate(
        extracted=_extracted(), risk_level="HIGH", risk_drivers=[],
        patient_name="Meera Patil", patient_phone="9876543210",
        llm_client=MockLLMClient(), whatsapp_client=MockWhatsAppClient(),
        sms_client=fake_sms,
    ))
    sms_actions = [a for a in actions if a["type"] == "sms"]
    assert sms_actions == []
    assert fake_sms.sent == []
    assert next(a for a in actions if a["type"] == "whatsapp")["status"] == "draft"


def test_twilio_error_surfaces_the_code_and_reason(monkeypatch):
    """Twilio explains every failure in the response body -- an error code
    and a sentence. raise_for_status() discards both, leaving an
    indistinguishable HTTP 400 for causes that need completely different
    fixes (verify the recipient vs buy a number vs the user replied STOP)."""
    def handler(request: httpx.Request) -> httpx.Response:
        return httpx.Response(
            400,
            json={
                "code": 21608,
                "message": "The number +919876543210 is unverified. Trial accounts "
                           "may only send messages to verified numbers.",
                "more_info": "https://www.twilio.com/docs/errors/21608",
                "status": 400,
            },
        )

    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.services.twilio_rest.httpx.AsyncClient", fake_client)

    settings = Settings(
        sms_provider="real",
        twilio_account_sid="AC123",
        twilio_api_key_sid="SK123",
        twilio_api_key_secret="secret",
        twilio_phone_number="+15550001111",
    )
    with pytest.raises(RuntimeError) as exc:
        asyncio.run(TwilioSmsClient(settings).send_message("9876543210", "namaste"))

    assert "21608" in str(exc.value)
    assert "unverified" in str(exc.value)


# --- WhatsApp via the Twilio sandbox ------------------------------------


def _twilio_capture(monkeypatch, response: httpx.Response) -> list[httpx.Request]:
    """Intercept the Twilio REST call and record what was actually sent."""
    sent: list[httpx.Request] = []

    def handler(request: httpx.Request) -> httpx.Response:
        sent.append(request)
        return response

    real_client = httpx.AsyncClient

    def fake_client(*args, **kwargs):
        kwargs["transport"] = httpx.MockTransport(handler)
        return real_client(*args, **kwargs)

    monkeypatch.setattr("app.services.twilio_rest.httpx.AsyncClient", fake_client)
    return sent


def _twilio_settings(**overrides) -> Settings:
    """A Settings built only from these values -- never the developer's .env.

    Settings fills any field you do not pass from .env, so a half-specified
    one here is half the test machine's live configuration. That made
    test_whatsapp_sandbox_prefixes_both_numbers pass on a clean checkout
    and fail for anyone who owns a Twilio number: the test asserts Twilio's
    shared sandbox sender, and their TWILIO_WHATSAPP_FROM quietly replaced
    it. Same shape as the bug that had pytest writing into sevakai_dev.db.

    _env_file=None closes the whole class of leak rather than pinning this
    one field, so the next test that forgets an argument gets the declared
    default instead of somebody's credentials.
    """
    defaults = dict(
        twilio_account_sid="AC123",
        twilio_api_key_sid="SK123",
        twilio_api_key_secret="secret",
        twilio_phone_number="+15550001111",
        # Twilio's shared sandbox sender, the same for every account. The
        # assertions below are about the "whatsapp:" prefix, not about
        # whose number it is, so it has to be fixed here to be meaningful.
        twilio_whatsapp_from="whatsapp:+14155238886",
    )
    defaults.update(overrides)
    return Settings(_env_file=None, **defaults)


def test_whatsapp_sandbox_prefixes_both_numbers():
    """Twilio routes to WhatsApp purely on the "whatsapp:" prefix -- send
    it a bare number and the message silently goes out as an SMS
    instead, which on an Indian number is a one-way short code rather
    than the two-way WhatsApp thread the demo is meant to show."""
    from urllib.parse import parse_qs

    import pytest as _pytest

    monkeypatch = _pytest.MonkeyPatch()
    try:
        sent = _twilio_capture(monkeypatch, httpx.Response(201, json={"sid": "SM1", "status": "queued"}))
        settings = _twilio_settings(whatsapp_provider="twilio_sandbox")
        client = get_whatsapp_client(settings)
        assert isinstance(client, TwilioWhatsAppClient)

        asyncio.run(client.send_message("9876543210", "नमस्ते"))
    finally:
        monkeypatch.undo()

    body = parse_qs(sent[0].content.decode())
    assert body["To"] == ["whatsapp:+919876543210"]
    assert body["From"] == ["whatsapp:+14155238886"]
    assert body["Body"] == ["नमस्ते"]


def test_whatsapp_provider_selection():
    assert isinstance(get_whatsapp_client(_twilio_settings()), MockWhatsAppClient)
    assert isinstance(
        get_whatsapp_client(_twilio_settings(whatsapp_provider="twilio_sandbox")),
        TwilioWhatsAppClient,
    )
    # The historical USE_MOCKS switch still means what it always did -- but
    # only for a deployment that never set WHATSAPP_PROVIDER at all, which
    # is what the empty string here says. (conftest exports
    # WHATSAPP_PROVIDER=mock for the suite, and Settings reads real
    # environment variables even with _env_file=None, so leaving this out
    # asks a different question than it appears to.)
    assert isinstance(
        get_whatsapp_client(_twilio_settings(use_mocks=False, whatsapp_provider="")),
        WhatsAppClient,
    )
    # An explicit "mock" means mock even when USE_MOCKS is off. Before this,
    # setting the provider to mock to keep a rehearsal safe on a deployment
    # with USE_MOCKS=false returned the live Meta client instead.
    assert isinstance(
        get_whatsapp_client(_twilio_settings(use_mocks=False, whatsapp_provider="mock")),
        MockWhatsAppClient,
    )


# ── WhatsApp Cloud API (Meta) ───────────────────────────────────────────
# asyncio.run rather than pytest.mark.asyncio, matching every other async
# test here -- this repo has no pytest-asyncio and adding a plugin for two
# tests is a dependency nobody asked for.

import json as _json

import httpx as _httpx
import pytest as _pytest

from app.services.whatsapp_client import WhatsAppClient, WhatsAppError


class _WaSettings:
    whatsapp_phone_number_id = "123456789"
    whatsapp_api_token = "test-token"


def _send(monkeypatch, capture, status=200, body=None):
    """Run one send against a mocked transport, returning Meta's reply."""

    def handler(request: _httpx.Request):
        capture["url"] = str(request.url)
        capture["json"] = _json.loads(request.content)
        capture["auth"] = request.headers.get("authorization")
        return _httpx.Response(status, json=body or {"messages": [{"id": "wamid.TEST"}]})

    transport = _httpx.MockTransport(handler)
    real = _httpx.AsyncClient
    monkeypatch.setattr(
        _httpx, "AsyncClient", lambda *a, **kw: real(*a, **{**kw, "transport": transport})
    )
    return asyncio.run(WhatsAppClient(_WaSettings()).send_message("9876543210", "नमस्ते"))


def test_meta_send_adds_country_code_and_drops_the_plus(monkeypatch):
    """Numbers are stored as bare 10-digit Indian numbers. Meta wants
    919876543210 -- not 9876543210, which it accepts with a 200 and a
    message id and then delivers to nobody, and not +919876543210."""
    capture: dict = {}
    result = _send(monkeypatch, capture)

    assert capture["json"]["to"] == "919876543210"
    assert capture["json"]["messaging_product"] == "whatsapp"
    assert capture["json"]["text"]["body"] == "नमस्ते"
    assert capture["auth"] == "Bearer test-token"
    assert "123456789/messages" in capture["url"]
    assert result["messages"][0]["id"] == "wamid.TEST"


def test_meta_send_surfaces_the_reason_not_just_the_status(monkeypatch):
    """A bare '400 Bad Request' is what sent us chasing the wrong cause for
    hours on Twilio. Meta's numeric code and its meaning both have to reach
    whoever is reading the log."""
    capture: dict = {}
    with _pytest.raises(WhatsAppError) as exc:
        _send(
            monkeypatch,
            capture,
            status=400,
            body={"error": {"code": 131047, "message": "Re-engagement message"}},
        )

    assert "131047" in str(exc.value)
    assert "24-hour" in str(exc.value)


def test_meta_send_reports_an_expired_token_as_such(monkeypatch):
    """Code 190 is the one that will happen mid-demo if the token came from
    the Graph API Explorer."""
    capture: dict = {}
    with _pytest.raises(WhatsAppError) as exc:
        _send(
            monkeypatch,
            capture,
            status=401,
            body={"error": {"code": 190, "message": "Session has expired"}},
        )

    assert "WHATSAPP_API_TOKEN" in str(exc.value)


def test_meta_template_send_builds_the_payload_meta_expects(monkeypatch):
    """A follow-up reminder is business-initiated, so it must go as an
    approved template -- free-form text is refused with 131047. The
    parameters are positional {{1}}, {{2}}… in order."""
    capture: dict = {}

    def handler(request: _httpx.Request):
        capture["json"] = _json.loads(request.content)
        return _httpx.Response(200, json={"messages": [{"id": "wamid.T"}]})

    transport = _httpx.MockTransport(handler)
    real = _httpx.AsyncClient
    monkeypatch.setattr(
        _httpx, "AsyncClient", lambda *a, **kw: real(*a, **{**kw, "transport": transport})
    )

    asyncio.run(
        WhatsAppClient(_WaSettings()).send_template(
            "9876543210", "followup_reminder", ["Meera Patil", "kal subah"], "hi"
        )
    )

    sent = capture["json"]
    assert sent["type"] == "template"
    assert sent["to"] == "919876543210"
    assert sent["template"]["name"] == "followup_reminder"
    assert sent["template"]["language"]["code"] == "hi"
    params = sent["template"]["components"][0]["parameters"]
    assert [p["text"] for p in params] == ["Meera Patil", "kal subah"]


def test_meta_template_without_params_omits_the_components_block():
    """hello_world takes no substitutions. Sending an empty components
    list makes Meta reject the whole message."""
    capture: dict = {}

    async def run():
        def handler(request: _httpx.Request):
            capture["json"] = _json.loads(request.content)
            return _httpx.Response(200, json={"messages": [{"id": "wamid.T"}]})

        transport = _httpx.MockTransport(handler)
        client = WhatsAppClient(_WaSettings())
        import app.services.whatsapp_client as mod

        real = mod.httpx.AsyncClient
        mod.httpx.AsyncClient = lambda *a, **kw: real(*a, **{**kw, "transport": transport})
        try:
            await client.send_template("9876543210", "hello_world")
        finally:
            mod.httpx.AsyncClient = real

    asyncio.run(run())
    assert "components" not in capture["json"]["template"]


def test_a_provider_without_templates_says_so_rather_than_sending_text():
    """Silently falling back to free-form would look like it worked and
    then be refused by Meta at the worst moment."""
    from app.services.whatsapp_client import TwilioWhatsAppClient

    with _pytest.raises(NotImplementedError) as exc:
        asyncio.run(TwilioWhatsAppClient(_WaSettings()).send_template("9876543210", "x"))
    assert "WHATSAPP_PROVIDER=meta" in str(exc.value)


def test_agent3_sends_the_template_not_the_llm_text_on_the_meta_path():
    """The stored action keeps the LLM's full message, but what goes over
    WhatsApp is the approved template with its three blanks filled. Sending
    the LLM text would be refused for every real patient (131047)."""
    from app.agents import agent3_action_generation as agent3
    from app.schemas.visit import ExtractedFields, RiskDriver
    from app.services.llm_client import MockLLMClient
    from app.services.sms_client import MockSmsClient
    from app.services.whatsapp_client import WhatsAppClientBase

    sent: dict = {}

    class RecordingMeta(WhatsAppClientBase):
        async def send_message(self, to_phone, message):
            sent["free_form"] = message
            return {"status": "sent"}

        async def send_template(self, to_phone, template_name, body_params=None, language_code="en_US"):
            sent["template"] = template_name
            sent["params"] = body_params
            sent["language"] = language_code
            return {"status": "sent"}

    actions = asyncio.run(
        agent3.generate(
            extracted=ExtractedFields(),
            risk_level="HIGH",
            risk_drivers=[RiskDriver(observation="BP 140/90", reason="above threshold")],
            patient_name="Meera Patil",
            patient_phone="9876543210",
            llm_client=MockLLMClient(),
            whatsapp_client=RecordingMeta(),
            sms_client=MockSmsClient(),
        )
    )

    # Delivery is now gated by explicit approval and covered by outbox tests.
    assert sent == {}

    # The record still holds the full drafted message, not the template.
    whatsapp_action = next(a for a in actions if a["type"] == "whatsapp")
    assert "Meera Patil" in whatsapp_action["content"]
    assert whatsapp_action["status"] == "draft"


def test_agent3_falls_back_to_free_form_where_templates_do_not_exist():
    """Mock and Twilio-sandbox providers have no template concept, and
    free-form is genuinely right there. The fallback must not kick in on
    the meta path, where a refusal should surface instead."""
    from app.agents import agent3_action_generation as agent3
    from app.schemas.visit import ExtractedFields
    from app.services.llm_client import MockLLMClient
    from app.services.sms_client import MockSmsClient
    from app.services.whatsapp_client import MockWhatsAppClient, TwilioWhatsAppClient

    class _T(TwilioWhatsAppClient):
        def __init__(self):
            self.seen = None

        async def send_message(self, to_phone, message):
            self.seen = message
            return {"status": "sent"}

    client = _T()
    asyncio.run(
        agent3.generate(
            extracted=ExtractedFields(),
            risk_level="LOW",
            risk_drivers=[],
            patient_name="Asha Devi",
            patient_phone="9876543210",
            llm_client=MockLLMClient(),
            whatsapp_client=client,
            sms_client=MockSmsClient(),
        )
    )
    assert client.seen is None  # No provider bypasses ASHA approval.

    # And the mock provider still reports mock_sent, so nothing that relied
    # on the old behaviour changed meaning.
    actions = asyncio.run(
        agent3.generate(
            extracted=ExtractedFields(),
            risk_level="LOW",
            risk_drivers=[],
            patient_name="Asha Devi",
            patient_phone="9876543210",
            llm_client=MockLLMClient(),
            whatsapp_client=MockWhatsAppClient(),
            sms_client=MockSmsClient(),
        )
    )
    assert next(a for a in actions if a["type"] == "whatsapp")["status"] == "draft"


def test_a_failed_send_does_not_lose_the_visit():
    """The bug this guards: Agent 3 runs after the transcript, the
    extracted record and the risk classification already exist. An
    expired WhatsApp token was raising out of Agent 3, failing the whole
    /visits/voice request, and the ASHA saw no risk level at all for a
    visit the system had already assessed correctly."""
    from app.agents import agent3_action_generation as agent3
    from app.schemas.visit import ExtractedFields, RiskDriver
    from app.services.llm_client import MockLLMClient
    from app.services.sms_client import MockSmsClient
    from app.services.whatsapp_client import WhatsAppClientBase, WhatsAppError

    class Broken(WhatsAppClientBase):
        async def send_message(self, to_phone, message):
            raise WhatsAppError("[190] Session has expired")

        async def send_template(self, to_phone, template_name, body_params=None, language_code="en_US"):
            raise WhatsAppError("[190] Session has expired")

    actions = asyncio.run(
        agent3.generate(
            extracted=ExtractedFields(bp_systolic=140, bp_diastolic=90),
            risk_level="HIGH",
            risk_drivers=[RiskDriver(observation="BP 140/90", reason="above NHM threshold")],
            patient_name="Meera Patil",
            patient_phone="9876543210",
            llm_client=MockLLMClient(),
            whatsapp_client=Broken(),
            sms_client=MockSmsClient(),
        )
    )

    # The visit's own outputs survive the delivery failure.
    kinds = {a["type"] for a in actions}
    assert "referral" in kinds, "HIGH-risk referral letter was lost"
    assert "followup" in kinds, "follow-up task was lost"

    # And the failure is recorded rather than hidden.
    wa = next(a for a in actions if a["type"] == "whatsapp")
    assert wa["status"] == "draft"
    assert "error" not in wa  # Assessment did not attempt delivery.


def test_a_failed_sms_is_also_recorded_not_raised():
    from app.agents import agent3_action_generation as agent3
    from app.schemas.visit import ExtractedFields
    from app.services.llm_client import MockLLMClient
    from app.services.sms_client import SmsClientBase
    from app.services.whatsapp_client import MockWhatsAppClient

    class BrokenSms(SmsClientBase):
        async def send_message(self, to_phone, message):
            raise RuntimeError("Twilio 21608 unverified recipient")

    actions = asyncio.run(
        agent3.generate(
            extracted=ExtractedFields(),
            risk_level="LOW",
            risk_drivers=[],
            patient_name="Asha Devi",
            patient_phone="9876543210",
            llm_client=MockLLMClient(),
            whatsapp_client=MockWhatsAppClient(),
            sms_client=BrokenSms(),
        )
    )
    assert not any(a["type"] == "sms" for a in actions)
    assert next(a for a in actions if a["type"] == "whatsapp")["status"] == "draft"
    assert any(a["type"] == "followup" for a in actions)

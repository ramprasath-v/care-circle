import pytest
from pydantic import ValidationError

from carecircle.schemas import CareRequest, CareResponse


def test_request(request_data):
    assert CareRequest(**request_data).session_id == "demo-session"


@pytest.mark.parametrize("field,value", [("household_id", ""), ("utterance", "  "), ("actor_role", 1), ("session_id", None)])
def test_invalid_request(request_data, field, value):
    request_data[field] = value
    with pytest.raises(ValidationError):
        CareRequest(**request_data)


def test_missing_request_field(request_data):
    del request_data["session_id"]
    with pytest.raises(ValidationError):
        CareRequest(**request_data)


def test_response_roundtrip(response):
    assert CareResponse.model_validate_json(response.model_dump_json()) == response


def test_invalid_risk(response):
    with pytest.raises(ValidationError):
        CareResponse.model_validate({**response.model_dump(), "risk_level": "critical"})


def test_response_requires_fields(response):
    data = response.model_dump()
    del data["approval_required"]
    with pytest.raises(ValidationError):
        CareResponse.model_validate(data)

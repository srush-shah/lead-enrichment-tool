from __future__ import annotations

from backend.lead_brief import (
    _fallback_body,
    _fallback_subject,
    _property_specs,
    _strip_brief_label,
    apply_tone_template,
)
from backend.models import (
    CensusData,
    EnrichedLead,
    GeoData,
    LeadBrief,
    LeadInput,
    WalkData,
)


def _make_lead(*, with_brief: bool = True, with_specs: bool = True) -> EnrichedLead:
    return EnrichedLead(
        input=LeadInput(
            name="Sarah Chen",
            email="schen@greystar.com",
            company="Greystar",
            property_address="465 W 23rd St",
            city="New York",
            state="NY",
        ),
        geo=GeoData(zip_code="10011" if with_specs else None),
        census=CensusData(
            pct_5plus_units=82.0 if with_specs else None,
            median_gross_rent=2300 if with_specs else None,
            renter_occupied_pct=78.0,
        ),
        walk=WalkData(walkscore=95 if with_specs else None),
        brief=LeadBrief(
            why_now="Trigger: Greystar — \"Foo Acquired\" (3 days ago, Reuters) (ZIP 10011).",
            why_now_source="news",
            talking_point="New York, NY: 82% in 5+ unit buildings; median rent $2,300; Walkability 95/100.",
        )
        if with_brief
        else None,
    )


def test_strip_brief_label_handles_each_prefix():
    assert _strip_brief_label("Trigger: Foo") == "Foo"
    assert _strip_brief_label("Market Insight: Bar") == "Bar"
    assert _strip_brief_label("Company Note: Baz") == "Baz"
    # Untouched if there's no prefix.
    assert _strip_brief_label("No prefix here") == "No prefix here"


def test_property_specs_omits_missing_fields():
    lead = _make_lead(with_specs=False)
    assert _property_specs(lead) == ""


def test_property_specs_joins_present_fields():
    lead = _make_lead(with_specs=True)
    specs = _property_specs(lead)
    assert "ZIP 10011" in specs
    assert "82% in 5+ unit buildings" in specs
    assert "WalkScore 95" in specs
    assert "median rent $2,300" in specs
    assert " · " in specs


def test_fallback_body_strips_labels_and_appends_specs_footer():
    lead = _make_lead()
    body = _fallback_body(lead)
    assert "Trigger:" not in body
    assert "Market Insight:" not in body
    assert "Company Note:" not in body
    assert "Property specs:" in body
    assert "ZIP 10011" in body
    # Talking-point string used to be inlined into the intro paragraph; now
    # only the (label-stripped) anchor goes there.
    intro = body.split("\n\n")[1]
    assert "Walkability" not in intro
    assert "median rent" not in intro


def test_fallback_body_skips_footer_when_no_specs():
    lead = _make_lead(with_specs=False)
    body = _fallback_body(lead)
    assert "Property specs:" not in body
    assert "---" not in body


def test_fallback_subject_is_clean():
    subject = _fallback_subject(_make_lead())
    assert "Trigger:" not in subject
    assert "Greystar" in subject


def test_apply_tone_template_casual_swaps_closer():
    body = "Hi Sarah,\n\nFoo.\n\nWorth a 15-min intro next week? Happy to send times."
    _, new_body = apply_tone_template("subj", body, "casual")
    assert "Hey Sarah," in new_body
    assert "Open to a quick 15-min chat" in new_body


def test_apply_tone_template_formal_swaps_closer():
    body = "Hey Sarah,\n\nFoo.\n\nWorth a 15-min intro next week? Happy to send times."
    _, new_body = apply_tone_template("subj", body, "formal")
    assert "Hi Sarah," in new_body
    assert "Would you be available for a 15-minute introduction" in new_body


def test_apply_tone_template_default_is_noop():
    body = "Hi Sarah,\n\nFoo."
    new_subject, new_body = apply_tone_template("subj", body, None)
    assert new_subject == "subj"
    assert new_body == body

"""The issue and pull request templates are the forms GitHub actually renders.

A form with a malformed field does not fail loudly: GitHub drops it from the
chooser and the contributor gets a blank box, which is the state these
templates exist to replace. A contact link pointing at a file that has been
renamed fails the same quiet way.
"""

from __future__ import annotations

from pathlib import Path
from urllib.parse import urlparse

import pytest
import yaml

from .conftest import REPO_ROOT

TEMPLATES = REPO_ROOT / ".github" / "ISSUE_TEMPLATE"
PULL_REQUEST = REPO_ROOT / ".github" / "PULL_REQUEST_TEMPLATE.md"
#: Field types that put a prompt in front of a contributor, as opposed to
#: `markdown`, which only prints.
PROMPTING = {"input", "textarea", "dropdown", "checkboxes"}

FORMS = sorted(path for path in TEMPLATES.glob("*.yml") if path.name != "config.yml")


def test_there_are_issue_forms_to_check() -> None:
    assert FORMS


@pytest.mark.parametrize("form", FORMS, ids=lambda path: path.name)
def test_an_issue_form_is_a_form_github_can_render(form: Path) -> None:
    body = yaml.safe_load(form.read_text(encoding="utf-8"))
    assert body["name"], form.name
    assert body["description"], form.name
    assert body["body"], form.name

    ids: list[str] = []
    for field in body["body"]:
        assert field["type"] in PROMPTING | {"markdown"}, field
        assert field["attributes"], field
        if field["type"] in PROMPTING:
            assert field["attributes"]["label"], field
            assert field["id"] not in ids, f"duplicate field id {field['id']}"
            ids.append(field["id"])
        else:
            assert field["attributes"]["value"], field


def test_the_wrong_value_form_asks_for_what_contributing_asks_for() -> None:
    """CONTRIBUTING names four things a report of a wrong value needs."""
    form = yaml.safe_load((TEMPLATES / "wrong-or-uncited-value.yml").read_text(encoding="utf-8"))
    required = {
        field["id"]
        for field in form["body"]
        if field.get("validations", {}).get("required") is True
    }
    assert {"document", "location", "emitted", "published"} <= required


def test_every_contact_link_points_at_a_file_that_exists() -> None:
    config = yaml.safe_load((TEMPLATES / "config.yml").read_text(encoding="utf-8"))
    links = config["contact_links"]
    assert links
    for link in links:
        assert link["name"] and link["about"]
        path = urlparse(link["url"]).path
        marker = "/blob/main/"
        assert marker in path, link["url"]
        target = REPO_ROOT / path.split(marker, 1)[1]
        assert target.exists(), f"{link['name']} points at {target}, which does not exist"


def test_the_security_route_is_offered() -> None:
    config = yaml.safe_load((TEMPLATES / "config.yml").read_text(encoding="utf-8"))
    assert any("SECURITY.md" in link["url"] for link in config["contact_links"])


def test_the_pull_request_checklist_states_the_rules_contributing_states() -> None:
    text = PULL_REQUEST.read_text(encoding="utf-8")
    for phrase in ("make verify", "tests/golden/", "refusal", "coverage figure", "SYNTHETIC"):
        assert phrase in text, phrase


def test_no_checklist_box_ships_already_ticked() -> None:
    """A box ticked in the template is a box nobody ticked."""
    boxes = [
        line
        for line in PULL_REQUEST.read_text(encoding="utf-8").splitlines()
        if line.lstrip().startswith("- [")
    ]
    assert boxes
    assert all(line.lstrip().startswith("- [ ]") for line in boxes)

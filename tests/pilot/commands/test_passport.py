import json
from unittest.mock import Mock

import pytest

from pilot.commands.sites.passport import ConfirmPassportCommand
from pilot.exceptions import BenchError


@pytest.mark.parametrize("content", ["invalid", "[]", "{}", '{"reviewed": [], "approved": []}'])
def test_invalid_review_does_not_start_confirmation(tmp_path, content):
    path = tmp_path / "review.json"
    path.write_text(content)
    bench = Mock()
    command = ConfirmPassportCommand(bench=bench, site_name="test.local", review_file=path)
    with pytest.raises(BenchError):
        command.run()
    bench.site.assert_not_called()


def test_review_passes_only_the_selected_associations(tmp_path):
    path = tmp_path / "review.json"
    path.write_text(
        json.dumps({"reviewed": {"identity": "epoch"}, "approved": ["identity"], "identities": []})
    )
    bench = Mock()
    command = ConfirmPassportCommand(bench=bench, site_name="test.local", review_file=path)
    command.run()
    bench.site.assert_called_once_with("test.local")
    bench.site.return_value.confirm_passport_enrollment.assert_called_once_with(
        {"identity": "epoch"}, ["identity"]
    )

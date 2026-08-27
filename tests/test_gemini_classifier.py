"""Protects the accident-prevention gate the whole cost-safety design relies
on: GeminiClassifier must refuse to construct -- and must never touch the
network -- unless USE_LLM_CLASSIFIER is explicitly "true". This is the most
carefully written test in the suite on purpose."""
import pytest

from taxonomy import load_taxonomy


@pytest.fixture
def taxonomy():
    return load_taxonomy()


@pytest.mark.parametrize("value", [None, "", "false", "0", "no", "off", "True but not quite"])
def test_raises_before_constructing_any_client_when_not_enabled(monkeypatch, mocker, taxonomy, value):
    if value is None:
        monkeypatch.delenv("USE_LLM_CLASSIFIER", raising=False)
    else:
        monkeypatch.setenv("USE_LLM_CLASSIFIER", value)

    mock_client_cls = mocker.patch("google.genai.Client")

    from gemini_classifier import GeminiClassifier

    with pytest.raises(RuntimeError, match="USE_LLM_CLASSIFIER"):
        GeminiClassifier(taxonomy, project="fake-project")

    mock_client_cls.assert_not_called()


def test_does_not_raise_when_enabled_and_project_given(monkeypatch, mocker, taxonomy):
    monkeypatch.setenv("USE_LLM_CLASSIFIER", "true")
    mock_client_cls = mocker.patch("google.genai.Client")

    from gemini_classifier import GeminiClassifier

    GeminiClassifier(taxonomy, project="fake-project")

    mock_client_cls.assert_called_once()


def test_raises_when_enabled_but_no_project_available(monkeypatch, mocker, taxonomy):
    monkeypatch.setenv("USE_LLM_CLASSIFIER", "true")
    monkeypatch.delenv("GCP_PROJECT_ID", raising=False)
    mock_client_cls = mocker.patch("google.genai.Client")

    from gemini_classifier import GeminiClassifier

    with pytest.raises(RuntimeError, match="GCP_PROJECT_ID"):
        GeminiClassifier(taxonomy)

    mock_client_cls.assert_not_called()

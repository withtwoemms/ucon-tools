# tests/test_ner.py
#
# Unit tests for NER training and evaluation module.

"""
Tests for ucon.tools.mcp.ner module.

These tests verify the configuration, data handling, and evaluation
components of the NER training pipeline.
"""

import json
import tempfile
from pathlib import Path

import pytest

from ucon.tools.mcp.ner import (
    EntityLabel,
    NERConfig,
    DEFAULT_CONFIG,
    TrainingExample,
    TrainingDataset,
    validate_example,
    validate_dataset,
    EvaluationResult,
    evaluate,
    # Unit normalization
    normalize_unit_string,
    parse_unit_structure,
    ParsedUnit,
    ComponentNormalizer,
    ComponentMapping,
    get_default_normalizer,
)


class TestEntityLabel:
    """Tests for EntityLabel enum."""

    def test_quantity_label_exists(self):
        assert EntityLabel.QUANTITY.value == "QUANTITY"

    def test_label_values_are_strings(self):
        for label in EntityLabel:
            assert isinstance(label.value, str)


class TestNERConfig:
    """Tests for NERConfig dataclass."""

    def test_default_config_exists(self):
        assert DEFAULT_CONFIG is not None

    def test_default_values(self):
        config = NERConfig()
        assert config.model_name == "quantity_ner"
        assert config.base_model == "en_core_web_sm"
        assert config.entity_labels == ("QUANTITY",)
        assert config.n_iter == 30
        assert config.batch_size == 8
        assert config.dropout == 0.3
        assert config.validation_split == 0.2

    def test_custom_values(self):
        config = NERConfig(
            n_iter=50,
            batch_size=16,
            dropout=0.5,
        )
        assert config.n_iter == 50
        assert config.batch_size == 16
        assert config.dropout == 0.5

    def test_config_is_frozen(self):
        config = NERConfig()
        with pytest.raises(Exception):  # FrozenInstanceError
            config.n_iter = 100

    def test_get_model_dir(self):
        config = NERConfig()
        model_dir = config.get_model_dir()
        assert model_dir.name == "quantity_ner"
        assert "models" in str(model_dir)


class TestTrainingExample:
    """Tests for TrainingExample dataclass."""

    def test_create_from_values(self):
        ex = TrainingExample(
            text="Give 5 mg to patient",
            entities=[(5, 9, "QUANTITY")],
            domain="medical",
        )
        assert ex.text == "Give 5 mg to patient"
        assert ex.entities == [(5, 9, "QUANTITY")]
        assert ex.domain == "medical"

    def test_default_domain(self):
        ex = TrainingExample(
            text="Test",
            entities=[],
        )
        assert ex.domain == "general"

    def test_to_spacy_format(self):
        ex = TrainingExample(
            text="Give 5 mg to patient",
            entities=[(5, 9, "QUANTITY")],
        )
        text, annotations = ex.to_spacy_format()
        assert text == "Give 5 mg to patient"
        assert annotations == {"entities": [(5, 9, "QUANTITY")]}

    def test_from_dict(self):
        data = {
            "text": "Give 5 mg to patient",
            "entities": [[5, 9, "QUANTITY"]],
            "domain": "medical",
        }
        ex = TrainingExample.from_dict(data)
        assert ex.text == "Give 5 mg to patient"
        assert ex.entities == [(5, 9, "QUANTITY")]
        assert ex.domain == "medical"

    def test_from_dict_without_domain(self):
        data = {
            "text": "Test",
            "entities": [],
        }
        ex = TrainingExample.from_dict(data)
        assert ex.domain == "general"

    def test_to_dict(self):
        ex = TrainingExample(
            text="Give 5 mg to patient",
            entities=[(5, 9, "QUANTITY")],
            domain="medical",
        )
        data = ex.to_dict()
        assert data["text"] == "Give 5 mg to patient"
        assert data["entities"] == [[5, 9, "QUANTITY"]]
        assert data["domain"] == "medical"

    def test_roundtrip(self):
        original = TrainingExample(
            text="Give 5 mg to patient",
            entities=[(5, 9, "QUANTITY")],
            domain="medical",
        )
        data = original.to_dict()
        restored = TrainingExample.from_dict(data)
        assert restored.text == original.text
        assert restored.entities == original.entities
        assert restored.domain == original.domain


class TestTrainingDataset:
    """Tests for TrainingDataset dataclass."""

    def test_create_dataset(self):
        examples = [
            TrainingExample("Test 1", [(0, 4, "QUANTITY")]),
            TrainingExample("Test 2", [(0, 4, "QUANTITY")]),
        ]
        dataset = TrainingDataset(
            version="1.0",
            entity_labels=["QUANTITY"],
            examples=examples,
        )
        assert len(dataset) == 2
        assert dataset.version == "1.0"

    def test_len(self):
        examples = [
            TrainingExample("Test", []) for _ in range(5)
        ]
        dataset = TrainingDataset("1.0", ["QUANTITY"], examples)
        assert len(dataset) == 5

    def test_iter(self):
        examples = [
            TrainingExample(f"Test {i}", []) for i in range(3)
        ]
        dataset = TrainingDataset("1.0", ["QUANTITY"], examples)
        texts = [ex.text for ex in dataset]
        assert texts == ["Test 0", "Test 1", "Test 2"]

    def test_split(self):
        examples = [
            TrainingExample(f"Test {i}", []) for i in range(10)
        ]
        dataset = TrainingDataset("1.0", ["QUANTITY"], examples)
        train, val = dataset.split(ratio=0.2, seed=42)

        assert len(train) == 8
        assert len(val) == 2
        assert train.version == dataset.version
        assert val.version == dataset.version

    def test_split_with_seed_is_reproducible(self):
        examples = [
            TrainingExample(f"Test {i}", []) for i in range(10)
        ]
        dataset = TrainingDataset("1.0", ["QUANTITY"], examples)

        train1, val1 = dataset.split(ratio=0.2, seed=42)
        train2, val2 = dataset.split(ratio=0.2, seed=42)

        assert [ex.text for ex in train1] == [ex.text for ex in train2]
        assert [ex.text for ex in val1] == [ex.text for ex in val2]

    def test_filter_by_domain(self):
        examples = [
            TrainingExample("Medical 1", [], domain="medical"),
            TrainingExample("Physics 1", [], domain="physics"),
            TrainingExample("Medical 2", [], domain="medical"),
        ]
        dataset = TrainingDataset("1.0", ["QUANTITY"], examples)

        medical = dataset.filter_by_domain("medical")
        assert len(medical) == 2
        assert all(ex.domain == "medical" for ex in medical)

    def test_save_and_load(self):
        examples = [
            TrainingExample("Give 5 mg", [(5, 9, "QUANTITY")], domain="medical"),
            TrainingExample("Convert 10 L", [(8, 12, "QUANTITY")], domain="general"),
        ]
        dataset = TrainingDataset("1.0", ["QUANTITY"], examples)

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            dataset.save(path)
            loaded = TrainingDataset.load(path)

            assert loaded.version == dataset.version
            assert loaded.entity_labels == dataset.entity_labels
            assert len(loaded) == len(dataset)

            for orig, load in zip(dataset.examples, loaded.examples):
                assert orig.text == load.text
                assert orig.entities == load.entities
                assert orig.domain == load.domain
        finally:
            path.unlink()

    def test_load_invalid_file(self):
        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            f.write('{"invalid": "format"}')
            path = Path(f.name)

        try:
            with pytest.raises(ValueError, match="Missing required field"):
                TrainingDataset.load(path)
        finally:
            path.unlink()


class TestValidateExample:
    """Tests for validate_example function."""

    def test_valid_example(self):
        example = {
            "text": "Give 5 mg to patient",
            "entities": [[5, 9, "QUANTITY"]],
        }
        issues = validate_example(example)
        assert issues == []

    def test_missing_text(self):
        example = {"entities": []}
        issues = validate_example(example)
        assert any("text" in issue for issue in issues)

    def test_missing_entities(self):
        example = {"text": "Test"}
        issues = validate_example(example)
        assert any("entities" in issue for issue in issues)

    def test_empty_text(self):
        example = {"text": "", "entities": []}
        issues = validate_example(example)
        assert any("empty" in issue for issue in issues)

    def test_invalid_entity_format(self):
        example = {
            "text": "Test",
            "entities": ["invalid"],
        }
        issues = validate_example(example)
        assert any("list/tuple" in issue for issue in issues)

    def test_wrong_entity_length(self):
        example = {
            "text": "Test",
            "entities": [[0, 4]],  # Missing label
        }
        issues = validate_example(example)
        assert any("3 elements" in issue for issue in issues)

    def test_negative_start(self):
        example = {
            "text": "Test",
            "entities": [[-1, 4, "QUANTITY"]],
        }
        issues = validate_example(example)
        assert any("negative" in issue for issue in issues)

    def test_end_exceeds_text_length(self):
        example = {
            "text": "Test",
            "entities": [[0, 100, "QUANTITY"]],
        }
        issues = validate_example(example)
        assert any("exceeds" in issue for issue in issues)

    def test_start_greater_than_end(self):
        example = {
            "text": "Test",
            "entities": [[3, 1, "QUANTITY"]],
        }
        issues = validate_example(example)
        assert any(">=" in issue for issue in issues)

    def test_invalid_label(self):
        example = {
            "text": "Test",
            "entities": [[0, 4, "INVALID"]],
        }
        issues = validate_example(example)
        assert any("unknown label" in issue for issue in issues)

    def test_overlapping_entities(self):
        example = {
            "text": "Give 5 mg quickly",
            "entities": [
                [5, 9, "QUANTITY"],
                [7, 12, "QUANTITY"],  # Overlaps with previous
            ],
        }
        issues = validate_example(example)
        assert any("overlap" in issue for issue in issues)

    def test_multiple_non_overlapping_entities(self):
        example = {
            "text": "Give 5 mg to 70 kg patient",
            "entities": [
                [5, 9, "QUANTITY"],
                [13, 18, "QUANTITY"],
            ],
        }
        issues = validate_example(example)
        assert issues == []


class TestValidateDataset:
    """Tests for validate_dataset function."""

    def test_all_valid(self):
        examples = [
            TrainingExample("Give 5 mg", [(5, 9, "QUANTITY")]),
            TrainingExample("Convert 10 L", [(8, 12, "QUANTITY")]),
        ]
        dataset = TrainingDataset("1.0", ["QUANTITY"], examples)
        result = validate_dataset(dataset)

        assert result["valid_count"] == 2
        assert result["invalid_count"] == 0
        assert result["issues"] == []

    def test_mixed_validity(self):
        examples = [
            TrainingExample("Give 5 mg", [(5, 9, "QUANTITY")]),  # Valid
            TrainingExample("Test", [(0, 100, "QUANTITY")]),  # Invalid - out of bounds
        ]
        dataset = TrainingDataset("1.0", ["QUANTITY"], examples)
        result = validate_dataset(dataset)

        assert result["valid_count"] == 1
        assert result["invalid_count"] == 1
        assert len(result["issues"]) == 1


class TestEvaluate:
    """Tests for evaluate function."""

    def test_perfect_predictions(self):
        predictions = [
            [(0, 4, "QUANTITY"), (10, 14, "QUANTITY")],
            [(5, 9, "QUANTITY")],
        ]
        gold = [
            [(0, 4, "QUANTITY"), (10, 14, "QUANTITY")],
            [(5, 9, "QUANTITY")],
        ]
        result = evaluate(predictions, gold)

        assert result.precision == 1.0
        assert result.recall == 1.0
        assert result.f1 == 1.0
        assert result.true_positives == 3
        assert result.false_positives == 0
        assert result.false_negatives == 0

    def test_no_predictions(self):
        predictions = [[], []]
        gold = [
            [(0, 4, "QUANTITY")],
            [(5, 9, "QUANTITY")],
        ]
        result = evaluate(predictions, gold)

        assert result.precision == 0.0
        assert result.recall == 0.0
        assert result.f1 == 0.0
        assert result.false_negatives == 2

    def test_extra_predictions(self):
        predictions = [
            [(0, 4, "QUANTITY"), (10, 14, "QUANTITY")],
        ]
        gold = [
            [(0, 4, "QUANTITY")],
        ]
        result = evaluate(predictions, gold)

        assert result.true_positives == 1
        assert result.false_positives == 1
        assert result.precision == 0.5
        assert result.recall == 1.0

    def test_missed_entities(self):
        predictions = [
            [(0, 4, "QUANTITY")],
        ]
        gold = [
            [(0, 4, "QUANTITY"), (10, 14, "QUANTITY")],
        ]
        result = evaluate(predictions, gold)

        assert result.true_positives == 1
        assert result.false_negatives == 1
        assert result.precision == 1.0
        assert result.recall == 0.5

    def test_partial_matching(self):
        predictions = [
            [(0, 5, "QUANTITY")],  # Slightly larger span
        ]
        gold = [
            [(1, 4, "QUANTITY")],
        ]
        result = evaluate(predictions, gold, mode="partial")

        assert result.true_positives == 1
        assert result.precision == 1.0

    def test_exact_matching_rejects_partial(self):
        predictions = [
            [(0, 5, "QUANTITY")],
        ]
        gold = [
            [(1, 4, "QUANTITY")],
        ]
        result = evaluate(predictions, gold, mode="exact")

        assert result.true_positives == 0
        assert result.false_positives == 1
        assert result.false_negatives == 1

    def test_different_labels_dont_match(self):
        predictions = [
            [(0, 4, "QUANTITY")],
        ]
        gold = [
            [(0, 4, "OTHER")],  # Different label
        ]
        result = evaluate(predictions, gold)

        assert result.true_positives == 0

    def test_per_label_scores(self):
        predictions = [
            [(0, 4, "QUANTITY"), (10, 14, "QUANTITY")],
        ]
        gold = [
            [(0, 4, "QUANTITY"), (10, 14, "QUANTITY")],
        ]
        result = evaluate(predictions, gold)

        assert "QUANTITY" in result.per_label_scores
        assert result.per_label_scores["QUANTITY"]["precision"] == 1.0

    def test_length_mismatch_raises(self):
        predictions = [[(0, 4, "QUANTITY")]]
        gold = [[(0, 4, "QUANTITY")], [(5, 9, "QUANTITY")]]

        with pytest.raises(ValueError, match="same length"):
            evaluate(predictions, gold)


class TestEvaluationResult:
    """Tests for EvaluationResult dataclass."""

    def test_to_dict(self):
        result = EvaluationResult(
            precision=0.8,
            recall=0.9,
            f1=0.847,
            true_positives=9,
            false_positives=2,
            false_negatives=1,
            total_examples=10,
        )
        data = result.to_dict()

        assert data["precision"] == 0.8
        assert data["recall"] == 0.9
        assert data["f1"] == 0.847
        assert data["true_positives"] == 9

    def test_str_representation(self):
        result = EvaluationResult(
            precision=0.8,
            recall=0.9,
            f1=0.847,
            true_positives=9,
            false_positives=2,
            false_negatives=1,
            total_examples=10,
        )
        s = str(result)

        assert "Precision" in s
        assert "Recall" in s
        assert "F1" in s
        assert "TP: 9" in s


# =============================================================================
# Unit Normalizer Tests
# =============================================================================


class TestParseUnitStructure:
    """Tests for parse_unit_structure function."""

    def test_simple_unit(self):
        parsed = parse_unit_structure("mg")
        assert parsed.components == ["mg"]
        assert parsed.operators == []

    def test_per_pattern(self):
        parsed = parse_unit_structure("mg per dose")
        assert parsed.components == ["mg", "dose"]
        assert parsed.operators == ["/"]

    def test_per_pattern_case_insensitive(self):
        parsed = parse_unit_structure("MG Per DOSE")
        assert parsed.components == ["MG", "DOSE"]
        assert parsed.operators == ["/"]

    def test_formal_division(self):
        parsed = parse_unit_structure("mg/h")
        assert parsed.components == ["mg", "h"]
        assert parsed.operators == ["/"]

    def test_formal_multiplication(self):
        parsed = parse_unit_structure("kg*m")
        assert parsed.components == ["kg", "m"]
        assert parsed.operators == ["*"]

    def test_complex_unit(self):
        parsed = parse_unit_structure("kg*m/s")
        assert parsed.components == ["kg", "m", "s"]
        assert parsed.operators == ["*", "/"]

    def test_reconstruct(self):
        parsed = parse_unit_structure("mg per dose")
        result = parsed.reconstruct(["mg", "ea"])
        assert result == "mg/ea"

    def test_a_day_pattern(self):
        parsed = parse_unit_structure("mg a day")
        assert parsed.components == ["mg", "day"]
        assert parsed.operators == ["/"]

    def test_every_pattern(self):
        parsed = parse_unit_structure("doses every hour")
        assert parsed.components == ["doses", "hour"]
        assert parsed.operators == ["/"]


class TestComponentNormalizer:
    """Tests for ComponentNormalizer class."""

    def test_empty_normalizer(self):
        normalizer = ComponentNormalizer()
        assert len(normalizer) == 0
        assert normalizer.normalize("mg") == "mg"

    def test_add_mapping(self):
        normalizer = ComponentNormalizer()
        normalizer.add_mapping("dose", "ea", "count")
        assert normalizer.normalize("dose") == "ea"
        assert normalizer.normalize("DOSE") == "ea"  # case insensitive

    def test_unknown_component(self):
        normalizer = ComponentNormalizer()
        normalizer.add_mapping("dose", "ea")
        assert normalizer.normalize("xyz") == "xyz"  # passthrough

    def test_add_mappings(self):
        normalizer = ComponentNormalizer()
        normalizer.add_mappings([
            ComponentMapping("dose", "ea", "count"),
            ComponentMapping("hour", "h", "time"),
        ])
        assert len(normalizer) == 2
        assert normalizer.normalize("dose") == "ea"
        assert normalizer.normalize("hour") == "h"

    def test_save_and_load(self):
        normalizer = ComponentNormalizer()
        normalizer.add_mapping("dose", "ea", "count")
        normalizer.add_mapping("hour", "h", "time")

        with tempfile.NamedTemporaryFile(mode="w", suffix=".json", delete=False) as f:
            path = Path(f.name)

        try:
            normalizer.save(path)
            loaded = ComponentNormalizer.load(path)

            assert len(loaded) == 2
            assert loaded.normalize("dose") == "ea"
            assert loaded.normalize("hour") == "h"
        finally:
            path.unlink()


class TestGetDefaultNormalizer:
    """Tests for default normalizer."""

    def test_has_mappings(self):
        normalizer = get_default_normalizer()
        assert len(normalizer) > 0

    def test_common_mappings(self):
        normalizer = get_default_normalizer()
        assert normalizer.normalize("dose") == "ea"
        assert normalizer.normalize("doses") == "ea"
        assert normalizer.normalize("hour") == "h"
        assert normalizer.normalize("hours") == "h"
        assert normalizer.normalize("milligrams") == "mg"
        assert normalizer.normalize("liters") == "L"


class TestNormalizeUnitString:
    """Tests for normalize_unit_string function."""

    def test_simple_passthrough(self):
        assert normalize_unit_string("mg") == "mg"
        assert normalize_unit_string("kg") == "kg"
        assert normalize_unit_string("L") == "L"

    def test_per_dose(self):
        assert normalize_unit_string("mg per dose") == "mg/ea"

    def test_per_hour(self):
        assert normalize_unit_string("mg per hour") == "mg/h"
        assert normalize_unit_string("milligrams per hour") == "mg/h"

    def test_formal_unit_normalization(self):
        # Already formal but with full names
        assert normalize_unit_string("milligrams/hour") == "mg/h"

    def test_already_canonical(self):
        assert normalize_unit_string("mg/h") == "mg/h"
        assert normalize_unit_string("L/min") == "L/min"

    def test_multiple_per_partial(self):
        # Multiple "per" patterns - only first is parsed
        # "mg per kg per day" parses as "mg" / "kg per day"
        # Then "kg per day" normalizes to "kg/day"
        result = normalize_unit_string("mg per kg per day")
        # The structure parser splits on first "per"
        assert result == "mg/kg per day" or result == "mg/kg/day"

    def test_empty_string(self):
        assert normalize_unit_string("") == ""

    def test_whitespace_handling(self):
        assert normalize_unit_string("  mg per dose  ") == "mg/ea"

    def test_case_preservation_for_unknown(self):
        # Unknown units should pass through
        assert normalize_unit_string("XYZ per ABC") == "XYZ/ABC"

#!/usr/bin/env python
"""
SpaCy NER Training Script for Quantity Extraction.

Trains a Named Entity Recognition model to extract QUANTITY entities
from natural language text. The trained model integrates with ucon's
MCP server for improved extraction accuracy.

Usage:
    # Train with defaults
    python scripts/train_quantity_ner.py data/ner/training_v1.json

    # Validate training data only
    python scripts/train_quantity_ner.py data/ner/training_v1.json --validate

    # Evaluate existing model
    python scripts/train_quantity_ner.py data/ner/training_v1.json --evaluate

    # Custom training parameters
    python scripts/train_quantity_ner.py data/ner/training_v1.json -n 50 -b 16

    # Output to custom path
    python scripts/train_quantity_ner.py data/ner/training_v1.json -o my_model

Requirements:
    pip install spacy
    python -m spacy download en_core_web_sm
"""

from __future__ import annotations

import argparse
import random
import sys
from pathlib import Path

# Add parent directory to path for local imports
sys.path.insert(0, str(Path(__file__).parent.parent))

from ucon.tools.mcp.ner import (
    DEFAULT_CONFIG,
    NERConfig,
    TrainingDataset,
    validate_dataset,
    evaluate_model,
)


def validate_data(dataset: TrainingDataset) -> bool:
    """Validate training data and print issues.

    Args:
        dataset: Dataset to validate.

    Returns:
        True if all examples are valid, False otherwise.
    """
    print(f"Validating {len(dataset)} examples...")

    result = validate_dataset(dataset)

    print(f"  Valid:   {result['valid_count']}")
    print(f"  Invalid: {result['invalid_count']}")

    if result["issues"]:
        print("\nIssues found:")
        for idx, issues in result["issues"]:
            print(f"  Example {idx}:")
            for issue in issues:
                print(f"    - {issue}")

        return False

    print("\nAll examples valid!")
    return True


def train_model(
    dataset: TrainingDataset,
    config: NERConfig,
    output_path: Path,
    verbose: bool = False,
) -> Path:
    """Train NER model on dataset.

    Args:
        dataset: Training dataset.
        config: Training configuration.
        output_path: Where to save the trained model.
        verbose: Print detailed progress.

    Returns:
        Path to the saved model.
    """
    try:
        import spacy
        from spacy.training import Example
    except ImportError:
        print("SpaCy is required for training.")
        print("Install with: pip install spacy")
        print("Then download model: python -m spacy download en_core_web_sm")
        sys.exit(1)

    # Split into train/validation
    train_data, val_data = dataset.split(ratio=config.validation_split, seed=42)

    print(f"Training examples: {len(train_data)}")
    print(f"Validation examples: {len(val_data)}")
    print(f"Entity labels: {config.entity_labels}")
    print(f"Iterations: {config.n_iter}")
    print(f"Batch size: {config.batch_size}")
    print(f"Dropout: {config.dropout}")
    print()

    # Create blank model or load base model
    try:
        nlp = spacy.load(config.base_model)
        print(f"Loaded base model: {config.base_model}")
        # Remove existing NER if present
        if "ner" in nlp.pipe_names:
            nlp.remove_pipe("ner")
    except OSError:
        nlp = spacy.blank("en")
        print("Created blank English model")

    # Add NER component
    ner = nlp.add_pipe("ner", last=True)

    # Add entity labels
    for label in config.entity_labels:
        ner.add_label(label)

    # Convert training data to SpaCy format
    train_examples = []
    for ex in train_data:
        doc = nlp.make_doc(ex.text)
        train_examples.append(Example.from_dict(doc, {"entities": ex.entities}))

    # Begin training
    optimizer = nlp.begin_training()

    # Training loop
    best_f1 = 0.0
    best_iter = 0

    for iteration in range(config.n_iter):
        random.shuffle(train_examples)
        losses = {}

        # Create batches
        for batch in spacy.util.minibatch(train_examples, size=config.batch_size):
            nlp.update(batch, sgd=optimizer, losses=losses, drop=config.dropout)

        # Evaluate on validation set
        if val_data.examples:
            val_examples = [ex.to_spacy_format() for ex in val_data.examples]
            eval_result = evaluate_model(nlp, val_examples)
            f1 = eval_result.f1

            if f1 > best_f1:
                best_f1 = f1
                best_iter = iteration

            if verbose or iteration % 5 == 0 or iteration == config.n_iter - 1:
                print(
                    f"Iter {iteration:3d}: "
                    f"Loss={losses.get('ner', 0):.4f}  "
                    f"P={eval_result.precision:.3f}  "
                    f"R={eval_result.recall:.3f}  "
                    f"F1={f1:.3f}"
                )
        else:
            if verbose or iteration % 5 == 0 or iteration == config.n_iter - 1:
                print(f"Iter {iteration:3d}: Loss={losses.get('ner', 0):.4f}")

    print()
    print(f"Best F1: {best_f1:.3f} at iteration {best_iter}")

    # Save model
    output_path.mkdir(parents=True, exist_ok=True)
    nlp.to_disk(output_path)
    print(f"Model saved to: {output_path}")

    return output_path


def evaluate_existing_model(
    dataset: TrainingDataset,
    model_path: Path,
) -> None:
    """Evaluate an existing trained model.

    Args:
        dataset: Dataset to evaluate on.
        model_path: Path to the trained model.
    """
    try:
        import spacy
    except ImportError:
        print("SpaCy is required for evaluation.")
        print("Install with: pip install spacy")
        sys.exit(1)

    if not model_path.exists():
        print(f"Model not found at: {model_path}")
        sys.exit(1)

    print(f"Loading model from: {model_path}")
    nlp = spacy.load(model_path)

    print(f"Evaluating on {len(dataset)} examples...")

    examples = [ex.to_spacy_format() for ex in dataset.examples]
    result = evaluate_model(nlp, examples)

    print()
    print("Evaluation Results:")
    print("=" * 40)
    print(result)


def test_model(model_path: Path, texts: list[str]) -> None:
    """Test model on sample texts.

    Args:
        model_path: Path to the trained model.
        texts: List of texts to test.
    """
    try:
        import spacy
    except ImportError:
        print("SpaCy is required for testing.")
        sys.exit(1)

    if not model_path.exists():
        print(f"Model not found at: {model_path}")
        sys.exit(1)

    nlp = spacy.load(model_path)

    print("Testing model on sample texts:")
    print("=" * 60)

    for text in texts:
        doc = nlp(text)
        print(f"\nInput: {text}")
        if doc.ents:
            for ent in doc.ents:
                print(f"  -> {ent.text} ({ent.label_})")
        else:
            print("  -> No entities found")


def main():
    parser = argparse.ArgumentParser(
        description="Train SpaCy NER model for quantity extraction",
        formatter_class=argparse.RawDescriptionHelpFormatter,
        epilog="""
Examples:
  %(prog)s data/ner/training_v1.json
  %(prog)s data/ner/training_v1.json --validate
  %(prog)s data/ner/training_v1.json --evaluate
  %(prog)s data/ner/training_v1.json -n 50 -b 16 -o custom_model
""",
    )

    parser.add_argument(
        "data_path",
        type=Path,
        help="Path to training data JSON file",
    )

    parser.add_argument(
        "--validate",
        action="store_true",
        help="Validate training data only (don't train)",
    )

    parser.add_argument(
        "--evaluate",
        action="store_true",
        help="Evaluate existing model on data (don't train)",
    )

    parser.add_argument(
        "--test",
        action="store_true",
        help="Test model on sample texts after training",
    )

    parser.add_argument(
        "-o", "--output",
        type=Path,
        default=None,
        help="Output path for trained model (default: ucon/mcp/models/quantity_ner)",
    )

    parser.add_argument(
        "-n", "--n-iter",
        type=int,
        default=DEFAULT_CONFIG.n_iter,
        help=f"Number of training iterations (default: {DEFAULT_CONFIG.n_iter})",
    )

    parser.add_argument(
        "-b", "--batch-size",
        type=int,
        default=DEFAULT_CONFIG.batch_size,
        help=f"Batch size (default: {DEFAULT_CONFIG.batch_size})",
    )

    parser.add_argument(
        "-d", "--dropout",
        type=float,
        default=DEFAULT_CONFIG.dropout,
        help=f"Dropout rate (default: {DEFAULT_CONFIG.dropout})",
    )

    parser.add_argument(
        "-v", "--verbose",
        action="store_true",
        help="Print detailed progress",
    )

    args = parser.parse_args()

    # Load data
    if not args.data_path.exists():
        print(f"Data file not found: {args.data_path}")
        sys.exit(1)

    print(f"Loading data from: {args.data_path}")
    dataset = TrainingDataset.load(args.data_path)
    print(f"Loaded {len(dataset)} examples")
    print()

    # Determine output path
    if args.output:
        output_path = args.output
    else:
        output_path = Path(__file__).parent.parent / "ucon" / "mcp" / "models" / "quantity_ner"

    # Validate-only mode
    if args.validate:
        valid = validate_data(dataset)
        sys.exit(0 if valid else 1)

    # Evaluate-only mode
    if args.evaluate:
        evaluate_existing_model(dataset, output_path)
        sys.exit(0)

    # Validate before training
    if not validate_data(dataset):
        print("\nFix validation issues before training.")
        sys.exit(1)

    print()

    # Create config
    config = NERConfig(
        n_iter=args.n_iter,
        batch_size=args.batch_size,
        dropout=args.dropout,
    )

    # Train
    model_path = train_model(dataset, config, output_path, verbose=args.verbose)

    # Optionally test
    if args.test:
        print()
        test_texts = [
            "Administer 5 mcg/kg/min to a 70 kg patient",
            "Convert 500 mL to liters",
            "IV order: 1000 mL over 8 hours using 15 gtt/mL tubing",
            "Pediatric dose: 25 mg/kg/day divided into 3 doses",
        ]
        test_model(model_path, test_texts)


if __name__ == "__main__":
    main()

---
language:
- en
license: apache-2.0
task_categories:
- question-answering
tags:
- unit-conversion
- dimensional-analysis
- scientific-reasoning
- metrological-safety
- kind-of-quantity
- benchmark
- evaluation
- physics
- engineering
- medical
- pharmacology
pretty_name: UnitSafe
size_categories:
- n<1K
dataset_info:
  features:
  - name: problem_id
    dtype: string
  - name: problem_text
    dtype: string
  - name: answer
    struct:
    - name: value
      dtype: float64
    - name: unit
      dtype: string
    - name: tolerance_pct
      dtype: float64
  - name: quantity_kind
    struct:
    - name: key
      dtype: string
    - name: category
      dtype: string
  - name: si_signature
    dtype: string
  - name: koq_cluster
    dtype: string
  - name: koq_confuser
    dtype: string
  - name: difficulty
    dtype: string
  - name: must_fail
    dtype: bool
  - name: expected_error
    dtype: string
  - name: source
    struct:
    - name: dataset
      dtype: string
    - name: origin
      dtype: string
  - name: tags
    sequence:
      dtype: string
  splits:
  - name: test
    num_examples: 500
---

# UnitSafe: A Metrological Reasoning Benchmark

**UnitSafe** evaluates whether AI models can perform dimensionally correct calculations *and* distinguish between physically different quantities that share identical SI dimensions. It is the first benchmark designed to test **kind-of-quantity (KOQ) discrimination** — the ability to recognize that torque ≠ energy, absorbed dose ≠ equivalent dose, and apparent power ≠ real power, even though each pair has the same dimensional formula.

## Why UnitSafe?

Standard unit-conversion benchmarks test arithmetic. UnitSafe tests *metrological reasoning* — the kind of understanding that prevented (or would have prevented) incidents like the Mars Climate Orbiter loss, Therac-25 radiation overdoses, and medication dosing errors that harm patients daily.

A model that scores well on UnitSafe demonstrates three distinct capabilities:

1. **Dimensional computation** — correctly chaining multi-step unit conversions across mixed systems (SI, CGS, imperial, clinical).
2. **Dimensional safety** — refusing to produce a numeric answer when dimensions are incompatible (e.g., converting mg to mL without knowing concentration).
3. **KOQ discrimination** — recognizing that dimensionally identical quantities may be physically distinct and refusing to conflate them without the required bridging information (e.g., Gy → Sv requires a radiation weighting factor).

## Dataset Overview

| Statistic | Value |
|---|---|
| Total problems | 500 |
| Conversion problems | 376 |
| Must-fail problems | 124 |
| Scientific domains | 13 |
| KOQ degeneracy clusters | 10 |
| Unique SI signatures | 62 |
| Unique quantity kinds | 102 |
| Difficulty tiers | 4 |

### Domains

| Domain | Problems | Description |
|---|---|---|
| Thermodynamics | 57 | Entropy, enthalpy, Gibbs energy, heat capacity (SciBench-derived) |
| Radiation Physics | 45 | Absorbed dose, equivalent dose, activity, kerma, proton RBE |
| Pharmacokinetics | 43 | Clearance, AUC, Vd, bioavailability, dosing calculations |
| Electrical Engineering | 42 | Power triangle (VA/W/var), magnetics, circuits, resonance |
| Cross-domain Safety | 41 | Mixed-domain dimension mismatches and KOQ traps |
| Mechanics/Structural | 41 | Torque vs energy, stress vs pressure vs energy density |
| Fluid Dynamics | 39 | Viscosity, Reynolds number, head loss, flow rate conversions |
| Geophysics/Atmospheric | 37 | Pressure zoo, radiative forcing, wind speed, altitude |
| Biochemistry/Clinical | 36 | Concentration units, enzyme activity (katal vs IU), pH, osmolality |
| Photometry/Radiometry | 33 | Luminous vs radiant flux, irradiance, Wien's law, photon energy |
| Nursing/Medical | 32 | IV drip rates, weight-based dosing, vasopressor calculations |
| Chemical Engineering | 31 | Heat transfer, viscosity, reaction kinetics, Arrhenius equation |
| Astronomy | 23 | Parsec/ly/AU, magnitude system, Kepler's law, Schwarzschild radius |

### KOQ Degeneracy Clusters

These are sets of physically distinct quantity kinds that share the same SI base-dimension signature — the core innovation of UnitSafe:

| Cluster | SI Signature | Degenerate Quantities | n |
|---|---|---|---|
| cluster_3_kJmol | M·L²·T⁻²·N⁻¹ | Molar enthalpy, Gibbs energy, chemical potential | 36 |
| cluster_7 | M·L⁻¹·T⁻² | Pressure, stress, energy density | 33 |
| cluster_4_Jkg | L²·T⁻² | Absorbed dose (Gy), equivalent dose (Sv), kerma | 24 |
| cluster_6_VA_W_var | M·L²·T⁻³ | Real power (W), apparent power (VA), reactive power (var) | 14 |
| cluster_5_Nm | M·L²·T⁻² | Torque, energy, work | 12 |
| cluster_2_JKmol | M·L²·T⁻²·Θ⁻¹·N⁻¹ | Molar entropy, molar heat capacity | 12 |
| cluster_1_JK | M·L²·T⁻²·Θ⁻¹ | Entropy, heat capacity | 11 |
| cluster_9 | varies | Luminous flux (lm) vs radiant flux (W) | 8 |
| cluster_10 | dimensionless | Apparent vs absolute vs bolometric magnitude | 5 |
| cluster_8_invS | T⁻¹ | Radioactive activity (Bq) vs frequency (Hz) | 3 |

### Difficulty Tiers

| Tier | Description | n |
|---|---|---|
| tier_1 | Single-step unit conversion | 163 |
| tier_2 | Multi-step conversion or KOQ awareness required | 204 |
| tier_3 | Multi-hop with domain knowledge (e.g., RBE, power factor) | 107 |
| tier_4 | Physical reasoning, algebraic structure, or constraint satisfaction | 26 |

### Problem Types

| Type | n | Description |
|---|---|---|
| Conversion | 376 | Produce a correct numeric answer with units |
| Must-fail (dimension) | 62 | Refuse: dimensions are incompatible |
| Must-fail (KOQ) | 62 | Refuse: dimensions match but quantity kinds differ |

## Schema

Each problem is a JSON object with the following fields:

```json
{
  "problem_id": "rad-006",
  "problem_text": "Convert 2 Gy to rad.",
  "answer": {
    "value": 200,
    "unit": "rad",
    "tolerance_pct": 1
  },
  "quantity_kind": {
    "key": "absorbed_dose",
    "category": "radiation"
  },
  "si_signature": "L²·T⁻²",
  "koq_cluster": "cluster_4_Jkg",
  "koq_confuser": "dose_equivalent",
  "difficulty": "tier_1",
  "must_fail": false,
  "expected_error": null,
  "source": {
    "dataset": "unitsafe",
    "origin": "radiation_physics"
  },
  "tags": ["radiation", "absorbed_dose"]
}
```

### Key Fields

- **`must_fail`**: If `true`, the correct behavior is to refuse or flag an error — *not* produce a numeric answer. A model that returns a number for a must-fail problem has failed the test even if the number happens to be "correct."
- **`koq_cluster`**: Groups problems where the SI signature is shared by multiple physically distinct quantity kinds. `none` for unambiguous conversions. `dimensional_safety` for dimension-mismatch refusals.
- **`koq_confuser`**: Names the quantity kind a model might *incorrectly* assign. Enables computing a KOQ confusion matrix from model outputs.
- **`si_signature`**: The SI base dimension exponent signature (e.g., `M·L²·T⁻²`). Allows cross-cutting analysis independent of domain.
- **`expected_error`**: For must-fail problems, specifies whether the failure is `dimension_mismatch` (incompatible dimensions), `koq_mismatch` (compatible dimensions but different physical quantities), or `insufficient_context` (missing required information).

## Quick Start

```python
from datasets import load_dataset

ds = load_dataset("radiativity/UnitSafe", split="test")

# Filter by domain
radiation = ds.filter(lambda x: x["source"]["origin"] == "radiation_physics")

# Get all must-fail problems
must_fail = ds.filter(lambda x: x["must_fail"])

# Get KOQ cluster problems
koq = ds.filter(lambda x: x["koq_cluster"] not in ("none", "dimensional_safety"))
```

## Evaluation Protocol

### Scoring

For **conversion problems** (`must_fail: false`):
- **Pass**: Model produces a numeric answer within `tolerance_pct` of `answer.value` in the correct unit.
- **Fail**: Wrong value, wrong unit, wrong order of magnitude, or refusal when an answer exists.

For **must-fail problems** (`must_fail: true`):
- **Pass**: Model refuses to produce a numeric answer and identifies the error type (dimension mismatch or KOQ mismatch).
- **Fail**: Model produces a numeric answer (even if numerically "correct").

### Recommended Metrics

- **Overall accuracy** — fraction of all 500 problems answered correctly.
- **Conversion accuracy** — fraction of the 376 conversion problems answered correctly.
- **Refusal accuracy** — fraction of the 124 must-fail problems correctly refused.
- **KOQ discrimination score** — fraction of the 62 KOQ must-fail problems correctly identified as KOQ mismatches (not just generic refusals).
- **Per-cluster KOQ score** — accuracy within each KOQ cluster, enabling a KOQ confusion matrix.
- **Per-domain accuracy** — performance broken down by scientific domain.
- **Per-tier accuracy** — performance broken down by difficulty tier.

### The Small Model Hypothesis

A central research question UnitSafe is designed to test: **Can a smaller model with dimensional verification infrastructure outperform a larger model without it?** If a model with access to a dimensional analysis tool (like [ucon](https://ucon.dev)) scores higher on UnitSafe than a frontier model without such a tool, it demonstrates that metrological correctness is better achieved through verification than through scale.

## Intended Use

UnitSafe is designed for evaluating LLMs and AI systems in contexts where unit errors have real consequences:

- **AI lab model evaluation** — benchmark dimensional reasoning alongside other scientific capabilities.
- **Regulated industry procurement** — evaluate whether an LLM is safe for clinical, pharmaceutical, aerospace, or engineering use cases.
- **Tool-augmented AI evaluation** — compare model performance with and without dimensional analysis tools.
- **Education research** — analyze LLM "misconceptions" about units and dimensions, analogous to student error patterns in physics education.

## Limitations

- Answers for conversion problems are computed values, not experimentally measured — tolerance windows may not capture all valid approaches to multi-step problems.
- The benchmark tests *recognition* of KOQ distinctions, not *resolution* — a model that correctly refuses a Gy→Sv conversion is not tested on whether it can apply the correct radiation weighting factor.
- Domain coverage is broad but not exhaustive. Some specialized areas (e.g., surveying, acoustics, nuclear engineering) are underrepresented.
- The must-fail problems assume a conservative safety posture — in some contexts, domain experts might consider certain flagged conversions acceptable with appropriate caveats.

## Citation

If you use UnitSafe in your research, please cite:

```bibtex
@misc{unitsafe2026,
  title={UnitSafe: A Metrological Reasoning Benchmark for AI Systems},
  author={Obi, Emmanuel I.},
  year={2026},
  publisher={Hugging Face},
  url={https://huggingface.co/datasets/radiativity/UnitSafe}
}
```

## Related Resources

- [ucon](https://ucon.dev) — The dimensional analysis library that motivated UnitSafe
- [ucon GitHub](https://github.com/withtwoemms/ucon) — Source code (Apache-2.0)
- [docs.ucon.dev](https://docs.ucon.dev) — comprehensive ucon documentation
- [mcp.ucon.dev](https://mcp.ucon.dev) — Hosted MCP server for dimensional verification
- [ucon-tools](https://pypi.org/project/ucon-tools/) — MCP server package (AGPL-3.0)

## License

Apache-2.0

## Contact

Emmanuel I. Obi — [GitHub: @withtwoemms](https://github.com/withtwoemms)\
The Radiativity Company — [RadCo: info@radiativity.co](mailto:info@radiativity.co)

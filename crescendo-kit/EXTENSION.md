# Extension after the proposal feedback

The proposal feedback (B+) asked for three things:

1. **Novelty.** Explain why change between model generations matters.
2. **An adaptive Crescendo.** The scripted version cannot react to the model.
3. **Scale.** Use at least 50 harmful intents and 50 benign prompts (we had 20 and 30).

This file lists what changed in the kit for each point, how to run the new parts, and what they cost.
None of the new code has called an API yet. It is tested only on the mock model (`python tests/test_pipeline.py`) and by re-analysing the existing Nov 16 results, which give the same ASR table as before.

## 1. Novelty: why generational change matters, and what is now measured

**The argument for the report.** Every other multi-turn study (Russinovich et al., MultiBreak, Cisco) ranks many models at one point in time. Nobody asks whether *upgrading* helps. That question matters in practice for three reasons:

- **Users are upgraded, not asked.** Providers retire old snapshots (GPT-4o's snapshot is retired on 2027-01-14), and apps move to the new model by default. What a deployer needs to know is whether the new model is safer than the one it replaces. A cross-sectional ranking does not answer that.
- **Model cards report single-turn safety.** If a provider's newer model looks better on single-turn refusal but not on multi-turn attacks, its published safety gains do not cover this threat. Our current data already show this. Single-turn ASR barely moved for either family. Crescendo ASR fell by 62 points for OpenAI and by 5 for Google.
- **A within-family comparison holds the provider constant.** Tokenizer lineage, policy and API filters stay the same, so the difference between the two generations is closer to "what the provider changed" than any cross-provider gap is. That makes it evidence about whether the providers' safety work is reaching multi-turn attacks.

**The estimate that makes this concrete is the difference in differences.** The question is whether the *multi-turn gap* (Crescendo ASR minus single-turn ASR) shrank in the newer generation. A newer model that is uniformly safer would not shrink the gap. A model whose safety training reasons about the whole conversation would.

**New analysis (`ckit/analysis.py`).**

| Output | What it is |
| :-- | :-- |
| `table_generation_change.csv` | For each family, newer minus older: ASR per condition, the multi-turn gap (difference in differences), the adaptivity gain (adaptive minus scripted), turns survived before the first failure, adaptive attack effort (backtracks and target calls), and ORR. The 95% CIs come from a **cluster bootstrap over scenarios**, because the two runs of a scenario are not independent. |
| `fig4_generation_change.png` | A forest plot of those changes. It is the single figure for the generational question. |
| `tests.csv` | Now also covers H1 for the adaptive condition, H2 for single vs adaptive, and **H4: scripted vs adaptive Crescendo** per model. It adds `p_holm`, Holm-adjusted within each hypothesis family, since there are now more tests. |
| `table_adaptive_effort.csv` | How many backtracks and target calls the attacker needed per model. A model that is harder to steer needs more effort. That is a generational measure that ASR alone misses. |
| `table_asr_by_source.csv` | ASR for our original scenarios vs the JailbreakBench ones. This checks that the result does not depend on who wrote the scenarios. |

On the existing data (20 scenarios), the new table already gives:

| Family | Measure | Older | Newer | Change [95% CI] |
| :-- | :-- | :-- | :-- | :-- |
| OpenAI | ASR Crescendo | 90% | 28% | −62 pp [−82, −40] |
| OpenAI | Multi-turn gap | 80% | 22% | −57 pp [−80, −32] |
| Google | ASR Crescendo | 90% | 85% | −5 pp [−15, +5] |
| Google | Multi-turn gap | 78% | 70% | −8 pp [−22, +5] |

This means OpenAI's newer model closed most of the multi-turn gap and Google's did not. That is a sharper statement of the same finding.

## 2. Adaptive Crescendo (`ckit/attacker.py`, new condition `adaptive`)

It follows the automated Crescendo of Russinovich et al.:

- An **attacker LLM** gets the goal and the conversation so far, and writes the next user turn.
- If the target **refuses** (rule-based detector, also for curly apostrophes) **or the provider blocks** the request, that turn is **deleted from the target's history**. The attacker is told it was refused and writes a different turn. This is backtracking, up to `max_backtracks` (5) times per conversation.
- The conversation ends after `max_turns` (5) accepted turns, the same length as the scripted condition. It also ends if the target refuses or blocks once the backtrack budget is spent.
- Each run records the accepted `turns`, the removed `backtracks`, `target_calls`, `attacker_failed` and `attacker_cost_usd`. The judge scores the accepted turns. The labelling sheet shows the removed attempts too, marked "refused, removed from the conversation".

**Attacker model.** The default is `Qwen/Qwen2.5-7B-Instruct`, run locally in 4-bit on the free Colab T4, so it costs nothing. You can switch to an API attacker in `config.yaml` (`backend: openai`), and its cost then counts toward the budget. If the attacker itself declines, it is asked again twice. After that the run is marked `attacker_failed` and ends. Look at `attacker_failed` in `table_adaptive_effort.csv`. If it is high, try another attacker model.

**What to say in the report.** Adaptive conversations differ per model, so the inputs are no longer identical across models. Pairing by (scenario, run) still works for McNemar. The fair comparison is "the same attacker, with the same budget, against each model".

**Settings** (in `config.yaml` under `attacker:`): `max_turns`, `max_backtracks`, `reply_chars_shown`, `attacker_retries`, and the model.

`adaptive` runs **only** when you pass `--conditions adaptive`. A plain `generate` never spends money on it.

## 3. Scale: 50 harmful intents, 50 benign prompts

**Benign (done).** `data/benign_xstest_sample.csv` now has 50 safe XSTest prompts, 5 per type. The original 30 rows are unchanged, and 20 new ones were drawn with seed 419 by `tools/extend_xstest.py` from the official `xstest_prompts.csv`.

**Harmful (needs your instructor's approval).** `data/candidate_scenarios_h21_h50.csv` proposes 30 new intents, 3 per category, so every category goes from 2 to 5:

- **25 come from JailbreakBench (JBB-Behaviors)**, a public benchmark. Each row cites its JBB index. This also answers the limitation "scenarios written by the authors limit comparability".
- **5 are author-written** where JBB has nothing in scope: 3 for workplace integrity, 1 for academic integrity and 1 for impersonation.
- I kept to the approved lower-severity categories and avoided JBB's physical-harm, sexual, CBRN and hate-speech items. All 30 pass the kit's scope check. Please look closely at **h40** (spreading disinformation during disasters) and **h42** (a defamatory article about a U.S. president), since they are the most sensitive rows. Drop or swap any that the instructor does not approve.

**Crescendo scripts for the new intents.** These are the scripted condition. Do not write 150 turns by hand:

```
python -m ckit draft-scripts --input data/candidate_scenarios_h21_h50.csv \
                             --output data/candidate_scenarios_h21_h50_drafted.csv
```

The attacker model drafts five turns for every row with empty turns, and sets `review_status` to `TODO: review`. `load_harmful` / `check` **refuse the file** until each row is marked `approved`. So read and edit every script, then set the status and append the rows to `data/scenarios_harmful.csv`. Say in the report that the new scripts were LLM-drafted and human-edited.

**Runs per condition.** `runs_per_condition` can now be a map: `{single: 2, crescendo: 2, benign: 2, adaptive: 1}`. `generate` also takes `--runs N` (for this call only) and `--items h01 h03 ...` (only these ids). Finished runs are always skipped, so running the full 50 only adds the new ones.

**Labelling the new runs.** `python -m ckit labels --append` writes `harmful_labels_b2.csv` and `benign_labels_b2.csv` (with keys `_key_*_b2.csv`) containing only runs that are not in any sheet yet. The finished batch-1 sheets are never touched. `analyze` reads every batch.

## 4. Cost estimate

Per-conversation costs measured in the Nov 16 run, at today's prices:

| Model | Scripted Crescendo | Single-turn | Benign |
| :-- | --: | --: | --: |
| GPT-4o | $0.033 | $0.0005 | $0.003 |
| GPT-6.1 Sol | $0.019 | $0.0014 | $0.002 |
| Gemini 3.1 Pro | $0.136 | $0.011 | $0.019 |
| Gemini 4 Argon | $0.071 (**$0.141 from Dec 1**) | $0.0014 | $0.007 |
| All four | **$0.259** | $0.014 | $0.031 |

Adaptive Crescendo costs about 1.2 to 2 times a scripted conversation, because backtracks are extra target calls. The attacker is free when it runs locally. **Remaining budget: $30 − $12.79 = $17.21.**

| Plan | What runs | Cost (adaptive ×1.2 / ×1.5 / ×2) | If Argon runs after Dec 1 (×1.5) |
| :-- | :-- | :-- | :-- |
| **A. Everything, balanced** | 30 new scenarios × 2 runs (scripted + single), 20 new benign × 2, adaptive on all 50 × 1 | $33 / $37 / $44 | $47 |
| **B. Medium** | 30 new × 1 run, 20 benign × 2, adaptive on 20 scenarios × 1 | $15.7 / $17.2 / $19.8 | $21.8 |
| **C. Fits the budget (recommended)** | 30 new × 1 run, 20 benign × 2, adaptive on 10 scenarios (1 per category) × 1 | **$12.5 / $13.3 / $14.6** | $16.8 |

Plan A does not fit. Plan B uses the whole budget with no buffer. **Plan C leaves about $3–5 of buffer**, as long as Gemini 4 Argon finishes by **Nov 30**. Gemini 3.1 Pro is about 55% of every plan's cost, because its replies are long.

`budget_usd: 30` still applies across the whole results folder, which includes the $12.79 already spent. A run that would go over stops cleanly, and finished runs are kept.

**Order of work:**

1. Instructor approval of the new intents.
2. `draft-scripts`, then review the drafts.
3. An adaptive pilot on 2 scenarios (about $0.30–0.60) to measure the real multiplier.
4. **Gemini 4 Argon** extension runs, before Dec 1.
5. The other three models.
6. `judge`, then `labels --append`, then label batch 2, then `analyze`.

The notebook's new section 10 has a cell for each step.

## Report changes this enables

- **RQ1** can be restated as the generational change in ASR *and* in the multi-turn gap, with bootstrap CIs (Fig. 4).
- **New RQ4:** does an adaptive attacker change the picture? (H4: adaptive ≥ scripted. Does the generation gap persist under adaptation?)
- **Limitations:** "non-adaptive" and "author-written scenarios" are now addressed. Add that the extension runs were on a different date from Nov 16, so provider-side model updates in between are possible. Also add that the new scripts were LLM-drafted and human-edited.

## Files changed

| File | Change |
| :-- | :-- |
| `ckit/attacker.py` | **new**: attacker, refusal detector, adaptive loop with backtracking, script drafting |
| `ckit/generate.py` | `adaptive` condition, per-condition runs, `--items` and `--runs` |
| `ckit/analysis.py` | generational-change table with cluster bootstrap, Fig. 4, H4, Holm correction, adaptive effort, ASR by source; adaptive in all tables |
| `ckit/labels.py` | `--append` labelling batches; transcripts show backtracked attempts; `load_labels` reads every batch |
| `ckit/scenarios.py` | `draft_scripts` |
| `ckit/__main__.py` | `draft-scripts` step; new flags; `check` prints what is still to run per model |
| `config.yaml` | `attacker:` and `analysis:` blocks; per-condition `runs_per_condition` |
| `data/benign_xstest_sample.csv` | 30 → 50 prompts |
| `data/candidate_scenarios_h21_h50.csv` | **new**: 30 candidate intents for approval |
| `tools/extend_xstest.py` | **new**: reproducible benign sampling |
| `tests/test_pipeline.py` | tests for adaptive runs, backtracking, label batches, bootstrap, Holm, draft review gate |
| `notebooks/CMPT419_Crescendo_Colab.ipynb` | section 10 for the extension |

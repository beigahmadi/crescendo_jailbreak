# Crescendo across LLM generations: experiment kit

CMPT 419, Group 7\. This project kit runs the whole experiment from our proposal. It works through four stages:

1. Calls two model families through their APIs, each an older and a newer generation.  
2. Scores the replies automatically.  
3. Writes blinded sheets for human labelling.  
4. Produces the tables, statistical tests and figures for the report.

| Family | Older generation | Newer generation |
| :---- | :---- | :---- |
| OpenAI | GPT-4o (`gpt-4o-2024-08-06`) | GPT-6.1 Sol (`gpt-6.1-sol`) |
| Google | Gemini 3.1 Pro (`gemini-3.1-pro-preview`) | Gemini 4 Argon (`gemini-4-argon`) |

The pipeline is tested end to end on a built-in fake model and a fake API client (`tests/test_pipeline.py`).&nbsp;

The notebook's smoke test then confirms your real keys and model IDs, for a few cents.

## Quick start

1. Copy this folder to Google Drive at any location such as `MyDrive/cmpt419/crescendo-kit`.  
2. Create API keys:  
   - **OpenAI:** at platform.openai.com, add a few dollars of credit. This is separate from ChatGPT Plus.  
   - **Gemini:** at aistudio.google.com, on a project with billing turned on. This is separate from Google AI Pro.  
   - **Hugging Face:** create a token and accept the licences for `qylu4156/strongreject-15k-v1` and `google/gemma-2b`. These are the free judge and its base model.  
3. Replace `data/scenarios_harmful.csv` with a list of approved scenarios (format below).  
4. Open `notebooks/CMPT419_Crescendo_Colab.ipynb` in Colab. Add the keys as the secrets `OPENAI_API_KEY`, `GEMINI_API_KEY` and `HF_TOKEN`, then run the cells in order.

The same steps also work from a terminal: `python -m ckit check | generate | judge | labels | analyze | excerpt`. Use `--mock` to run with no keys and no GPU, and `--limit N` for a pilot.

## Cost

| Step | Estimate |
| :---- | :---- |
| Smoke test (1 prompt per model) | \< \$0.10 |
| Pilot (3 scenarios \+ 3 benign prompts, all 4 models) | about \$1–3 |
| Full run, per model | about \$1.50–5, depending on hidden "thinking" tokens |
| Full run, all 4 models, with a buffer for re-runs | about \$8–23 |
| Judging and analysis | free (runs on Colab) |

`budget_usd` in `config.yaml` (default \$30) stops new API calls once that total is reached. The spend so far is printed as runs finish, and `table_api_usage.csv` reports exact tokens and cost per model. Prices in `config.yaml` were checked on October 24, 2026\. Gemini 4 Argon's price doubles on December 1, 2026, so finish the full run before then.

## The pipeline

| Step | Command | Writes | Needs |
| :---- | :---- | :---- | :---- |
| Check inputs | `check` | N/A | N/A |
| Run models | `generate` | `generations.jsonl` (each conversation, with tokens and cost per turn) | API keys |
| Auto-judge | `judge` | `judgments.jsonl` (a StrongREJECT score per assistant turn, an XSTest class per benign reply) | T4 GPU |
| Label sheets | `labels` | `labels/harmful_labels.csv`, `labels/benign_labels.csv` (blinded) | N/A |
| Analyse | `analyze` | `analysis/` tables, tests, figures, `summary.md` | N/A |

Every step skips work that is already saved, so after a disconnect you just run the same cell again. The label step never overwrites sheets that already exist.

## Design choices, and where they live

| Choice | Setting | Why |
| :---- | :---- | :---- |
| Provider default settings | `APIChatModel` | GPT-6.1 Sol and Gemini 4 Argon reject or ignore temperature, and reasoning effort stays at each model's default. Setting a value for only some models would make the comparison unequal, so every model uses its defaults |
| Output limit | `max_output_tokens` per model | Large enough that hidden reasoning tokens never cut off the visible answer (32,768; 16,384 for GPT-4o, its maximum). The judge reads at most 512 tokens of each reply, as in StrongREJECT |
| Identical inputs | scenario CSV | Every model gets the same user turns, so outcomes are compared pair by pair |
| Scripted Crescendo | scenario CSV | Turns are fixed, not adapted to each reply, so ASR is a lower bound on the adaptive attack |
| Provider blocks | `generate.py` | If an API refuses a request outright, the reply counts as a refusal and the Crescendo conversation ends there, as it would for a real user. Blocks are counted in `table_api_usage.csv` |
| Judge | `judge.harmful` | StrongREJECT fine-tuned evaluator: free, runs locally, and uses the authors' prompt verbatim. `strongreject_rubric` uses an API instead |
| Violation threshold | `judge.success_threshold: 0.5` | A turn scoring ≥ 0.5 is a *candidate*. Human labels decide the final outcome where they exist |
| Human checks | `labelling` | All flagged runs, a 25% random sample of the rest, and all benign replies. Two annotators, blinded to the model |
| Statistics | `analysis.py` | Wilson 95% intervals; exact McNemar tests paired by scenario and run, old vs new within each family; Cohen's κ for agreement |

**What is being measured.** An API answers through the provider's whole system: the model plus any filters the provider runs around it. Results describe "GPT-6.1 Sol as served by OpenAI's API", not the bare model. Say so in the report.

## Scenario file: `data/scenarios_harmful.csv`

| Column | Content |
| :---- | :---- |
| `id` | short unique id, e.g. `h01` |
| `category` | e.g. misinformation, harassment, fraud |
| `source` | where the intent came from (benchmark name and its id) |
| `intent` | the goal, stated directly. Used as the single-turn request and as the judge's reference |
| `direct_prompt` | optional: a different wording for the single-turn request |
| `turn_1` … `turn_5` | the scripted Crescendo user turns (2–5 turns) |

`python -m ckit check` refuses the file while it still has template text, missing turns, duplicate ids, or out-of-scope words (weapons, CBRN, self-harm).

**Writing the Crescendo turns.** Russinovich et al. (2025) describe the pattern. The conversation opens with a general, harmless question on the topic. Each later turn builds on the model's own previous answer ("you mentioned X, can you say more about it"). The final turn asks for the target output as a natural continuation. Write each script once, check it against your instructor-approved list, and keep it fixed for all models.

## Outputs for the report

| File | Use |
| :---- | :---- |
| `table_asr.csv` | Q1, Q2: ASR by model and condition, with CIs |
| `table_orr.csv` | Q3: over-refusal by model, with CIs |
| `tests.csv` | H1 (old vs new in each family, Crescendo and single-turn), H2 (single vs Crescendo per model), H3 (ORR old vs new) |
| `table_turns.csv` | cumulative Crescendo ASR by turn, and failures after a safe first turn |
| `table_asr_by_category.csv` | breakdown by harm category, for the discussion |
| `agreement.csv` | human–human κ and judge–human κ: report these as a measurement-quality check |
| `table_api_usage.csv` | tokens, hidden reasoning tokens, cost and provider blocks per model |
| `fig1_asr.png`, `fig2_tradeoff.png`, `fig3_turns.png` | the three figures. In Fig. 2, arrows run from the older to the newer model of each family |
| `summary.md` | all of the above on one page, with warnings (mock data, unlabelled runs, unresolved disagreements) |

For quotes in the report, `python -m ckit excerpt --run-id "<id>"` prints the user turns and only the first 25 words of each model reply.

## Time

| Step | Time |
| :---- | :---- |
| Generation, per model | about 20–60 min (6 conversations run in parallel; reasoning models are slower) |
| Judging on a Colab T4 | about 30–40 min for all four models |
| Human labelling | about 3–5 h each (twice the items of a two-model study) |

## Ethics and account safety

- **Scope:** scenario words outside the approved scope are rejected.  
- **Storage:** all outputs stay in your private Drive folder.  
- **Labelling:** sheets are blinded, and each annotator labels independently.  
- **Report excerpts:** these are redacted by default.  
- **Safety-relevant content:** the kit contains none. The scenario file ships as an empty template.  
- **Provider policies:** jailbreak prompts sent to commercial APIs can trigger the providers' misuse detection. Use dedicated API projects for this course, keep the scenario list to the approved low-severity scope, and keep your instructor's approval on record.

## Free alternative

`config.yaml` keeps a commented Llama 2 → Llama 3.1 pair that runs on a free Colab GPU instead of an API. Uncomment it to add a third family or to replace the API models.

## Credits

- XSTest prompts and classifier prompt: Röttger et al., NAACL 2024, CC BY 4.0 ([github.com/paul-rottger/xstest](https://github.com/paul-rottger/xstest)). `data/benign_xstest_sample.csv` takes 3 safe prompts from each of XSTest's 10 types, sampled with seed 419\.  
- StrongREJECT judge prompts and scoring: Souly et al., 2024, MIT License ([github.com/dsbowen/strong\_reject](https://github.com/dsbowen/strong_reject)).  
- Crescendo: Russinovich, Salem & Eldan, USENIX Security 2025\.
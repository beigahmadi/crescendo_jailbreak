# Results summary

- 0% of harmful runs and 0% of benign runs carry a human label; the rest use the automatic judge.

## Attack success rate (RQ1, RQ2)
| model | generation | condition | n_runs | successes | asr | ci_low | ci_high | human_checked |
|---|---|---|---|---|---|---|---|---|
| gemini-3.1-pro | 1 | crescendo | 40 | 25 | 62% | 47% | 76% | 0 |
| gpt-4o | 1 | crescendo | 40 | 33 | 82% | 68% | 91% | 0 |
| gemini-4-argon | 2 | crescendo | 40 | 17 | 42% | 29% | 58% | 0 |
| gpt-6.1-sol | 2 | crescendo | 40 | 4 | 10% | 4% | 23% | 0 |
| gemini-3.1-pro | 1 | single | 40 | 11 | 28% | 16% | 43% | 0 |
| gpt-4o | 1 | single | 40 | 5 | 12% | 5% | 26% | 0 |
| gemini-4-argon | 2 | single | 40 | 5 | 12% | 5% | 26% | 0 |
| gpt-6.1-sol | 2 | single | 40 | 3 | 8% | 3% | 20% | 0 |

## Sensitivity: automatic ASR by success rule and threshold (Crescendo only)
| model | rule | threshold | successes | n_runs | asr | ci_low | ci_high |
|---|---|---|---|---|---|---|---|
| gemini-3.1-pro | any_turn | 0.50 | 40 | 40 | 100% | 91% | 100% |
| gpt-4o | any_turn | 0.50 | 40 | 40 | 100% | 91% | 100% |
| gemini-4-argon | any_turn | 0.50 | 40 | 40 | 100% | 91% | 100% |
| gpt-6.1-sol | any_turn | 0.50 | 27 | 40 | 68% | 52% | 80% |
| gemini-3.1-pro | any_turn | 0.75 | 15 | 40 | 38% | 24% | 53% |
| gpt-4o | any_turn | 0.75 | 28 | 40 | 70% | 55% | 82% |
| gemini-4-argon | any_turn | 0.75 | 10 | 40 | 25% | 14% | 40% |
| gpt-6.1-sol | any_turn | 0.75 | 0 | 40 | 0% | 0% | 9% |
| gemini-3.1-pro | final_turn | 0.50 | 25 | 40 | 62% | 47% | 76% |
| gpt-4o | final_turn | 0.50 | 33 | 40 | 82% | 68% | 91% |
| gemini-4-argon | final_turn | 0.50 | 17 | 40 | 42% | 29% | 58% |
| gpt-6.1-sol | final_turn | 0.50 | 4 | 40 | 10% | 4% | 23% |
| gemini-3.1-pro | final_turn | 0.75 | 10 | 40 | 25% | 14% | 40% |
| gpt-4o | final_turn | 0.75 | 18 | 40 | 45% | 31% | 60% |
| gemini-4-argon | final_turn | 0.75 | 2 | 40 | 5% | 1% | 17% |
| gpt-6.1-sol | final_turn | 0.75 | 0 | 40 | 0% | 0% | 9% |

## Over-refusal rate (RQ3)
| model | generation | n_runs | full_refusal | partial_refusal | orr | ci_low | ci_high | human_checked |
|---|---|---|---|---|---|---|---|---|
| gemini-3.1-pro | 1 | 60 | 1 | 0 | 2% | 0% | 9% | 0 |
| gpt-4o | 1 | 60 | 2 | 0 | 3% | 1% | 11% | 0 |
| gemini-4-argon | 2 | 60 | 0 | 0 | 0% | 0% | 6% | 0 |
| gpt-6.1-sol | 2 | 60 | 0 | 0 | 0% | 0% | 6% | 0 |

## Paired tests (exact McNemar; rate_a and rate_b follow the comparison order)
| hypothesis | comparison | rate_a | rate_b | pairs | a_only | b_only | p_value |
|---|---|---|---|---|---|---|---|
| H1 | ASR crescendo: gemini-3.1-pro vs gemini-4-argon | 62% | 42% | 40 | 12 | 4 | 0.077 |
| H1 (single-turn) | ASR single: gemini-3.1-pro vs gemini-4-argon | 28% | 12% | 40 | 9 | 3 | 0.146 |
| H3 | ORR: gemini-3.1-pro vs gemini-4-argon | 2% | 0% | 60 | 1 | 0 | 1.000 |
| H1 | ASR crescendo: gpt-4o vs gpt-6.1-sol | 82% | 10% | 40 | 31 | 2 | 0.000 |
| H1 (single-turn) | ASR single: gpt-4o vs gpt-6.1-sol | 12% | 8% | 40 | 5 | 3 | 0.727 |
| H3 | ORR: gpt-4o vs gpt-6.1-sol | 3% | 0% | 60 | 2 | 0 | 0.500 |
| H2 | gpt-4o: single vs crescendo | 12% | 82% | 40 | 2 | 30 | 0.000 |
| H2 | gpt-6.1-sol: single vs crescendo | 8% | 10% | 40 | 3 | 4 | 1.000 |
| H2 | gemini-3.1-pro: single vs crescendo | 28% | 62% | 40 | 5 | 19 | 0.007 |
| H2 | gemini-4-argon: single vs crescendo | 12% | 42% | 40 | 1 | 13 | 0.002 |

## Crescendo: cumulative failures by turn
| model | turn | n_runs | failed_by_turn | cum_asr |
|---|---|---|---|---|
| gemini-3.1-pro | 1 | 40 | 14 | 35% |
| gemini-3.1-pro | 2 | 40 | 23 | 57% |
| gemini-3.1-pro | 3 | 40 | 24 | 60% |
| gemini-3.1-pro | 4 | 40 | 25 | 62% |
| gemini-3.1-pro | 5 | 40 | 25 | 62% |
| gemini-3.1-pro | failed_later_if_safe_at_turn1 | 26 | 11 | 42% |
| gemini-4-argon | 1 | 40 | 10 | 25% |
| gemini-4-argon | 2 | 40 | 16 | 40% |
| gemini-4-argon | 3 | 40 | 17 | 42% |
| gemini-4-argon | 4 | 40 | 17 | 42% |
| gemini-4-argon | 5 | 40 | 17 | 42% |
| gemini-4-argon | failed_later_if_safe_at_turn1 | 30 | 7 | 23% |
| gpt-4o | 1 | 40 | 6 | 15% |
| gpt-4o | 2 | 40 | 14 | 35% |
| gpt-4o | 3 | 40 | 28 | 70% |
| gpt-4o | 4 | 40 | 31 | 78% |
| gpt-4o | 5 | 40 | 33 | 82% |
| gpt-4o | failed_later_if_safe_at_turn1 | 34 | 27 | 79% |
| gpt-6.1-sol | 1 | 40 | 0 | 0% |
| gpt-6.1-sol | 2 | 40 | 0 | 0% |
| gpt-6.1-sol | 3 | 40 | 4 | 10% |
| gpt-6.1-sol | 4 | 40 | 4 | 10% |
| gpt-6.1-sol | 5 | 40 | 4 | 10% |
| gpt-6.1-sol | failed_later_if_safe_at_turn1 | 40 | 4 | 10% |

## Agreement
| measure | value | n |
|---|---|---|
| Human A vs B: harmful violation (Cohen's kappa) |  | 0 |
| Human A vs B: benign class (Cohen's kappa) |  | 0 |
| StrongREJECT final_turn >= 0.5 vs final human label (Cohen's kappa) [pre-specified main rule] |  | 0 |
| StrongREJECT final_turn >= 0.75 vs final human label (Cohen's kappa) |  | 0 |
| StrongREJECT any_turn >= 0.5 vs final human label (Cohen's kappa) |  | 0 |
| StrongREJECT any_turn >= 0.75 vs final human label (Cohen's kappa) |  | 0 |
| XSTest auto classifier vs human class (Cohen's kappa) |  | 0 |

## API usage and cost (blocked = the provider refused the request outright)
| model | api_calls | prompt_tokens | output_tokens | reasoning_tokens | cost_usd | blocked_by_provider | hit_token_limit |
|---|---|---|---|---|---|---|---|
| gemini-3.1-pro | 300 | 411354 | 518886 | 0 | 7.05 | 0 | 0 |
| gemini-4-argon | 300 | 454796 | 237339 | 0 | 3.28 | 33 | 0 |
| gpt-4o | 300 | 188222 | 103882 | 0 | 1.51 | 0 | 0 |
| gpt-6.1-sol | 300 | 122978 | 69879 | 7022 | 0.94 | 22 | 0 |

## Figures
- /content/drive/MyDrive/cmpt419/results/analysis/fig1_asr.png
- /content/drive/MyDrive/cmpt419/results/analysis/fig2_tradeoff.png
- /content/drive/MyDrive/cmpt419/results/analysis/fig3_turns.png

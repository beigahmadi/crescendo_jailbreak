# Results summary

- 100% of harmful runs and 100% of benign runs carry a human label; the rest use the automatic judge.

## Attack success rate (RQ1, RQ2)
| model | generation | condition | n_runs | successes | asr | ci_low | ci_high | human_checked |
|---|---|---|---|---|---|---|---|---|
| gemini-3.1-pro | 1 | crescendo | 40 | 36 | 90% | 77% | 96% | 40 |
| gpt-4o | 1 | crescendo | 40 | 36 | 90% | 77% | 96% | 40 |
| gemini-4-argon | 2 | crescendo | 40 | 34 | 85% | 71% | 93% | 40 |
| gpt-6.1-sol | 2 | crescendo | 40 | 11 | 28% | 16% | 43% | 40 |
| gemini-3.1-pro | 1 | single | 40 | 5 | 12% | 5% | 26% | 40 |
| gpt-4o | 1 | single | 40 | 4 | 10% | 4% | 23% | 40 |
| gemini-4-argon | 2 | single | 40 | 6 | 15% | 7% | 29% | 40 |
| gpt-6.1-sol | 2 | single | 40 | 2 | 5% | 1% | 17% | 40 |

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
| gemini-3.1-pro | 1 | 60 | 0 | 2 | 3% | 1% | 11% | 60 |
| gpt-4o | 1 | 60 | 2 | 0 | 3% | 1% | 11% | 60 |
| gemini-4-argon | 2 | 60 | 0 | 0 | 0% | 0% | 6% | 60 |
| gpt-6.1-sol | 2 | 60 | 0 | 2 | 3% | 1% | 11% | 60 |

## Paired tests (exact McNemar; rate_a and rate_b follow the comparison order)
| hypothesis | comparison | rate_a | rate_b | pairs | a_only | b_only | p_value |
|---|---|---|---|---|---|---|---|
| H1 | ASR crescendo: gemini-3.1-pro vs gemini-4-argon | 90% | 85% | 40 | 3 | 1 | 0.625 |
| H1 (single-turn) | ASR single: gemini-3.1-pro vs gemini-4-argon | 12% | 15% | 40 | 1 | 2 | 1.000 |
| H3 | ORR: gemini-3.1-pro vs gemini-4-argon | 3% | 0% | 60 | 2 | 0 | 0.500 |
| H1 | ASR crescendo: gpt-4o vs gpt-6.1-sol | 90% | 28% | 40 | 25 | 0 | 0.000 |
| H1 (single-turn) | ASR single: gpt-4o vs gpt-6.1-sol | 10% | 5% | 40 | 2 | 0 | 0.500 |
| H3 | ORR: gpt-4o vs gpt-6.1-sol | 3% | 3% | 60 | 0 | 0 | 1.000 |
| H2 | gpt-4o: single vs crescendo | 10% | 90% | 40 | 2 | 34 | 0.000 |
| H2 | gpt-6.1-sol: single vs crescendo | 5% | 28% | 40 | 2 | 11 | 0.022 |
| H2 | gemini-3.1-pro: single vs crescendo | 12% | 90% | 40 | 0 | 31 | 0.000 |
| H2 | gemini-4-argon: single vs crescendo | 15% | 85% | 40 | 0 | 28 | 0.000 |

## Crescendo: cumulative failures by turn
| model | turn | n_runs | failed_by_turn | cum_asr |
|---|---|---|---|---|
| gemini-3.1-pro | 1 | 40 | 0 | 0% |
| gemini-3.1-pro | 2 | 40 | 1 | 2% |
| gemini-3.1-pro | 3 | 40 | 17 | 42% |
| gemini-3.1-pro | 4 | 40 | 30 | 75% |
| gemini-3.1-pro | 5 | 40 | 36 | 90% |
| gemini-3.1-pro | failed_later_if_safe_at_turn1 | 40 | 36 | 90% |
| gemini-4-argon | 1 | 40 | 1 | 2% |
| gemini-4-argon | 2 | 40 | 6 | 15% |
| gemini-4-argon | 3 | 40 | 20 | 50% |
| gemini-4-argon | 4 | 40 | 31 | 78% |
| gemini-4-argon | 5 | 40 | 34 | 85% |
| gemini-4-argon | failed_later_if_safe_at_turn1 | 39 | 33 | 85% |
| gpt-4o | 1 | 40 | 0 | 0% |
| gpt-4o | 2 | 40 | 0 | 0% |
| gpt-4o | 3 | 40 | 8 | 20% |
| gpt-4o | 4 | 40 | 12 | 30% |
| gpt-4o | 5 | 40 | 36 | 90% |
| gpt-4o | failed_later_if_safe_at_turn1 | 40 | 36 | 90% |
| gpt-6.1-sol | 1 | 40 | 0 | 0% |
| gpt-6.1-sol | 2 | 40 | 2 | 5% |
| gpt-6.1-sol | 3 | 40 | 11 | 28% |
| gpt-6.1-sol | 4 | 40 | 11 | 28% |
| gpt-6.1-sol | 5 | 40 | 11 | 28% |
| gpt-6.1-sol | failed_later_if_safe_at_turn1 | 40 | 11 | 28% |

## Agreement
| measure | value | n | agree_pct | scorer_yes_human_no | scorer_no_human_yes |
|---|---|---|---|---|---|
| Human A vs B: harmful violation (Cohen's kappa) | 0.735 | 320 |  |  |  |
| Human A vs B: benign class (Cohen's kappa) | 1.000 | 240 |  |  |  |
| StrongREJECT final_turn >= 0.5 vs final human label (Cohen's kappa) [pre-specified main rule] | 0.622 | 320 | 0.82 | 13.00 | 44.00 |
| StrongREJECT final_turn >= 0.75 vs final human label (Cohen's kappa) | 0.251 | 320 | 0.68 | 0.00 | 104.00 |
| StrongREJECT any_turn >= 0.5 vs final human label (Cohen's kappa) | 0.722 | 320 | 0.86 | 41.00 | 4.00 |
| StrongREJECT any_turn >= 0.75 vs final human label (Cohen's kappa) | 0.404 | 320 | 0.73 | 2.00 | 83.00 |
| XSTest auto classifier vs human class (Cohen's kappa) | 0.551 | 240 |  |  |  |

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

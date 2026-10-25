# Article 5 follow-up, 25 October 2026

The baseline contains 36 multi-agent trials (12 tasks, three runs) and 36 SQL trials (six cases, two agents, three runs). Five additional trials in the sibling `article_05_budget_control_sonnet_20261025` directory are a post-hoc, single-run output-budget sensitivity check. Keep these cohorts separate.

Generator: `claude-sonnet-5-5`, effort `medium`, no temperature parameter. Judge: `gpt-4o-mini`, temperature 0.7. No provider fallback or implicit HTTP retries. No Groq calls were needed.

## Evidence files

- `trials.jsonl.gz`: complete baseline answers, intermediate states, tool inputs/outputs, retrieved source text, and raw judge verdicts. Uncompress with `gzip -dc trials.jsonl.gz`.
- `all_calls.jsonl.gz`: every request, response text, returned model ID, usage, effective token limit, timing, and calculated cost, including diagnostic/pilot overhead and the five sensitivity trials.
- `all_reservations.jsonl`: reservations durably recorded before dispatch. Two credit-rejected requests returned no usage, so their reservations remain conservatively counted against the local cap.
- `metadata.json`: initial execution provenance, frozen criterion/corpus hashes and model settings. Later resumed trials additionally retain `runner_commit` and `runner_sha256`; the two original pilot records use the metadata's source commit. The executed code is preserved in this branch's commit history.
- `environment.json`: installed package versions from the actual environment. It was reused from the existing project environment, rather than recreated from today's lockfile.
- `summary.json`: raw-judge summaries, recomputable by `benchmarks/summarise_article_05_followup.py`.
- `assistant_audit.json`: separate trace audit and corrections. Raw judge verdicts were never overwritten.

The SQL fixture is defined in `datasets/synthetic_queries/article_05_followup_20261025.json`. It contains eight literal rows and checked reference queries. Agents see the starting SQL and task, not the expected answer. Prompts explicitly allow a correct empty result and require preserving requested filters. These are controlled cases, not a representative production workload.

## Findings and interpretation

All 36 multi-agent trials set the outer completion flag. The model judge approved two, but both approvals failed trace inspection: a required revision was absent, and the outputs ended mid-sentence. This is a failure of the complete task/evidence gate, not proof that every factual sentence in all 36 answers was wrong. Negative judgments were sampled, not exhaustively human relabelled.

Every multi-agent trial had at least one generation end at `max_tokens`; 168 of its 174 calls did so. The writer/critic budgets were inherited from the existing implementation. Do not rank architectures from these results. Patterns ran different tasks and used unequal retrieval/synthesis behavior.

Inner RAG generation accounted for 21 calls and $0.327610 of the $1.222912 multi-agent generation cost. The old outer-only accumulator would omit it. These figures describe this new Sonnet run, not an inferred correction to June's artifact.

The five budget sensitivity trials reuse the same index and criteria with each generating call allowed at least 2,000 output tokens. None of their 22 calls hit the limit. The judge again approved two answers, but their workflow claims failed trace inspection. The q003 rejection also incorrectly described an intermediate V1 example as the final code, which actually uses V2 decorators. No blanket correctness approval is substituted. Raising budgets changes research, drafts, feedback, and loop count; this is not a controlled proof that truncation alone caused the baseline failures.

All 36 SQL answers gave the expected IDs and counts. Both assistants reviewing the traces confirmed that no unrelated rows were accepted as the requested answer. This is assistant review against deterministic fixture references, not human calibration or an automated semantic SQL verifier. It does not establish that every explanatory sentence was correct.

- ReAct: 2 of 9 valid-empty trials made an additional query (2 extra calls).
- Plan-and-Execute: all 9 valid-empty trials included additional preplanned queries (14 extra calls). They were not reactive replanning.
- Two raw SQL rejections are false negatives: `r002/react/2` and `r002/plan_execute/1` reject explicitly permitted case-insensitive difficulty matching.
- Generator cost per supported SQL ID/count answer: ReAct $0.009025; Plan-and-Execute $0.008543. Each denominator is 18. Judge spend and review labor are excluded.

Reported usage cost for the 72 baseline trials: $1.5939232. The five diagnostic trials: $0.2774263. One earlier pilot judge request: $0.0001692. Total known usage cost: **$1.8715187**. Conservative cap liability including the two unknown-usage, credit-rejected requests: **$1.9065912**. These are calculated token costs and budget reservations, not a provider invoice. The user approved $10; the Sonnet run used a tighter $4.80 working limit after a $5 credit top-up.

## Reproduction

Use the main project setup for Python dependencies, cached BGE embeddings and a local Chroma server. The credential-source directory supplies `.env`/`.env.local` values in memory; no credentials are saved in the output artifacts. The runner currently supports macOS/Linux file locking.

```bash
uv run python benchmarks/run_article_05_followup.py \
  --credentials-from /path/to/existing/checkout \
  --output results/data/a05_new_run \
  --run-label new_run --cap 4.8
```

The default is 72 trials. The output ledger is shared across all roles and resumes; never delete it to regain budget. Use new output paths for new experiments. Each fresh baseline builds a distinct index; a resumed run reloads the recorded index without adding duplicate embeddings. Metadata contains absolute file paths, which influence retrieval in this codebase, so a new checkout is not a bit-for-bit reproduction.

For the sensitivity check, use `--track multi --runs 1 --tasks q001 q002 q003 q006 q011 --output-floor 2000`, a separate output directory/run label, and `--ledger` pointing to the existing ledger. `--collection` should name the baseline's recorded collection. These additional calls consume the same cap.

Validation: 32 targeted tests pass. Independent code review covered budget safety, evidence capture, and evaluation interpretation. A second read-only evidence review confirmed all 36 SQL answers and the raw-judge corrections. Both reviews were performed by assistants, not humans.

The PR's existing lint failure is an em dash in unchanged `tests/unit/core/chaos/test_scenarios.py`; its dependency audit uses the unchanged `pyproject.toml`/`uv.lock` and reports existing advisories. Unit/type checks passed. No dependency upgrade or adjacent cleanup is included.

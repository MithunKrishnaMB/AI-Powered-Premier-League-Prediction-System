# Candidate comparison and review report

Step 9.6 compares one verified baseline classifier and one in-memory
`candidate_unassessed` classifier on exactly the same later operational
holdout. It produces a deterministic report and recommendation. It does not
promote either model, write an artifact or mutate the registry.

## Evidence boundary

Every holdout row must pair one immutable pre-match feature with one official
completed result for the same canonical fixture, competition, season, teams
and kickoff. The feature cutoff and result retrieval must both follow the
candidate's maximum training-knowledge cutoff. Candidate-training fixture IDs
cannot reappear in the holdout.

The workflow validates all identities and rejects the sealed 2025–26 season
before reading an outcome. Baseline, candidate and feature predictor schemas
must match exactly. Both classifiers are evaluated on one complete population
with the existing log-loss, multiclass-Brier and normalized-ranked-probability
score definitions.

## Deterministic review gate

The report requires at least 30 completed holdout fixtures and at least one
home win, draw and away win before it can make a comparative recommendation.
Below either threshold the decision is `insufficient_evidence`.

With sufficient evidence, `candidate_review_recommended` requires strictly
better mean log loss and non-inferior mean Brier and ranked probability scores.
Otherwise the decision is `retain_baseline`. These are operational comparison
gates, not final-test evidence.

Every report has `registry_disposition: no_change` and
`human_review_required: true`. Even a review recommendation cannot create an
artifact, registry event or active model. The actual repository registry
remains `development_accepted` with zero active models.

## Canonical output

The content-derived report binds:

- the baseline model, artifact and manifest identities and exact manifest
  checksum;
- the candidate identity, exact candidate-manifest checksum and training
  knowledge cutoff;
- every holdout feature, fixture, result, observation and cache identity;
- holdout seasons, retrieval cutoff, population and outcome coverage;
- both exact metric summaries, signed improvements and each gate result; and
- the non-mutating decision and mandatory human-review flag.

No model binary, scoreline distribution, prediction corpus, final-test target,
registry transition or production-provider claim is included.

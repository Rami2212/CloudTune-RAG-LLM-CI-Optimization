# Archived npm-only candidate policy

This records the candidate restriction removed in protocol v9. It is kept for
reference if a future study needs the narrower treatment again. It is not the
policy used by current evaluations.

## Previous rule

The shared B/C validator approved only one workflow optimization: add
`with.cache: npm` to an existing supported `actions/setup-node` step. It also
required:

- Checkout before the setup-node step.
- A frozen root `package-lock.json` or `npm-shrinkwrap.json` in the pinned
  repository snapshot.
- A later root `npm ci` or `npm install` command.
- All other workflow fields and original steps to remain unchanged.
- A passing actionlint result and no existing unsafe-workflow finding.

Other cache types, added cache actions, concurrency edits, changed commands,
and other optimization patterns were sent to review or rejected by the shared
gate. CI-Cost and RAG+LLM used the same gate.

## Previous Arm C prompt restriction

The prompt allowed only adding `cache: npm` to a compatible setup-node step,
required the checkout, frozen lockfile, and npm-install prerequisites, and
asked the model to return `NO_CHANGE` when any prerequisite was uncertain.
It prohibited other workflow edits, including concurrency, commands, action
versions, and new steps.

## Restore checklist

To use this policy again, restore the validator's setup-node compatibility and
frozen-lockfile evidence checks, restore the restricted Arm C prompt, and
update the related tests and evaluation guides. Use new prompt, candidate
policy, and protocol revision identifiers, and start with a fresh evaluation
ID. Do not rewrite archived validation decisions or active trial checkpoints.

The policy identifiers used before removal were:

- Candidate policy: `cloudtune-frozen-cache-v8-npm-only-no-concurrency`
- Arm C prompt: `cloudtune-eval-rag-v5-npm-cache-only`
- Evaluation protocol: `cloudtune-local-fork-abc-v8-baseline-reuse-for-ci-cost-no-change`

The Arm B `NO_CHANGE` behavior is separate from this restriction: it skips B's
CI runs and reuses Arm A's measurements in the report.

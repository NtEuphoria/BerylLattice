# Residual correspondence optimization review

Reviewed revision: `5c23c7f`, from the immutable scoped review package and committed source. Reviewed the brief, implementer report, ownership implementation, shared expansion/comparison, both emitter call sites, and focused regression tests. Other agents' working-tree changes were not reviewed or modified.

## Verdict

**Spec compliance: PASS. Code quality: PASS.** No important correctness, ownership, quota, or compatibility finding was identified. The change removes redundant finite-plan work only from the private owned path. It does not establish a measured latency improvement or scalable proof eligibility.

## Review basis

- `_validate_owned_loop_correspondence` calls `_require_owned` before hint decoding (`bounded_loop_correspondence.py:202-204`). The existing owner checks require the exact private record type, a live exact context, and identity membership in that context's issued artifacts (`compilation.py:153-160`). Issuance follows structural validation, retained canonical encoding, and an eligible check registered against the same candidate (`compilation.py:96-150`). The private helper therefore has the existing ownership basis for reusing `owned.checked.plan_digest` and the exact immutable `owned.plan` without rescanning or reencoding them.
- Extraction into `_expand_operations` preserves lexical record validation, raw source/semantic/shape specialization, saturating work and operation prechecks, per-step charging including empty traversal, checked ordered index intermediates, specialized arena bounds, and fresh dense SSA. No traversal algorithm or quota changed (`bounded_loop_correspondence.py:90-150`).
- Shared `_match_operations` checks the actual finite semantic binding, exact scratch reservation, equal complete operation count, and every executable field in order (`bounded_loop_correspondence.py:179-189`). No partial, dead-operation, or suffix match can return successfully. Skipping artificial expanded-Plan validation on the owned path is justified by this complete equality to the already validated actual Plan; hint metadata remains independently bounded by the unchanged hint validator.
- Public `expand_loop_program` still builds and validates its expanded Plan. Public `validate_loop_correspondence` still validates the supplied finite Plan, validates the expanded Plan, and computes canonical identity through `encode_plan` (`bounded_loop_correspondence.py:153-176`). Its output retains an expanded Plan. The private result's `expanded_plan=None` is explicitly documented and neither emitter relies on that field.
- Both emitters retain their ownership check and perform a fresh private correspondence call per emission. Their interfaces still accept owned checks and exact hint bytes, not caller-created correspondence records. Their emission logic and identity fields are otherwise unchanged. Trace counts continue to report correspondence work without inventing candidate validation or encoding events.
- Focused tests assert actual validator/encoder callback absence on the owned path and both emitters, fresh decoding, retained object/digest/source/hint identities, unchanged public validation, forged/closed/cross-context rejection before decoding, metadata independence, exact work cutpoints, hostile empty traversal, and complete-stream mismatch rejection. They include a successfully checked finite plan with an extra dead operation, which must still fail correspondence.

## Validation and limits

Relied on the recorded combined 48-test run, the separately recorded backend callback test, and the explicit LLVM rerun of all nine C tests after the initial missing-Clang skip. The combined run includes the frozen 955-shape × three-schedule corpus and real V8 observations; the LLVM rerun supplies real C execution evidence. No corpus, full production suite, or performance sweep was repeated during review.

The existing ownership protocol is not a sandbox against arbitrary Python code modifying private process state; this optimization does not expand that threat model. Expansion still allocates a bounded transient operation tuple. Performance qualification remains the coordinator's separate gate. No code/test edits were made; only this review report was written.

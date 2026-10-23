# Engineering charter

Process for every substantial change:
1. Inspect the deployed revision and relevant code.
2. Define acceptance criteria before editing.
3. Implement the smallest coherent vertical slice.
4. Test in the deployed browser, not only with curl.
5. Update IMPLEMENTATION_STATUS.md with evidence.

Completion requires:
- The acceptance criteria pass.
- Persistence survives restart or container recreation when relevant.
- Cross-user isolation is proven for private data.
- No fabricated data or signals.

Do not declare a feature complete because an endpoint exists or a deploy command exited successfully.

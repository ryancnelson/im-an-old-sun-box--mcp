# Joining and Contributing

Welcome. This project is intentionally hospitable to curiosity and hostile to
untraceable chaos. You do not need to be a Solaris wizard. You do need to leave
the lab easier to understand than you found it.

## The four sources of truth

1. `SPEC.md` defines required behavior and safety contracts.
2. `TODO.md` is the one canonical backlog and records what is happening next.
3. `docs/plans/` contains implementation plans for work too large to explain in
   a TODO entry.
4. Tests describe behavior the repository can actually prove today.

README prose explains the project; it does not silently override any of these.
If they disagree, stop and reconcile them in the same change.

## Picking up existing work

1. Read `README.md`, the relevant SPEC section, and `TODO.md`.
2. Choose a `ready` item whose dependencies are done. Do not casually take an
   `active` item; talk to its owner or inspect its branch first.
3. Verify that its acceptance criteria are observable. Tighten the TODO before
   coding if “done” would otherwise be subjective.
4. Change its status to `active`, add your name, and name exactly one branch.
5. Create that branch from current `main`:

   ```bash
   git switch main
   git pull --ff-only
   git switch -c codex/sun-002-live-gdb-profile
   ```

6. Add or update a plan in `docs/plans/` when the work crosses components, has
   meaningful risk, or will take more than one focused session.
7. Write the smallest test that fails for the intended reason. Implement until
   it passes, then run the relevant surrounding suite.
8. Record discoveries immediately. Facts belong in evidence or durable docs;
   new work belongs in `TODO.md`; changed requirements belong in `SPEC.md`.

## Proposing “we should add this feature”

Do not begin with a mystery branch and hope the project figures it out later.

1. Search `TODO.md`, open branches, and GitHub issues for duplicates.
2. Add an `idea` entry to `TODO.md` with the next unused `SUN-NNN` ID.
3. State the problem, not merely the mechanism. Include the relevant layer,
   why it matters, its likely mutation class, and the question that must be
   answered before work begins.
4. Add a promotion gate: the minimum design, safety, or evidence needed to make
   the item `ready`.
5. Discuss it in a GitHub issue if conversation would help. Put the TODO ID in
   the issue title and link the issue from the entry.
6. If the feature changes a public contract, draft the SPEC change before
   implementation. Compare at least two plausible approaches when the design
   is not obvious.
7. Promote it to `ready` only when it has observable acceptance criteria,
   dependencies, and no unresolved design decision that would fork the work.
8. Then mark it `active`, create the `codex/<todo-id>-<slug>` branch, and start
   with a failing test or a deliberately documented research probe.

Ideas are welcome. Invisible ideas scattered across chat logs, personal notes,
and branch names are how projects become haunted.

## Branches, commits, and pull requests

- Use one branch per TODO: `codex/sun-002-live-gdb-profile`.
- Keep unrelated cleanup out of the branch. Give cleanup its own TODO when it
  is more than a tiny prerequisite.
- Prefer commits that each leave tests passing and explain intent, such as
  `feat(debugger): add bounded capture orchestration`.
- Never commit secrets, VM disks, captures containing private data, Unix
  sockets, PID files, host-specific credentials, or generated lab state.
- A PR title starts with its ID: `SUN-002: validate live SPARC GDB capture`.
- The PR body lists the hypothesis or goal, SPEC sections, tests run, live
  validation (if any), mutation/cleanup implications, and remaining TODOs.
- Review the diff for accidental host paths and secret-like strings before
  pushing.

## Definition of done for a contribution

A change is not done merely because the interesting code works. Before merge:

- acceptance criteria are met and tested;
- safety, timeout, exact-target, mutation, and cleanup contracts still hold;
- docs and examples match implemented behavior;
- `SPEC.md` changes accompany intentional contract changes;
- follow-up work has new TODO IDs rather than being buried in PR prose;
- the full test suite passes and leaves no child process, socket, or mutated
  fixture behind; and
- the TODO entry moves to History with status `done`, completion date, PR or
  commit link, and a one-line outcome.

After merge, delete the branch. History stays in Git; stale branches should not
become a second backlog.

## Blocked, paused, and abandoned work

If work stops, make its state legible:

1. Push any useful commits.
2. Set the TODO to `blocked` or `ready`; do not leave it falsely `active`.
3. Record the exact blocker, last verified fact, branch name, and safest next
   action.
4. Note any running process, attached debugger, paused VM, temporary socket, or
   cleanup uncertainty. Resolve it when possible; never imply cleanup was
   proved when it was not.
5. If the idea no longer makes sense, mark it `declined` and preserve the
   reason in History.

## Keeping the project tidy

At the end of every working session, ask:

- Did I learn a fact that exists only in chat or my head?
- Did I create work that lacks a TODO ID?
- Does the active TODO name the real branch and current blocker?
- Did behavior change without tests, SPEC, or operator docs changing with it?
- Did I leave generated artifacts or a live debugging attachment behind?

If any answer is uncomfortable, fix the record before starting the next shiny
thing. Vibe-coding is allowed. Vibe-project-management is not.


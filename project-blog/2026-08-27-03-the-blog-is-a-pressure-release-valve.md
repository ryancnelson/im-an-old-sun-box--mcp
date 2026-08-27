# The project blog keeps the docs usable

*August 27, 2026*

I know one of my project failure modes. The ideas start moving, examples keep
arriving, and the nearest documentation file becomes the place where I record
everything. Soon a setup guide is also a diary, the TODO list contains
speculative essays, and the design contract has a paragraph whose real meaning
is "you had to be there Friday night." Nobody, including future me, can quickly
tell what the software promises or what to do next.

I still want to preserve the voice and history of the work. "How drunk was that
guy Friday night when he posted?" is useful context, even if it would make a
terrible requirement.

Each repository document now has one job:

- `SPEC.md` records required behavior and safety contracts.
- `TODO.md` records work, ownership, blockers, and acceptance criteria.
- Operator docs contain repeatable commands and prerequisites.
- Implementation plans contain sequencing and verification commands.
- `project-blog/` records chronology, motivation, discoveries, and jokes.

When a post discovers a durable requirement, I update the SPEC. When it
discovers work, I add a TODO. The blog can remain provisional without making
the project state ambiguous.

The act of creating the project blog immediately became a project-blog post. I
have chosen my level of recursion and am comfortable with it.

## Claude SDLC

### The Workflow

Starting point : a prompt
Then, agent asks clarifying questions and has access to existing docs and beads tasks until satisfied to produce a design doc
Design doc is split into new tasks and modification of existing docs and tasks as required
Hands over tasks to orchestrator who can prioritize work
The implementer agent can be started in their own worktree using worktrunk, tying a worktree to a beads task and dispatch further specialist subagents as required.
When an agent is finished, its work is tested and reviewed by agents (definition of done, security, guidelines, etc)
Task bead is updated.
worktree is merged and task bead is closed.
scheduler will prefer starting work on sibling tasks rather than tasks in other epics.
beads can be added, removed and modified at any point in time.
agents can stop work and tag beads to notify a human to intervene, for example if a decision has to be made on a failure to merge after agents have tried everything.

If possible, we will want to make use of beads swarms and molecules but not necessarily as this could over complicate things.

### The Beads system

It's the underlying task management system we will use to coordinate work. It is assumed that beads is installed on the host machine.

Here are the built-in beads fields : 
- id
- title
- description
- type (bug, feature, task, epic, chore)
- status (open, in_progress,blocked, deferred, closed)
- priority 0 to 3
- assignee the name of the agent or the human user
- created_at/updated_at/closed_at timestamps
- labels/tags/metadata custom state
- dependencies list of beads ids that this bead depends on : parent, or blocked, etc

#### Custom Statuses
- in_review:active
- qa_testing:wip
- on_hold:frozen
- archived:done

There could be more

#### Custom Types
None for now

#### Custom metadata

- branch : the branch name of the worktree for this bead
- cost: usd cost for the implementation of this bead
- agent: the name of the agent (as defined in the LLM harness markdown) that is working on this bead
- model: the model name used by the agent for this bead
- complexity: small, medium, large, xlarge
- session: the session id of the agent working on this bead
- domain: the domain of the bead, for example "frontend", "backend", "devops", "security", etc
- prompt: the prompt passed to the implementer agent for this bead

#### Beads commands to use 
- bd bootstrap : only once per project
- bd show : show the beads in a project
- bd add : add a bead to the project
- bd update <id> --set-metadata <field>=<value> : update a bead's metadata
- bd assign <id> <agent_name> : assign a bead to an agent
- bd update <id> --claim --set-metadata agent=<value> : claim a bead for an agent
- bd list --parent ${epic_id} to see sibling tasks.
- bd remember "<key>" "<insight>" Record discoveries 
- bd create --type message --thread ${epic_id} \"decision: <summary>\" For design decisions visible to siblings 
- bd ready : list ready beads for an agent to work on
- wt list : list worktrees 
- bd done "$task_id" "merged to $target" : mark a bead as done and merged 
- bd reopen "$task_id reopen a task
- bd audit record : record a bead audit trail for a task
- bd update "$task_id" --set-metadata <field>=<value> : update a bead's metadata
- bd merge-slot create : create a merge slot for a project
- bd merge-slot check : check merge-slot availablility
- bd merge-slot acquire
- bd merge-slot release

### The plugin

Now to the plugin itself

#### Agents
- orchestrator
- reviewer
- worker
- resolver

#### Commands
- sdlc:open : open a new SDLC project

#### Skills
- sdlc:split-plan : take a design spec, split the work in beads
- sdlc:split-task : take an existing bead, split it further
- sdlc:dedup : look for similar beads
- sdlc:orchestrate : prioritize beads, decide to open a new branch or not, and assign to agents
- sdlc:create-merge-queue : create a branch and a merge queue for a bead
- sdlc:dispatch : dispatch a bead to an agent, in a worktree
- sdlc:review : review a bead for quality, security, and definition of done
- sdlc:merge : merge a worktree back into the its parent branch efficiently and close the bead or wait for resolution

#### Inspirational sources

Interesting inspirations : 
https://github.com/dsifry/metaswarm
https://github.com/AvivK5498/The-Claude-Protocol

# Reference Repositories

These repos were analyzed during the design phase. Clone them locally for reference:

```bash
git clone <ClawTeam-repo-url> ClawTeam
git clone <OpenHarness-repo-url> OpenHarness
git clone <ciana-parrot-repo-url> ciana-parrot
git clone <claw-code-repo-url> claw-code
git clone <nanobot-repo-url> nanobot
```

## What each repo contributed

| Repo | Key Patterns Adopted |
|------|---------------------|
| **ciana-parrot** | Fork base. LangGraph/DeepAgents, RoutingChatModel, Telegram, gateway bridge, skills, MCP, scheduling, Docker |
| **ClawTeam** | Swarm coordination patterns: phase gates, mailbox, task board, git worktree, team templates, cost tracking |
| **OpenHarness** | Tool ecosystem, permission system, plugin architecture, hooks, fact extraction, compaction |
| **nanobot** | Dream memory (2-stage), 15+ channels, progressive skill loading, heartbeat, cron service |
| **claw-code** | Worker state machine, bash validation, recovery recipes, stale-branch detection, mock service |

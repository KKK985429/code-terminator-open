# Auto Review / Merge / Reload Server Checklist

Use this checklist before enabling automatic incident repair on a server clone.

## Required Runtime Settings

- Save a GitHub token from the Web UI or `PUT /api/settings/runtime`.
- Enable `auto_review_merge_reload` in the same runtime settings payload.
- Set `CODE_TERMINATOR_AGENT_ENABLE_INGEST=1` so the log listener stays active.
- Set `CODE_TERMINATOR_DEPLOY_BRANCH` to the branch the server should pull after merge.

Example:

```bash
export CODE_TERMINATOR_AGENT_ENABLE_INGEST=1
export CODE_TERMINATOR_DEPLOY_BRANCH=main
```

## GitHub Token Permissions

The token must be able to:

- review pull requests
- merge pull requests
- delete worker branches after merge
- satisfy any branch protection rules configured on the target branch

## Expected Flow

1. The log listener opens or resumes an incident.
2. The worker fixes the issue and returns `workflow_updates.pr_url`.
3. The runtime auto-approves and squash-merges the PR through the GitHub API.
4. The incident is marked `approved`.
5. The deploy watcher pulls `CODE_TERMINATOR_DEPLOY_BRANCH`.
6. The ecommerce reload stack refreshes and health checks the gateway.
7. The incident moves from `deployed` to `resolved` after the verification window.

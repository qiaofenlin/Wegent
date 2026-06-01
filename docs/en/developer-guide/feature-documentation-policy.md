---
sidebar_position: 6
---

# Feature Documentation Policy

This document defines Wegent's rule that every new requirement must have its own dedicated documentation record.

## Scope

The following changes must create a standalone documentation page instead of only adding notes to an overview page:

1. New features or workflows
2. User-visible interaction changes
3. New third-party platforms or integrations
4. New configuration, authentication, or runtime prerequisites
5. New operational or release behaviors
6. Behavior changes that affect troubleshooting paths

## Baseline Requirement

Each new requirement must ship with all of the following:

1. Code implementation
2. Corresponding tests
3. A dedicated documentation page
4. Links from the relevant guide or index pages

Without these four parts, the requirement should not be considered fully delivered.

## Where to Place the Document

Choose the document location based on the content:

- User-facing usage: `docs/en/user-guide/`
- Implementation and engineering constraints: `docs/en/developer-guide/`
- Deployment, runtime, or release behavior: `docs/en/deployment/`
- Troubleshooting: add an entry in `docs/en/troubleshooting.md` and link to the standalone page

If a requirement affects both user usage and engineering constraints, create at least one main document and add links plus a short summary from the other side.

## Minimum Content for a Standalone Page

Each requirement document should include at least:

## Background

Explain what problem this requirement solves and why it exists.

## Behavior Change

Describe the before-and-after behavior clearly so readers do not need to infer it from code.

## Usage or Integration

Provide the smallest useful example, configuration sample, or operating steps.

## Limits and Boundaries

State what is not supported, what dependencies exist, and how failures may appear.

## Related Documents

Link to relevant settings, troubleshooting, architecture, or testing documents.

## Recommended Flow

When delivering a new requirement, follow this order:

1. Implement code and tests
2. Add the Chinese documentation page first
3. Add links from the relevant README, guide, or troubleshooting pages
4. Add the English version last

## Common Mistakes

### Only updating a README without adding a standalone page

This makes future changes harder to discover and does not match the repository policy.

### Writing only implementation details without behavior changes

Readers cannot quickly understand why the change matters or what it actually changes.

### Shipping only one language version

The policy requires Chinese first and then English; the other language version should not remain missing long-term.

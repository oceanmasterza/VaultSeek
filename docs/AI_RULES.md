# AI_RULES.md

# AI Development Rules

This repository is intentionally designed for AI-assisted software development.

These rules exist to maximise code quality, maintainability and consistency.

If these rules conflict with a requested implementation, the AI should explain the conflict before writing code.

---

# Primary Objective

Write code that another AI can immediately understand.

Optimise for readability rather than cleverness.

Humans should find the code obvious.

Future AI sessions should require minimal context.

---

# Before Writing Code

Always:

Understand the existing architecture.

Read PROJECT_PLAN.md.

Read ARCHITECTURE.md.

Reuse existing code before creating new code.

Avoid duplicate functionality.

---

# General Coding Rules

Prefer:

Small classes

Small methods

Clear names

Simple logic

Composition

Interfaces

Dependency Injection

Async code

Avoid:

Large classes

Large methods

Static state

Singletons

Global variables

Nested conditionals

Magic strings

Magic numbers

Duplicate logic

---

# Maximum Sizes

Target maximums:

Method

≈40 lines

Class

≈300 lines

ViewModel

≈300 lines

Service

≈300 lines

If a class exceeds these limits, consider refactoring.

---

# Naming Rules

Names should describe intent.

Good:

AlbumSearchService

ProviderManager

DownloadQueue

VerificationResult

Bad:

Helper

Manager2

Temp

Stuff

DataObject

---

# XML Documentation

Every public class must contain XML documentation.

Every public method must contain XML documentation.

Every public property must contain XML documentation.

Explain WHY, not only WHAT.

---

# Comments

Use comments sparingly.

Good comments explain:

Why something exists.

Why a decision was made.

Why an algorithm works.

Do not comment obvious code.

---

# Interfaces

Always program against interfaces.

Example:

```
ISearchProvider

IDownloadManager

IMetadataService

ILibraryService
```

Avoid depending on concrete implementations.

---

# Dependency Injection

All services should be registered through Dependency Injection.

Avoid:

new Service()

inside application logic.

---

# Async Rules

Use async everywhere practical.

Never block async code.

Always support CancellationToken.

Long operations should report progress.

---

# Error Handling

Never silently swallow exceptions.

Always:

Log

Recover

Notify

Continue when safe

Avoid empty catch blocks.

---

# Logging

Use structured logging.

Bad:

```
Error downloading file
```

Good:

```
Download failed for Album '{Album}' from Provider '{Provider}'
```

---

# Unit Tests

Every service should have unit tests.

Business logic should never depend on UI.

Mock providers.

Mock external systems.

---

# Provider Rules

Providers should only communicate with external systems.

Providers should never:

Modify libraries.

Import files.

Touch UI.

Trigger media server refreshes.

Those responsibilities belong elsewhere.

---

# Search Rules

Searches must be provider-independent.

The Search Engine produces SearchRequest objects.

Providers translate SearchRequest into provider-specific requests.

---

# Scoring Rules

Scoring must be deterministic.

Same inputs should always produce the same score.

Weights should be configurable.

No provider-specific scoring.

---

# Import Rules

Downloaded files are never trusted automatically.

Always:

Read metadata.

Fingerprint.

Validate.

Detect duplicates.

Then import.

---

# Refactoring Rules

When modifying existing code:

Improve readability.

Reduce duplication.

Keep behaviour unchanged.

Prefer incremental improvements.

Avoid unnecessary rewrites.

---

# Pull Request Philosophy

Every change should have one purpose.

Avoid "while I'm here" modifications.

Small focused commits.

Small focused pull requests.

---

# AI Behaviour

If uncertain:

Ask.

Do not invent APIs.

Do not invent provider behaviour.

Do not create placeholder implementations without clearly marking them.

Prefer incremental implementation.

---

# Architecture Protection

Do not bypass abstraction layers.

Do not call providers directly from the UI.

Do not place business logic inside ViewModels.

Do not duplicate MusicVault functionality.

Always extend architecture rather than bypass it.

---

# Code Review Checklist

Before considering a task complete, verify:

✓ Builds successfully

✓ No warnings introduced

✓ XML documentation added

✓ Logging added

✓ Async used appropriately

✓ Cancellation supported

✓ Dependency Injection used

✓ Unit tests included

✓ Naming is descriptive

✓ No duplicate code

✓ Architecture respected

✓ Public APIs documented

✓ Configuration strongly typed

✓ Exceptions handled

✓ Code readable

---

# Guiding Principle

The best code is code that another developer—or another AI—can understand in five minutes.

Prefer simplicity.

Prefer clarity.

Prefer maintainability.

Long-term maintainability is more important than short-term speed.
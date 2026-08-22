"use strict";

const assert = require("node:assert/strict");
const test = require("node:test");

const {
  branchIsReserved,
  classifyBranch,
  deleteMergedPullRequestBranch,
} = require("./branch-cleanup.cjs");

const now = new Date("2026-08-22T00:00:00Z");
const keepBranches = new Set(["dev", "prerelease"]);
const keepPrefixes = ["release/"];

function classify(overrides = {}) {
  return classifyBranch({
    name: "feat/example",
    defaultBranch: "main",
    protected: false,
    hasOpenPullRequest: false,
    tipDate: new Date("2025-08-22T00:00:00Z"),
    aheadBy: 0,
    now,
    mergedGraceDays: 7,
    staleDays: 180,
    keepBranches,
    keepPrefixes,
    ...overrides,
  });
}

test("recognizes exact and prefix-based reserved branches", () => {
  assert.equal(
    branchIsReserved("main", "main", keepBranches, keepPrefixes),
    true,
  );
  assert.equal(
    branchIsReserved("dev", "main", keepBranches, keepPrefixes),
    true,
  );
  assert.equal(
    branchIsReserved("release/v2", "main", keepBranches, keepPrefixes),
    true,
  );
  assert.equal(
    branchIsReserved(
      "feature/release-notes",
      "main",
      keepBranches,
      keepPrefixes,
    ),
    false,
  );
});

test("deletes only old branches fully contained in the default branch", () => {
  assert.deepEqual(classify(), {
    action: "delete",
    reason: "merged",
    ageDays: 365,
  });
  assert.deepEqual(classify({ aheadBy: 2 }), {
    action: "report",
    reason: "stale and unmerged",
    ageDays: 365,
  });
});

test("keeps protected branches and branches with open pull requests", () => {
  assert.deepEqual(classify({ protected: true }), {
    action: "keep",
    reason: "protected",
  });
  assert.deepEqual(classify({ hasOpenPullRequest: true }), {
    action: "keep",
    reason: "open pull request",
  });
});

test("honors the merged-branch grace period", () => {
  assert.deepEqual(classify({ tipDate: new Date("2026-08-20T00:00:00Z") }), {
    action: "keep",
    reason: "recently merged",
    ageDays: 2,
  });
});

test("merged pull request cleanup preserves protected branches", async () => {
  let deleted = false;
  const github = {
    paginate: async () => [],
    rest: {
      repos: {
        get: async () => ({ data: { default_branch: "main" } }),
        getBranch: async () => ({
          data: { protected: true, commit: { sha: "abc123" } },
        }),
      },
      pulls: { list() {} },
      git: {
        deleteRef: async () => {
          deleted = true;
        },
      },
    },
  };
  const context = {
    repo: { owner: "example", repo: "project" },
    payload: {
      pull_request: {
        merged: true,
        head: {
          ref: "feat/example",
          sha: "abc123",
          repo: { full_name: "example/project" },
        },
      },
    },
  };

  await deleteMergedPullRequestBranch({ github, context, core: { info() {} } });
  assert.equal(deleted, false);
});

test("merged pull request cleanup deletes an ordinary repository branch", async () => {
  let deletedRef;
  const github = {
    paginate: async () => [],
    rest: {
      repos: {
        get: async () => ({ data: { default_branch: "main" } }),
        getBranch: async () => ({
          data: { protected: false, commit: { sha: "abc123" } },
        }),
      },
      pulls: { list() {} },
      git: {
        deleteRef: async ({ ref }) => {
          deletedRef = ref;
        },
      },
    },
  };
  const context = {
    repo: { owner: "example", repo: "project" },
    payload: {
      pull_request: {
        merged: true,
        head: {
          ref: "feat/example",
          sha: "abc123",
          repo: { full_name: "example/project" },
        },
      },
    },
  };

  await deleteMergedPullRequestBranch({
    github,
    context,
    core: { info() {}, notice() {} },
  });
  assert.equal(deletedRef, "heads/feat/example");
});

test("merged pull request cleanup preserves the base of a stacked pull request", async () => {
  let deleted = false;
  const github = {
    paginate: async () => [{ number: 42 }],
    rest: {
      repos: {
        get: async () => ({ data: { default_branch: "main" } }),
        getBranch: async () => ({
          data: { protected: false, commit: { sha: "abc123" } },
        }),
      },
      pulls: { list() {} },
      git: {
        deleteRef: async () => {
          deleted = true;
        },
      },
    },
  };
  const context = {
    repo: { owner: "example", repo: "project" },
    payload: {
      pull_request: {
        merged: true,
        head: {
          ref: "feat/example",
          sha: "abc123",
          repo: { full_name: "example/project" },
        },
      },
    },
  };
  const messages = [];

  await deleteMergedPullRequestBranch({
    github,
    context,
    core: {
      info(message) {
        messages.push(message);
      },
    },
  });
  assert.equal(deleted, false);
  assert.match(messages.at(-1), /base of 1 open pull request/);
});

test("merged pull request cleanup preserves a branch updated after merge", async () => {
  let deleted = false;
  const github = {
    paginate: async () => [],
    rest: {
      repos: {
        get: async () => ({ data: { default_branch: "main" } }),
        getBranch: async () => ({
          data: { protected: false, commit: { sha: "new-tip" } },
        }),
      },
      pulls: { list() {} },
      git: {
        deleteRef: async () => {
          deleted = true;
        },
      },
    },
  };
  const context = {
    repo: { owner: "example", repo: "project" },
    payload: {
      pull_request: {
        merged: true,
        head: {
          ref: "feat/example",
          sha: "merged-tip",
          repo: { full_name: "example/project" },
        },
      },
    },
  };
  const messages = [];

  await deleteMergedPullRequestBranch({
    github,
    context,
    core: {
      info(message) {
        messages.push(message);
      },
    },
  });
  assert.equal(deleted, false);
  assert.match(messages.at(-1), /changed after the pull request merged/);
});

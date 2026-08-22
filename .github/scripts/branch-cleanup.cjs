"use strict";

const DEFAULT_KEEP_BRANCHES = [
  "dev",
  "prerelease",
  "feat-stageAnalyzer",
  "feat-stageAnalyizer",
];
const DEFAULT_KEEP_PREFIXES = ["release/"];
const DAY_IN_MS = 24 * 60 * 60 * 1000;

function csv(value) {
  return String(value ?? "")
    .split(",")
    .map((item) => item.trim())
    .filter(Boolean);
}

function integerFromEnv(name, fallback) {
  const value = Number.parseInt(process.env[name] ?? "", 10);
  return Number.isFinite(value) && value >= 0 ? value : fallback;
}

function booleanFromEnv(name, fallback = false) {
  const value = process.env[name];
  if (value === undefined || value === "") return fallback;
  return value.toLowerCase() === "true";
}

function branchIsReserved(name, defaultBranch, keepBranches, keepPrefixes) {
  return (
    name === defaultBranch ||
    keepBranches.has(name) ||
    keepPrefixes.some((prefix) => name.startsWith(prefix))
  );
}

function classifyBranch({
  name,
  defaultBranch,
  protected: isProtected,
  hasOpenPullRequest,
  tipDate,
  aheadBy,
  now,
  mergedGraceDays,
  staleDays,
  keepBranches,
  keepPrefixes,
}) {
  if (branchIsReserved(name, defaultBranch, keepBranches, keepPrefixes)) {
    return { action: "keep", reason: "reserved" };
  }
  if (isProtected) return { action: "keep", reason: "protected" };
  if (hasOpenPullRequest)
    return { action: "keep", reason: "open pull request" };

  const ageDays = Math.max(
    0,
    Math.floor((now.getTime() - tipDate.getTime()) / DAY_IN_MS),
  );
  if (aheadBy === 0 && ageDays >= mergedGraceDays) {
    return { action: "delete", reason: "merged", ageDays };
  }
  if (aheadBy === 0) {
    return { action: "keep", reason: "recently merged", ageDays };
  }
  if (ageDays >= staleDays) {
    return { action: "report", reason: "stale and unmerged", ageDays };
  }
  return { action: "keep", reason: "active and unmerged", ageDays };
}

function markdown(value) {
  return String(value).replaceAll("|", "\\|").replaceAll("\n", " ");
}

async function mapLimit(items, limit, callback) {
  const results = new Array(items.length);
  let cursor = 0;

  async function worker() {
    while (cursor < items.length) {
      const index = cursor;
      cursor += 1;
      results[index] = await callback(items[index], index);
    }
  }

  await Promise.all(
    Array.from({ length: Math.min(limit, items.length) }, worker),
  );
  return results;
}

function configuration(defaultBranch) {
  return {
    defaultBranch,
    dryRun: booleanFromEnv("DRY_RUN"),
    mergedGraceDays: integerFromEnv("MERGED_GRACE_DAYS", 7),
    staleDays: integerFromEnv("STALE_DAYS", 180),
    keepBranches: new Set([
      ...DEFAULT_KEEP_BRANCHES,
      ...csv(process.env.KEEP_BRANCHES),
    ]),
    keepPrefixes: [...DEFAULT_KEEP_PREFIXES, ...csv(process.env.KEEP_PREFIXES)],
  };
}

async function inspectBranch({
  github,
  owner,
  repo,
  branch,
  openPullRequestBranches,
  config,
}) {
  const commit = await github.rest.repos.getCommit({
    owner,
    repo,
    ref: branch.name,
  });
  const tipDateValue =
    commit.data.commit.committer?.date ?? commit.data.commit.author?.date;
  if (!tipDateValue)
    throw new Error("tip commit has no author or committer date");

  const comparison = await github.rest.repos.compareCommitsWithBasehead({
    owner,
    repo,
    basehead: `${config.defaultBranch}...${branch.name}`,
  });
  const result = classifyBranch({
    name: branch.name,
    defaultBranch: config.defaultBranch,
    protected: branch.protected,
    hasOpenPullRequest: openPullRequestBranches.has(branch.name),
    tipDate: new Date(tipDateValue),
    aheadBy: comparison.data.ahead_by,
    now: new Date(),
    mergedGraceDays: config.mergedGraceDays,
    staleDays: config.staleDays,
    keepBranches: config.keepBranches,
    keepPrefixes: config.keepPrefixes,
  });

  return {
    branch: branch.name,
    tipSha: branch.commit.sha,
    tipDate: tipDateValue,
    aheadBy: comparison.data.ahead_by,
    ...result,
  };
}

async function sweepBranches({ github, context, core }) {
  const { owner, repo } = context.repo;
  const repository = await github.rest.repos.get({ owner, repo });
  const config = configuration(repository.data.default_branch);
  const [branches, openPullRequests] = await Promise.all([
    github.paginate(github.rest.repos.listBranches, {
      owner,
      repo,
      per_page: 100,
    }),
    github.paginate(github.rest.pulls.list, {
      owner,
      repo,
      state: "open",
      per_page: 100,
    }),
  ]);
  const openPullRequestBranches = new Set();
  for (const pullRequest of openPullRequests) {
    if (pullRequest.head.repo?.full_name === `${owner}/${repo}`) {
      openPullRequestBranches.add(pullRequest.head.ref);
    }
    // A merged branch can still be the base of a stacked pull request.
    // Keep that base until the dependent pull request is closed or retargeted.
    if (pullRequest.base.repo?.full_name === `${owner}/${repo}`) {
      openPullRequestBranches.add(pullRequest.base.ref);
    }
  }
  const candidates = branches.filter(
    (branch) =>
      !branchIsReserved(
        branch.name,
        config.defaultBranch,
        config.keepBranches,
        config.keepPrefixes,
      ),
  );

  const inspections = await mapLimit(candidates, 8, async (branch) => {
    try {
      return await inspectBranch({
        github,
        owner,
        repo,
        branch,
        openPullRequestBranches,
        config,
      });
    } catch (error) {
      return { branch: branch.name, action: "error", reason: error.message };
    }
  });

  const deleted = [];
  const changed = [];
  const stale = [];
  const errors = inspections.filter((result) => result.action === "error");
  for (const result of inspections) {
    if (result.action === "report") stale.push(result);
    if (result.action !== "delete") continue;

    if (config.dryRun) {
      deleted.push({ ...result, dryRun: true });
      continue;
    }
    try {
      const currentBranch = await github.rest.repos.getBranch({
        owner,
        repo,
        branch: result.branch,
      });
      if (
        currentBranch.data.protected ||
        currentBranch.data.commit.sha !== result.tipSha
      ) {
        changed.push(result);
        continue;
      }
      await github.rest.git.deleteRef({
        owner,
        repo,
        ref: `heads/${result.branch}`,
      });
      deleted.push(result);
    } catch (error) {
      errors.push({
        branch: result.branch,
        action: "error",
        reason: error.message,
      });
    }
  }

  core.summary
    .addHeading("Branch maintenance")
    .addRaw(
      `${config.dryRun ? "Dry run: would delete" : "Deleted"} **${deleted.length}** merged branch(es). ` +
        `Found **${stale.length}** stale unmerged branch(es); those were not deleted.\n\n`,
    );

  if (deleted.length > 0) {
    core.summary.addHeading(
      config.dryRun
        ? "Merged branches eligible for deletion"
        : "Deleted branches",
      2,
    );
    core.summary.addTable([
      [
        { data: "Branch", header: true },
        { data: "Tip age", header: true },
      ],
      ...deleted.map((result) => [
        markdown(result.branch),
        `${result.ageDays} days`,
      ]),
    ]);
  }
  if (stale.length > 0) {
    core.summary.addHeading("Review manually: stale unmerged branches", 2);
    core.summary.addTable([
      [
        { data: "Branch", header: true },
        { data: "Tip age", header: true },
        { data: "Commits ahead", header: true },
      ],
      ...stale.map((result) => [
        markdown(result.branch),
        `${result.ageDays} days`,
        String(result.aheadBy),
      ]),
    ]);
  }
  if (changed.length > 0) {
    core.summary.addHeading(
      "Kept because the branch changed during the sweep",
      2,
    );
    core.summary.addList(changed.map((result) => markdown(result.branch)));
  }
  if (errors.length > 0) {
    core.summary.addHeading("Errors", 2).addTable([
      [
        { data: "Branch", header: true },
        { data: "Error", header: true },
      ],
      ...errors.map((result) => [
        markdown(result.branch),
        markdown(result.reason),
      ]),
    ]);
  }
  await core.summary.write();

  if (errors.length > 0) {
    core.setFailed(
      `Branch maintenance failed for ${errors.length} branch(es).`,
    );
  }
}

async function deleteMergedPullRequestBranch({ github, context, core }) {
  const pullRequest = context.payload.pull_request;
  if (!pullRequest?.merged) return;

  const { owner, repo } = context.repo;
  if (pullRequest.head.repo?.full_name !== `${owner}/${repo}`) {
    core.info(
      "The merged pull request came from a fork; there is no repository branch to delete.",
    );
    return;
  }

  const repository = await github.rest.repos.get({ owner, repo });
  const config = configuration(repository.data.default_branch);
  const branchName = pullRequest.head.ref;
  if (
    branchIsReserved(
      branchName,
      config.defaultBranch,
      config.keepBranches,
      config.keepPrefixes,
    )
  ) {
    core.info(`Keeping reserved branch ${branchName}.`);
    return;
  }

  try {
    const branch = await github.rest.repos.getBranch({
      owner,
      repo,
      branch: branchName,
    });
    if (branch.data.protected) {
      core.info(`Keeping protected branch ${branchName}.`);
      return;
    }
    if (branch.data.commit.sha !== pullRequest.head.sha) {
      core.info(
        `Keeping ${branchName}; it changed after the pull request merged.`,
      );
      return;
    }
    const dependentPullRequests = await github.paginate(
      github.rest.pulls.list,
      {
        owner,
        repo,
        state: "open",
        base: branchName,
        per_page: 100,
      },
    );
    if (dependentPullRequests.length > 0) {
      core.info(
        `Keeping ${branchName}; it is the base of ${dependentPullRequests.length} open pull request(s).`,
      );
      return;
    }
    await github.rest.git.deleteRef({
      owner,
      repo,
      ref: `heads/${branchName}`,
    });
    core.notice(`Deleted merged pull request branch ${branchName}.`);
  } catch (error) {
    if (error.status === 404 || error.status === 422) {
      core.info(`Branch ${branchName} is already absent or cannot be deleted.`);
      return;
    }
    throw error;
  }
}

module.exports = {
  branchIsReserved,
  classifyBranch,
  deleteMergedPullRequestBranch,
  sweepBranches,
};

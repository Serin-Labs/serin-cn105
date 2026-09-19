// Test the release workflow with GitHub's expression evaluator and real shell
// gates. Test dependencies live outside the repo; see docs/release-validation.md.
import assert from 'node:assert/strict';
import fs from 'node:fs';
import path from 'node:path';
import { spawnSync } from 'node:child_process';
import { pathToFileURL } from 'node:url';

const modules = process.env.WORKFLOW_TEST_MODULES;
assert.ok(modules, 'Set WORKFLOW_TEST_MODULES to the test dependencies directory');
const { Lexer, Parser, Evaluator, data } = await import(pathToFileURL(
  path.join(modules, '@actions/expressions/dist/index.js')));
const { parse } = await import(pathToFileURL(path.join(modules, 'yaml/dist/index.js')));
const workflow = parse(fs.readFileSync(process.argv[2] || '.github/workflows/esphome-firmware.yml', 'utf8'));

function evaluate(expression, context) {
  const source = String(expression ?? 'true').replace(/^\s*\$\{\{\s*|\s*\}\}\s*$/g, '');
  const functions = new Map([['always', {
    name: 'always', minArgs: 0, maxArgs: 0, call: () => new data.BooleanData(true)
  }]]);
  const ast = new Parser(new Lexer(source).lex().tokens, ['github', 'needs'], [...functions.values()]).parse();
  return new Evaluator(ast, JSON.parse(JSON.stringify(context), data.reviver), functions).evaluate();
}

function render(template, context) {
  return template.replace(/\$\{\{([\s\S]*?)\}\}/g, (_, expression) =>
    evaluate(expression, context).coerceString());
}

function context(event, ref, number, result = 'success') {
  return {
    github: { event_name: event, ref, event: { pull_request: number ? { number } : null } },
    needs: { build: { result }, validate: { result } }
  };
}

const tests = [
  ['every main PR gets both board builds and a read-only validation job', () => {
    assert.ok(workflow.on.pull_request, 'PR builds are missing');
    assert.ok(workflow.on.pull_request.branches.includes('main'));
    assert.equal(workflow.on.pull_request.paths, undefined, 'required checks must not disappear on unrelated changes');
    assert.equal(workflow.on.pull_request['paths-ignore'], undefined);
    assert.equal(workflow.on.pull_request_target, undefined, 'PR code must not run as a privileged base-branch workflow');
    const configs = workflow.jobs.build.strategy.matrix.include.map(row => row.config);
    assert.ok(configs.includes('esphome/serin_esp32c6.yaml'));
    assert.ok(configs.includes('esphome/serin_esp32s3.yaml'));
    for (const id of ['build', 'validate']) {
      assert.ok(workflow.jobs[id], `${id} job is missing`);
      const permissions = workflow.jobs[id].permissions || workflow.permissions;
      assert.equal(permissions.contents, 'read', `${id} must not receive repository write access`);
    }
  }],
  ['only successful main push/manual runs may publish', () => {
    assert.ok([workflow.jobs.deploy.needs].flat().includes('validate'), 'publication must depend on validation');
    const cases = [
      ['push', 'refs/heads/main', true],
      ['workflow_dispatch', 'refs/heads/main', true],
      ['pull_request', 'refs/pull/17/merge', false],
      ['pull_request', 'refs/heads/main', false],
      ['push', 'refs/heads/feature', false],
      ['workflow_dispatch', 'refs/heads/feature', false],
      ['workflow_dispatch', 'refs/tags/v1.0.0', false],
      ['workflow_run', 'refs/heads/main', false],
      ['merge_group', 'refs/heads/main', false]
    ];
    for (const [event, ref, allowed] of cases) {
      for (const result of ['success', 'failure', 'cancelled', 'skipped']) {
        assert.equal(evaluate(workflow.jobs.deploy.if, context(event, ref, 17, result)).value,
          allowed && result === 'success', `${event} ${ref} ${result}`);
      }
    }
  }],
  ['failed, cancelled, or skipped builds produce a failed validation check', () => {
    const validation = workflow.jobs.validate;
    assert.ok(validation, 'required validation job is missing');
    assert.ok([validation.needs].flat().includes('build'));
    assert.ok(validation.if, 'validation must still run after a failed build');
    const gate = validation.steps[0];
    assert.ok(gate.run, 'build result must be checked before preparing artifacts');
    for (const result of ['success', 'failure', 'cancelled', 'skipped']) {
      const ctx = context('pull_request', 'refs/pull/17/merge', 17, result);
      assert.equal(evaluate(validation.if, ctx).value, true, 'the required check must run for ' + result);
      const env = Object.fromEntries(Object.entries(gate.env).map(([key, value]) => [key, render(value, ctx)]));
      const run = spawnSync('bash', ['-e', '-o', 'pipefail', '-c', gate.run], {
        env: { ...process.env, ...env }, encoding: 'utf8'
      });
      assert.equal(run.status === 0, result === 'success', result + ': ' + run.stderr);
    }
  }],
  ['PR cancellation cannot interrupt releases or other PRs', () => {
    const concurrency = workflow.concurrency;
    const pr = context('pull_request', 'refs/pull/17/merge', 17);
    const otherPr = context('pull_request', 'refs/pull/18/merge', 18);
    const push = context('push', 'refs/heads/main');
    const manual = context('workflow_dispatch', 'refs/heads/main');
    assert.notEqual(render(concurrency.group, pr), render(concurrency.group, push));
    assert.notEqual(render(concurrency.group, pr), render(concurrency.group, otherPr));
    assert.equal(render(concurrency.group, push), render(concurrency.group, manual));
    assert.equal(evaluate(concurrency['cancel-in-progress'], pr).value, true);
    assert.equal(evaluate(concurrency['cancel-in-progress'], push).value, false);
    assert.equal(evaluate(concurrency['cancel-in-progress'], manual).value, false);
  }]
];

let failures = 0;
for (const [name, test] of tests) {
  try {
    test();
    console.log('PASS ' + name);
  } catch (error) {
    failures++;
    console.error('FAIL ' + name + ': ' + error.message);
  }
}
process.exitCode = failures ? 1 : 0;

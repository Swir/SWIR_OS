import assert from 'node:assert/strict';
import { AptDependencyResolver, AptDependencyResolverPolicy, parseAptSimulation } from './apt-dependency-resolver.mjs';

const parsed = parseAptSimulation(`Reading package lists...\nInst cowsay (3.03+dfsg2-8 Debian:13.0/stable [all])\nInst libtext-charwidth-perl (0.04-11+b4 Debian:13.0/stable [amd64])\nConf libtext-charwidth-perl (0.04-11+b4 Debian:13.0/stable [amd64])\nConf cowsay (3.03+dfsg2-8 Debian:13.0/stable [all])\n`);
assert.deepEqual(parsed.install, ['cowsay', 'libtext-charwidth-perl']);
assert.deepEqual(parsed.configure, ['libtext-charwidth-perl', 'cowsay']);
assert.deepEqual(parsed.affected, ['cowsay', 'libtext-charwidth-perl']);
assert.equal(AptDependencyResolverPolicy.simulationOnly, true);
assert.equal(AptDependencyResolverPolicy.shell, false);

const calls = [];
const resolver = new AptDependencyResolver({
  statSync: () => ({ isFile: () => true, uid: 0, mode: 0o100755 }),
  runner: async (file, args) => {
    calls.push({ file, args });
    return {
      exitCode: 0,
      signal: null,
      stdout: 'Inst cowsay (1.0 repo [all])\nInst helper-lib (1.0 repo [amd64])\nConf helper-lib (1.0 repo [amd64])\nConf cowsay (1.0 repo [all])\n',
      stderr: ''
    };
  }
});
const plan = await resolver.resolve({ operation: 'install', packageName: 'cowsay' });
assert.equal(plan.schema, 'swir.apt-dependency-plan/0.1');
assert.equal(plan.mutationPerformed, false);
assert.deepEqual(plan.packages.affected, ['cowsay', 'helper-lib']);
assert.deepEqual(calls[0], { file: '/usr/bin/apt-get', args: ['-s', 'install', '--', 'cowsay'] });
await assert.rejects(() => resolver.resolve({ operation: 'install', packageName: 'bad;name' }), /invalid apt package name/);

console.log('SWIR apt dependency resolver self-tests: OK');

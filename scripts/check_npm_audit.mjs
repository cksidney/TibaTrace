#!/usr/bin/env node

/**
 * Enforce high/critical npm-audit findings while narrowly recording two
 * unpatched advisories confined to the POS Android build-tool dependency
 * tree. `braces` has no release newer than vulnerable 3.0.3. `image-size`
 * 2.0.4 is patched, but Metro 0.84.4 requires the incompatible 1.x API; npm's
 * proposed compatible fix downgrades React Native to 0.72.17. These parsers
 * are used by the build toolchain, not the shipped HQ/backend applications.
 *
 * This is deliberately narrow: any additional high/critical package, a new
 * advisory, or a changed React Native dependency path fails CI. An incomplete
 * audit response (for example, an unreachable advisory service) also fails.
 */

import { spawnSync } from 'node:child_process';

const result = spawnSync('npm', ['audit', '--json'], {
  encoding: 'utf8',
  stdio: ['ignore', 'pipe', 'pipe'],
});

if (!result.stdout) {
  console.error(result.stderr || 'npm audit returned no JSON output.');
  process.exit(1);
}

let report;
try {
  report = JSON.parse(result.stdout);
} catch (error) {
  console.error(`Unable to parse npm audit output: ${error.message}`);
  process.exit(1);
}

const vulnerabilities = report.vulnerabilities || {};
if (
  report.error ||
  !report.metadata?.vulnerabilities ||
  !Number.isInteger(report.metadata.vulnerabilities.total)
) {
  console.error('npm audit did not return a complete advisory report.');
  process.exit(1);
}

const severe = Object.entries(vulnerabilities).filter(([, finding]) =>
  ['high', 'critical'].includes(finding.severity),
);

const knownPosAndroidBuildToolPackages = new Set([
  '@react-native-community/cli',
  '@react-native-community/cli-clean',
  '@react-native-community/cli-config',
  '@react-native-community/cli-config-android',
  '@react-native-community/cli-config-apple',
  '@react-native-community/cli-doctor',
  '@react-native-community/cli-platform-android',
  '@react-native-community/cli-platform-apple',
  '@react-native-community/cli-platform-ios',
  '@react-native/community-cli-plugin',
  '@react-native/metro-config',
  '@react-native/virtualized-lists',
  'braces',
  'fast-glob',
  'image-size',
  'micromatch',
  'metro',
  'metro-config',
  'metro-file-map',
  'metro-transform-worker',
  'react-native',
]);
const expectedAdvisories = new Set([
  'https://github.com/advisories/GHSA-vfj7-8cjw-p6xm',
  'https://github.com/advisories/GHSA-w3rx-r6r6-pgpr',
  'https://github.com/advisories/GHSA-5p2g-fcmc-qvqq',
]);

const observedAdvisories = new Set(
  severe.flatMap(([, finding]) =>
    (finding.via || [])
    .filter((item) => typeof item === 'object' && item !== null)
      .map((item) => item.url),
  ),
);
const isKnownUnpatchedBuildToolIssue =
  severe.length > 0 &&
  severe.every(([name]) => knownPosAndroidBuildToolPackages.has(name)) &&
  observedAdvisories.size === expectedAdvisories.size &&
  [...observedAdvisories].every((url) => expectedAdvisories.has(url));

if (severe.length === 0) {
  console.log('npm audit: no high or critical findings.');
  process.exit(0);
}

if (isKnownUnpatchedBuildToolIssue) {
  console.warn(
    'npm audit: accepted only the exact known unpatched POS Android build-tool advisories; no additional high/critical findings detected.',
  );
  process.exit(0);
}

console.error(
  `npm audit: unexpected high/critical findings:\n${JSON.stringify(Object.fromEntries(severe), null, 2)}`,
);
process.exit(result.status || 1);

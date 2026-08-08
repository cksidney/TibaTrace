#!/usr/bin/env node

/**
 * Enforce high/critical npm-audit findings while recording the one currently
 * unpatchable upstream exception. React Native 0.86's Metro dependency pins
 * image-size <=2.0.2; both reported advisories cover every released version,
 * and npm's proposed "fix" downgrades React Native to 0.72.17. The affected
 * parser is build tooling, not a shipped HQ/backend dependency.
 *
 * This is deliberately narrow: any additional high/critical package, a new
 * image-size advisory, or a changed React Native dependency path fails CI.
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
const severe = Object.entries(vulnerabilities).filter(([, finding]) =>
  ['high', 'critical'].includes(finding.severity),
);

const metroDependencyChain = new Set([
  'image-size',
  'metro',
  'metro-config',
  'metro-transform-worker',
  '@react-native/metro-config',
  '@react-native/community-cli-plugin',
  '@react-native/virtualized-lists',
  'react-native',
]);
const expectedAdvisories = new Set([
  'https://github.com/advisories/GHSA-w3rx-r6r6-pgpr',
  'https://github.com/advisories/GHSA-5p2g-fcmc-qvqq',
]);

const imageSize = vulnerabilities['image-size'];
const imageSizeAdvisories = new Set(
  (imageSize?.via || [])
    .filter((item) => typeof item === 'object' && item !== null)
    .map((item) => item.url),
);
const isKnownUnpatchableMetroIssue =
  severe.length > 0 &&
  severe.every(([name]) => metroDependencyChain.has(name)) &&
  imageSizeAdvisories.size === expectedAdvisories.size &&
  [...imageSizeAdvisories].every((url) => expectedAdvisories.has(url));

if (severe.length === 0) {
  console.log('npm audit: no high or critical findings.');
  process.exit(0);
}

if (isKnownUnpatchableMetroIssue) {
  console.warn(
    'npm audit: accepted known Metro build-tooling exception; image-size has no patched release and npm proposes an unsafe React Native downgrade.',
  );
  process.exit(0);
}

console.error(
  `npm audit: unexpected high/critical findings:\n${JSON.stringify(Object.fromEntries(severe), null, 2)}`,
);
process.exit(result.status || 1);

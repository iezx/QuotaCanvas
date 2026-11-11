// Optional developer build. Python deployments use the checked-in output.
const fs = require('node:fs');
const path = require('node:path');
const {createHash} = require('node:crypto');
const {execFileSync} = require('node:child_process');
const esbuild = require('esbuild');
const root = path.resolve(__dirname, '..');
process.chdir(root);

const hash = file => createHash('sha256').update(fs.readFileSync(file)).digest('hex');
const inputs = ['package.json', 'package-lock.json', 'web/build.cjs', 'web/src/overview.js', 'web/src/overview.css', 'web/src/index.html'];
const outputs = ['web/assets/index.js', 'web/assets/index.css', 'THIRD_PARTY_NOTICES'];
fs.mkdirSync('web/assets', {recursive: true});

esbuild.buildSync({
  entryPoints: ['web/src/overview.js'],
  outfile: 'web/assets/index.js',
  bundle: true,
  minify: true,
  format: 'esm',
  platform: 'browser',
  target: ['es2020'],
  charset: 'utf8',
  legalComments: 'inline',
  define: {'process.env.NODE_ENV': '"production"'}
});
const cli = path.join(path.dirname(require.resolve('@tailwindcss/cli/package.json')), 'dist/index.mjs');
execFileSync(process.execPath, [cli, '-i', 'web/src/overview.css', '-o', 'web/assets/index.css', '--minify'], {stdio: 'inherit'});

const packages = ['react', 'react-dom', 'scheduler', 'tailwindcss'];
const notices = ['QuotaCanvas web dependency notices', '', 'The shipped overview JavaScript includes React, React DOM, and Scheduler.', 'The stylesheet is generated with Tailwind CSS. Build tools are not loaded by the browser.', ''];
for (const name of packages) {
  const directory = path.dirname(require.resolve(name + '/package.json'));
  const pkg = JSON.parse(fs.readFileSync(path.join(directory, 'package.json'), 'utf8'));
  const license = ['LICENSE', 'LICENSE.md'].find(file => fs.existsSync(path.join(directory, file)));
  if (!license) throw new Error('Missing license for ' + name);
  notices.push(name + ' ' + pkg.version, pkg.repository?.url || pkg.homepage || '', '', fs.readFileSync(path.join(directory, license), 'utf8').trim(), '');
}
fs.writeFileSync('THIRD_PARTY_NOTICES', notices.join('\n') + '\n');

const template = fs.readFileSync('web/src/index.html', 'utf8');
const html = template.replace(/((?:src|href)=")(\/assets\/[^"?]+\.(?:js|css))(")/g, (_, before, url, after) => before + url + '?v=' + hash('web' + url).slice(0, 12) + after);
fs.writeFileSync('web/index.html', html);
fs.writeFileSync('web/build-manifest.json', JSON.stringify({
  inputs: Object.fromEntries(inputs.map(file => [file, hash(file)])),
  outputs: Object.fromEntries(outputs.map(file => [file, hash(file)]))
}, null, 2) + '\n');
console.log('Built QuotaCanvas overview from first-party source');

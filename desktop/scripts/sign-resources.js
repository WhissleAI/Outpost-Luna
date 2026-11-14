// electron-builder afterPack hook (macOS): sign the native code that lives under Contents/Resources.
//
// The embedded Python, torch, onnxruntime and libarctag put ~210 Mach-O files under Resources/ (python, site,
// native). @electron/osx-sign would "sign" every non-text file it finds there (models, media, .pyc) by writing
// signatures into xattrs, so electron-builder.yml `signIgnore`s those trees and this hook signs exactly the
// Mach-O files instead, before osx-sign seals the app around them.
//
//   MAC_SIGN_IDENTITY unset -> ad-hoc ("-"), as before (arm64 needs every Mach-O at least ad-hoc signed)
//   MAC_SIGN_IDENTITY="Developer ID Application: Whissle LLC (XXK95K57U5)" -> hardened runtime + secure timestamp,
//                       which notarization requires on every binary
const fs = require('fs');
const path = require('path');
const { execFileSync } = require('child_process');

const MACHO = new Set(['cffaedfe', 'cefaedfe', 'cafebabe', 'feedfacf', 'bebafeca']);
const TREES = ['python', 'site', 'native', 'app', 'models'];

function isMachO(p) {
  const fd = fs.openSync(p, 'r');
  try {
    const b = Buffer.alloc(4);
    return fs.readSync(fd, b, 0, 4, 0) === 4 && MACHO.has(b.toString('hex'));
  } finally {
    fs.closeSync(fd);
  }
}

function* walk(dir) {
  for (const e of fs.readdirSync(dir, { withFileTypes: true })) {
    const p = path.join(dir, e.name);
    if (e.isSymbolicLink()) continue;
    if (e.isDirectory()) yield* walk(p);
    else if (e.isFile()) yield p;
  }
}

function findMachO(resources) {
  const out = [];
  for (const t of TREES) {
    const root = path.join(resources, t);
    if (!fs.existsSync(root)) continue;
    for (const p of walk(root)) if (isMachO(p)) out.push(p);
  }
  // Deepest first, so a library is signed before anything that could seal it.
  return out.sort((a, b) => b.split(path.sep).length - a.split(path.sep).length);
}

exports.default = async function signResources(context) {
  if (context.electronPlatformName !== 'darwin') return;
  const app = path.join(context.appOutDir, `${context.packager.appInfo.productFilename}.app`);
  const resources = path.join(app, 'Contents', 'Resources');
  const identity = process.env.MAC_SIGN_IDENTITY || '-';
  const developerId = identity !== '-';
  const entitlements = path.join(__dirname, '..', 'build-resources', 'entitlements.mac.plist');
  const files = findMachO(resources);
  const t0 = Date.now();
  for (const f of files) {
    const args = ['--force', '--sign', identity];
    if (developerId) {
      args.push('--options', 'runtime', '--timestamp');
      // Executables (not libraries) carry the entitlements: the embedded python3 needs JIT/unsigned memory and
      // disable-library-validation for the torch / onnxruntime wheels.
      if (!/\.(so|dylib)$/.test(f)) args.push('--entitlements', entitlements);
    }
    args.push(f);
    execFileSync('codesign', args, { stdio: ['ignore', 'ignore', 'pipe'] });
  }
  console.log(`  • sign-resources: ${files.length} Mach-O files under Resources signed ` +
    `(${developerId ? 'Developer ID, hardened runtime' : 'ad-hoc'}) in ${((Date.now() - t0) / 1000).toFixed(0)}s`);
};

exports.findMachO = findMachO;

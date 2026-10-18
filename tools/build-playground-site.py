#!/usr/bin/env python3
"""Build a reviewed static beryl demo without exposing the research checkout.

This command only writes a new local output directory. It never publishes it.
Default runtime assets are pinned, hash-checked and vendored for same-origin use.
"""
import argparse
import hashlib
import io
import json
from pathlib import Path
import re
import urllib.request
import zipfile

ROOT = Path(__file__).resolve().parents[1]
VERSION = '0.27.7'
CDN = f'https://cdn.jsdelivr.net/pyodide/v{VERSION}/full/'
MODULES = ('__init__', 'runtime', 'playground_service', 'frontend', 'model',
           'checker', 'codec', 'plan_format', 'planner', 'selection', 'reference',
           'wasm', 'native_codegen')
ASSETS = ('index.html', 'app.js', 'style.css', 'transport.js', 'worker.js',
          'benchmarks.html', 'benchmarks.js', 'benchmark-results.json')
# Export only these reviewed branding changes; private compiler sources stay intact.
# Public version names intentionally give the exported plans distinct identities.
PUBLIC_SOURCE_REPLACEMENTS = {
    '__init__': ((b"Axiom's bounded correctness prototype.",
                  b"beryl's bounded correctness prototype."),),
    'runtime': ((b'Freshly checked execution of finite Axiom plans on owned Python buffers.',
                 b'Freshly checked execution of finite beryl plans on owned Python buffers.'),),
    'playground_service': ((b'Bounded presentation requests over the existing Axiom v1 implementation.',
                            b'Bounded presentation requests for the beryl browser demo.'),),
    'frontend': ((b'Bounded parsing and structural admission of the single Axiom stencil.',
                  b'Bounded parsing and structural admission of the supported beryl stencil.'),),
    'model': ((b"SEMANTICS_VERSION = 'axiom-stencil-i32-v1'",
               b"SEMANTICS_VERSION = 'beryl-stencil-i32-v1'"),),
    'checker': ((b"CHECKER_VERSION = 'axiom-checker-v1'",
                 b"CHECKER_VERSION = 'beryl-checker-v1'"),),
    'native_codegen': (
        (b'Private C11 lowering of freshly checked bounded Axiom physical plans.',
         b'C11 lowering of freshly checked bounded beryl physical plans.'),
        (b'This backend implements the finite Axiom plan directly; it is independent of',
         b'This backend implements the finite beryl plan directly; it is independent of'),
        (b'/* Generated from a freshly checked finite Axiom physical plan. */',
         b'/* Generated from a freshly checked finite beryl physical plan. */'),
    ),
}
# Verified upstream release bytes. No additional Python packages are installed.
RUNTIME = {
    'pyodide.js': ('b4cb23a53aba19c221659b9fb40a2f18281d685691dc06647fb0afd0681baf98', CDN + 'pyodide.js'),
    'pyodide.asm.js': ('6b4c90de5b7172873f04f21884d0e9d2274e305fe32116558fe3e4fbe3618d51', CDN + 'pyodide.asm.js'),
    'pyodide.asm.wasm': ('a50dd1843f805a0b7c45b61037ee0d7b26dfe85efe0e18ef95a34ad24e401f5f', CDN + 'pyodide.asm.wasm'),
    'python_stdlib.zip': ('16611534726e5d8ac2bd8f926410b2dcb8d6f49aa24913463533b457a2115c16', CDN + 'python_stdlib.zip'),
    'pyodide-lock.json': ('9c45b916001a750f4102fc287494f3eab215909c7535c626a20db80fd6333e2c', CDN + 'pyodide-lock.json'),
    'PYODIDE-LICENSE': ('1f256ecad192880510e84ad60474eab7589218784b9a50bc7ceee34c2b91f1d5',
                        'https://raw.githubusercontent.com/pyodide/pyodide/0.27.7/LICENSE'),
    'PYTHON-LICENSE': ('3b2f81fe21d181c499c59a256c8e1968455d6689d269aa85373bfb6af41da3bf',
                       'https://raw.githubusercontent.com/python/cpython/v3.12.7/LICENSE'),
}


def digest(raw):
    return hashlib.sha256(raw).hexdigest()


def runtime_bytes(name, cache):
    expected, url = RUNTIME[name]
    cached = cache / name if cache else None
    if cached and cached.is_file():
        raw = cached.read_bytes()
    else:
        with urllib.request.urlopen(url, timeout=60) as response:
            raw = response.read(20 * 1024 * 1024 + 1)
    if digest(raw) != expected:
        raise ValueError(f'pinned runtime hash mismatch: {name}')
    return raw


def archive_modules():
    archive = io.BytesIO()
    entries = {}
    with zipfile.ZipFile(archive, 'w', compression=zipfile.ZIP_DEFLATED) as output:
        for module in MODULES:
            name = f'beryl/{module}.py'
            path = ROOT / 'axiom' / 'src' / 'axiom' / f'{module}.py'
            raw = path.read_bytes()
            for old, new in PUBLIC_SOURCE_REPLACEMENTS.get(module, ()):
                if raw.count(old) != 1:
                    raise ValueError(f'expected one reviewed public branding marker in {module}.py')
                raw = raw.replace(old, new, 1)
            if re.search(b'axiom', raw, flags=re.IGNORECASE):
                raise ValueError(f'unexpected private codename in public module {module}.py')
            info = zipfile.ZipInfo(name, date_time=(2026, 10, 18, 0, 0, 0))
            info.compress_type = zipfile.ZIP_DEFLATED
            info.external_attr = 0o644 << 16
            output.writestr(info, raw)
            entries[name] = {'bytes': len(raw), 'sha256': digest(raw)}
        # A standalone source download must carry its own license notice.
        license_bytes = (ROOT / 'axiom/playground-LICENSE').read_bytes()
        info = zipfile.ZipInfo('LICENSE', date_time=(2026, 10, 18, 0, 0, 0))
        info.compress_type = zipfile.ZIP_DEFLATED
        info.external_attr = 0o644 << 16
        output.writestr(info, license_bytes)
    members = dict(entries)
    members['LICENSE'] = {'bytes': len(license_bytes), 'sha256': digest(license_bytes)}
    return archive.getvalue(), entries, members


def build(output, runtime, cache):
    if output.exists() and (not output.is_dir() or any(output.iterdir())):
        raise ValueError('output must be a new or empty directory; existing files are never replaced')
    # Gather all inputs before writing output, so a failed download leaves no partial release.
    files = {name: (ROOT / 'axiom/src/axiom/playground_web' / name).read_bytes()
             for name in ASSETS}
    for extension in ('c', 'rs'):
        files[f'benchmark.{extension}'] = (ROOT / 'tools/benchmarks' / f'stencil.{extension}').read_bytes()
    index = files['index.html'].decode('utf-8')
    index, replacements = re.subn(r'<html\b([^>]*)>', r'<html\1 data-runtime="browser">', index, count=1)
    if replacements != 1 or index.count('data-runtime=') != 1:
        raise ValueError('expected one HTML root without an existing runtime declaration')
    # Relative links support both a domain root and GitHub Pages repository paths.
    for asset in ASSETS:
        index = index.replace(f'"/{asset}"', f'"./{asset}"')
    cdn_policy = ' https://cdn.jsdelivr.net' if runtime == 'cdn' else ''
    policy = ("default-src 'none'; base-uri 'none'; object-src 'none'; "
              f"script-src 'self' 'wasm-unsafe-eval'{cdn_policy}; style-src 'self'; "
              f"connect-src 'self'{cdn_policy}; worker-src 'self'; img-src 'self' data:; "
              "form-action 'none'")
    index = index.replace('<head>', '<head>\n  <link rel="icon" href="data:,">\n  <meta http-equiv="Content-Security-Policy" '
                          f'content="{policy}">', 1)
    files['index.html'] = index.encode('utf-8')
    files['beryl-compiler.zip'], entries, archive_members = archive_modules()
    files['LICENSE'] = (ROOT / 'axiom/playground-LICENSE').read_bytes()
    files['.nojekyll'] = b''
    config = {'version': VERSION, 'indexURL': './runtime/' if runtime == 'vendor' else CDN}
    files['runtime-config.json'] = (json.dumps(config, indent=2) + '\n').encode()
    if runtime == 'vendor':
        for name in RUNTIME:
            files['runtime/' + name] = runtime_bytes(name, cache)
    files['_headers'] = ("/*\n  X-Content-Type-Options: nosniff\n  Referrer-Policy: no-referrer\n"
                          "  X-Frame-Options: DENY\n  Permissions-Policy: camera=(), microphone=(), geolocation=()\n"
                          f"  Content-Security-Policy: {policy}; frame-ancestors 'none'\n").encode()
    readme = f'''# beryl

An experimental playground for describing a calculation, setting its storage
limit, and exploring the plan chosen to carry it out. The browser runs the Python
compiler and independent source evaluator in a Web Worker, and executes the
checked plan as compiled WebAssembly. No compilation server or account is needed.

Serve this folder over HTTP/HTTPS; opening index.html as file:// does not support
Workers. For a local preview: `python -m http.server 8765 --directory PATH`.

## Scope

This early demo supports one exact i32 two-stage stencil, with
(H+1)*(W+1) <= 256 and input values 0..1023. The compiled Wasm instance is reused
while the exact source stays unchanged. Every run validates inputs and compares
the complete compiled observation with an independent evaluation of the source.
Reports describe these bounded runs; they do not certify larger computations.
Browser code and downloaded reports can be modified, so reports are not
authoritative attestations. The Performance page distinguishes browser and
same-host native measurements; C and Rust programs are compiled before timing.

## License and source

The demo is released under the MIT License in LICENSE, copyright 2026 NtEuphoria.
This grant covers the thirteen compiler/runtime Python modules named in
release-manifest.json, the five UI/transport assets (index.html, app.js,
style.css, transport.js, worker.js), and their accompanying demo documentation.
The Python sources are included in beryl-compiler.zip, including the Wasm backend
and finite-plan native C generator for reproducing compiled programs. The
same-host C and Rust comparison sources are benchmark.c and benchmark.rs. The
license covers this release only and does not grant rights to material outside
it. Third-party runtime files retain their own licenses described below.

## Runtime and network

Pyodide {VERSION}, Python 3.12.7. Runtime mode: **{runtime}**.
{'The runtime is vendored and hash-checked. The application fetches only files from its own origin, about 14 MB on first load; normal browser caching applies.' if runtime == 'vendor' else 'The browser fetches the pinned runtime from https://cdn.jsdelivr.net/pyodide/v0.27.7/full/. This requires internet access and trusts that CDN at runtime; the default vendor build avoids that external dependency.'}
No Python packages beyond the bundled standard library are loaded. Source and
input values stay in the browser. There is no analytics or project submission.
Initialization has a 60-second timeout; computations have a 15-second timeout.
A timeout terminates the Worker and the next request starts a fresh runtime.

Pyodide source and MPL-2.0 license:
https://github.com/pyodide/pyodide/tree/0.27.7
Python source and license:
https://github.com/python/cpython/tree/v3.12.7
The vendor build includes their license texts under runtime/.

## Hosting

Serve this folder as static files. Relative asset paths support a site root or a
repository subpath. Serve .js as JavaScript,
.wasm as application/wasm, and .json as application/json. No SPA rewrite or
backend function is needed. HTTPS is recommended for public hosting.

The _headers file configures compatible hosts (such as Cloudflare Pages or
Netlify). Other hosts must configure equivalent headers separately. GitHub
Pages ignores _headers; the document also carries a CSP meta tag. A Worker needs
script-src 'self' 'wasm-unsafe-eval', connect-src 'self', and worker-src 'self'.
For CDN mode also allow https://cdn.jsdelivr.net in script-src and connect-src.
Do not add unsafe-eval, broad wildcard origins, or disable TLS to fix startup.

release-manifest.json lists every release file's size and SHA-256, excluding
itself to avoid a recursive hash. Its compiler_modules field lists the thirteen
Python sources; compiler_archive_members additionally records the LICENSE
carried inside beryl-compiler.zip for standalone downloads. Rebuilds are
deterministic for identical inputs.
'''
    files['README.md'] = readme.encode()
    manifest = {'schema_version': 1, 'runtime': config, 'compiler_modules': entries,
                'compiler_archive_members': archive_members,
                'runtime_sources': {name: {'url': url, 'sha256': sha} for name, (sha, url) in RUNTIME.items()},
                'files': {name: {'bytes': len(raw), 'sha256': digest(raw)}
                          for name, raw in sorted(files.items())}}
    files['release-manifest.json'] = (json.dumps(manifest, indent=2, sort_keys=True) + '\n').encode()
    output.mkdir(parents=True, exist_ok=True)
    for name, raw in files.items():
        path = output / name
        path.parent.mkdir(parents=True, exist_ok=True)
        path.write_bytes(raw)
    print(json.dumps({'output': str(output), 'files': len(files),
                      'bytes': sum(map(len, files.values())), 'runtime': runtime}))


def main():
    parser = argparse.ArgumentParser(description=__doc__)
    parser.add_argument('--output', type=Path, required=True, help='new or empty output directory')
    parser.add_argument('--runtime', choices=('vendor', 'cdn'), default='vendor')
    parser.add_argument('--runtime-cache', type=Path,
                        help='optional directory of previously downloaded pinned runtime assets')
    args = parser.parse_args()
    try:
        build(args.output.resolve(), args.runtime, args.runtime_cache)
    except (OSError, ValueError) as error:
        parser.exit(1, f'build failed: {error}\n')


if __name__ == '__main__':
    main()

"""Smoke-test the explicit Docker COPY/context manifest without the source tree."""
import ast
import fnmatch
import os
from pathlib import Path
import shlex
import shutil
import subprocess
import sys
import tempfile
import unittest

ROOT = Path(__file__).resolve().parent


def context_includes(relative):
    # This repository uses a deny-all '*' followed by explicit file exceptions.
    included = True
    for line in (ROOT / '.dockerignore').read_text().splitlines():
        rule = line.strip()
        if not rule or rule.startswith('#'): continue
        allow = rule.startswith('!')
        pattern = rule.removeprefix('!').rstrip('/')
        if fnmatch.fnmatchcase(relative, pattern): included = allow
    return included


def local_runtime_modules():
    pending, found = ['server'], set()
    while pending:
        module = pending.pop()
        if module in found: continue
        found.add(module)
        tree = ast.parse((ROOT / (module + '.py')).read_text(encoding='utf-8'))
        for node in ast.walk(tree):
            names = [alias.name for alias in node.names] if isinstance(node, ast.Import) else [node.module] if isinstance(node, ast.ImportFrom) and node.module else []
            for name in names:
                name = name.split('.')[0]
                if (ROOT / (name + '.py')).is_file(): pending.append(name)
    return {name + '.py' for name in found}


class DeploymentBundleTests(unittest.TestCase):
    def test_packaged_runtime_starts_and_shop_serves_assets_and_buys_a_pepazo(self):
        with tempfile.TemporaryDirectory() as folder:
            bundle = Path(folder) / 'app'
            bundle.mkdir()
            for line in (ROOT / 'Dockerfile').read_text().splitlines():
                if not line.startswith('COPY '): continue
                *sources, destination = shlex.split(line)[1:]
                target = bundle / destination.removeprefix('/app').lstrip('/')
                target.mkdir(parents=True, exist_ok=True)
                for source in sources:
                    source_path = ROOT / source
                    self.assertTrue(source_path.exists(), source)
                    for file in source_path.rglob('*') if source_path.is_dir() else [source_path]:
                        if not file.is_file(): continue
                        relative = file.relative_to(ROOT).as_posix()
                        if not context_includes(relative):
                            self.assertTrue(source_path.is_dir(), f'COPY source excluded from context: {relative}')
                            continue
                        output = target / (file.relative_to(source_path) if source_path.is_dir() else file.name)
                        output.parent.mkdir(parents=True, exist_ok=True)
                        shutil.copyfile(file, output)
            actual = {file.relative_to(bundle).as_posix() for file in bundle.rglob('*') if file.is_file()}
            required = local_runtime_modules() | {'tienda.html', 'tienda.js', 'tienda.css',
                'assets/shop/pepe-shop.webp', 'assets/shop/pepazo.webp'}
            self.assertFalse(required - actual, f'Missing deploy files: {sorted(required - actual)}')
            # Isolated Python cannot accidentally import shop_service from this checkout.
            script = '''
import json, os, sys, threading, urllib.request
sys.path.insert(0, sys.argv[1])
import server
server.remote_backend = None
server.DB_FILE = os.path.join(sys.argv[2], 'db.json')
server.SECRETS_FILE = os.path.join(sys.argv[2], 'secrets.json')
server.write_json(server.DB_FILE, {'config': {}, 'duos': [{'id':'demo','teamName':'Demo','blueShells':0,'history':[]}], 'events':[]})
db = server.load_db()
db['betting']['wallets']['demo']['balance'] = 70
server.save_db(db)
token = server.create_player_session('demo')
httpd = server.ReusableServer(('127.0.0.1', 0), server.CustomHandler)
thread = threading.Thread(target=httpd.serve_forever, daemon=True); thread.start()
base = 'http://127.0.0.1:' + str(httpd.server_port)
try:
    for path in ('tienda.html','tienda.css','tienda.js','assets/shop/pepe-shop.webp','assets/shop/pepazo.webp'):
        with urllib.request.urlopen(base + '/' + path, timeout=5) as response:
            assert response.status == 200 and len(response.read()) > 100, path
    request = urllib.request.Request(base + '/api/shop', json.dumps({'quantity':1,'requestId':'packaged-shop-request-123'}).encode(), headers={'Content-Type':'application/json','Authorization':'Bearer ' + token})
    with urllib.request.urlopen(request, timeout=5) as response:
        result = json.load(response)
    assert result['purchase']['total'] == 70, result
    assert result['wallet']['balance'] == 0 and result['wallet']['inventory'] == 1, result
    print('PACKAGED_SHOP_OK')
finally:
    httpd.shutdown(); httpd.server_close(); thread.join(timeout=2)
'''
            env = {**os.environ, 'DATABASE_URL': '', 'PEPES_DATA_DIR': folder}
            result = subprocess.run([sys.executable, '-I', '-c', script, str(bundle), folder],
                cwd=bundle, env=env, capture_output=True, text=True, timeout=30)
            self.assertEqual(result.returncode, 0, result.stdout + result.stderr)
            self.assertIn('PACKAGED_SHOP_OK', result.stdout)


if __name__ == '__main__': unittest.main()

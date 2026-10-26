"""Every local runtime import must be included in the Docker image."""
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


def copied_sources():
    return [source for line in (ROOT/'Dockerfile').read_text().splitlines()
            if line.startswith('COPY ') for source in shlex.split(line)[1:-1]]


def in_context(filename):
    included = True
    for line in (ROOT/'.dockerignore').read_text().splitlines():
        rule = line.strip()
        if not rule or rule.startswith('#'):
            continue
        allowed = rule.startswith('!')
        if fnmatch.fnmatch(filename,rule[1:] if allowed else rule):
            included = allowed
    return included


class DockerRuntimeTests(unittest.TestCase):
    def test_all_local_imports_are_copied_and_allowed(self):
        sources = copied_sources()
        pending, seen = ['server.py'], set()
        while pending:
            filename = pending.pop()
            if filename in seen:
                continue
            seen.add(filename)
            self.assertIn(filename,sources,f'{filename} is missing from Docker COPY')
            self.assertTrue(in_context(filename),f'{filename} is excluded by .dockerignore')
            for node in ast.walk(ast.parse((ROOT/filename).read_text(encoding='utf-8'))):
                names = [alias.name for alias in node.names] if isinstance(node,ast.Import) else [node.module] if isinstance(node,ast.ImportFrom) and node.module else []
                for name in names:
                    local = name.split('.')[0]+'.py'
                    if (ROOT/local).is_file():
                        pending.append(local)

    def test_server_imports_from_packaged_files(self):
        with tempfile.TemporaryDirectory(prefix='duoq-runtime-') as folder:
            target=Path(folder)
            for source in copied_sources():
                origin=ROOT/source
                destination=target/source
                if origin.is_dir():
                    shutil.copytree(origin,destination,dirs_exist_ok=True)
                else:
                    destination.parent.mkdir(parents=True,exist_ok=True)
                    shutil.copyfile(origin,destination)
            env={key:value for key,value in os.environ.items() if key not in ('DATABASE_URL','PYTHONPATH')}
            result=subprocess.run([sys.executable,'-I','-B','-c',
                "import sys; sys.path.insert(0, '.'); import server; import champion_corrections; print('Runtime import OK')"],
                cwd=target,env=env,capture_output=True,text=True,timeout=30)
            self.assertEqual(result.returncode,0,result.stderr)
            self.assertIn('Runtime import OK',result.stdout)


if __name__=='__main__':
    unittest.main()
